"""
Entity Resolver — Intelligent cross-source identity resolution for Lexicon.

Takes raw scraped data from ANY organ (WhatsApp, GitHub, LinkedIn, etc.)
and resolves items into person-based entity nodes. Multiple scraped records
that refer to the same human being get merged into a single canonical node.

Architecture (multi-strategy consensus):
  ┌─────────────────────────────────────────────────────────┐
  │  RAW SCRAPED DATA (organ_id, class_name, values[])      │
  └──────────────┬──────────────────────────────────────────┘
                 │
       ┌─────────▼──────────┐
       │  SIGNAL EXTRACTION  │  Pull name, username, avatar,
       │                     │  phone, email, URL from each
       │                     │  scraped item (source-agnostic)
       └─────────┬──────────┘
                 │
       ┌─────────▼──────────────────────────────────────────┐
       │  MULTI-STRATEGY MATCHING (against existing nodes)   │
       │                                                     │
       │  Strategy 1: Normalized Name Similarity             │
       │    → Jaro-Winkler + phonetic (Soundex/Metaphone)    │
       │                                                     │
       │  Strategy 2: Username / Handle Fuzzy Match          │
       │    → Cross-platform handle correlation              │
       │    → e.g. "rishimehta04" ↔ "rishi_mehta"            │
       │                                                     │
       │  Strategy 3: Fingerprint Exact Match                │
       │    → Phone, email, unique URL → deterministic       │
       │                                                     │
       │  Strategy 4: Token-Set Overlap (TF-IDF inspired)    │
       │    → Name tokens as a set, Jaccard + IDF weighting  │
       │                                                     │
       │  Strategy 5: Contextual Co-occurrence               │
       │    → Same avatar URL, same phone, same org across   │
       │      different sources → strong merge signal         │
       └─────────┬──────────────────────────────────────────┘
                 │
       ┌─────────▼──────────┐
       │  CONSENSUS ENGINE   │  Each strategy votes with a
       │                     │  confidence score [0.0, 1.0].
       │                     │  Weighted vote; merge only
       │                     │  if consensus > threshold.
       └─────────┬──────────┘
                 │
       ┌─────────▼──────────┐
       │  ENTITY NODE STORE  │  SurrealDB: `entity` table
       │                     │  with aliases, sources, and
       │                     │  all raw data references.
       └────────────────────┘

Entity Node Schema (in SurrealDB):
  entity {
    entity_id:       string (uuid)
    canonical_name:  string ("Rishi Mehta")
    aliases:         [string] — all name variants seen
    usernames:       [string] — handles across platforms
    phones:          [string]
    emails:          [string]
    avatars:         [string] — avatar URLs
    sources:         [{ organ_id, class_name, item_index, raw }]
    name_tokens:     [string] — lowercased name tokens for search
    phonetic_keys:   [string] — Soundex/Metaphone codes
    created_at:      datetime
    updated_at:      datetime
  }
"""

from __future__ import annotations

import re
import uuid
import math
from dataclasses import dataclass, field
from typing import Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHONETIC ALGORITHMS (pure Python — no dependencies)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def soundex(name: str) -> str:
    """American Soundex algorithm. Returns 4-char code like 'M200'."""
    name = re.sub(r'[^a-zA-Z]', '', name).upper()
    if not name:
        return '0000'

    _map = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2',
        'X': '2', 'Z': '2',
        'D': '3', 'T': '3',
        'L': '4',
        'M': '5', 'N': '5',
        'R': '6',
    }

    result = name[0]
    prev_code = _map.get(name[0], '0')

    for ch in name[1:]:
        code = _map.get(ch, '0')
        if code != '0' and code != prev_code:
            result += code
        prev_code = code if code != '0' else prev_code

    return (result + '0000')[:4]


def double_metaphone(name: str) -> tuple[str, str]:
    """Simplified Double Metaphone. Returns (primary, alternate) codes.
    Handles common English/European name patterns."""
    name = re.sub(r'[^a-zA-Z]', '', name).upper()
    if not name:
        return ('', '')

    # Simplified: use consonant skeleton approach inspired by Metaphone
    vowels = set('AEIOU')
    primary = []
    alt = []

    i = 0
    while i < len(name):
        ch = name[i]

        if ch in vowels:
            if i == 0:
                primary.append('A')
                alt.append('A')
            i += 1
            continue

        # Digraphs
        pair = name[i:i+2]

        if pair == 'PH':
            primary.append('F'); alt.append('F'); i += 2; continue
        if pair == 'TH':
            primary.append('T'); alt.append('0'); i += 2; continue
        if pair == 'SH':
            primary.append('X'); alt.append('X'); i += 2; continue
        if pair == 'CH':
            primary.append('X'); alt.append('K'); i += 2; continue
        if pair == 'GH':
            primary.append('K'); alt.append('F'); i += 2; continue
        if pair == 'CK':
            primary.append('K'); alt.append('K'); i += 2; continue
        if pair == 'WR':
            primary.append('R'); alt.append('R'); i += 2; continue
        if pair == 'KN':
            primary.append('N'); alt.append('N'); i += 2; continue

        # Single chars
        if ch in ('B', 'D', 'F', 'J', 'K', 'L', 'M', 'N', 'P', 'R', 'T', 'V'):
            primary.append(ch); alt.append(ch)
        elif ch == 'C':
            if i + 1 < len(name) and name[i+1] in ('E', 'I', 'Y'):
                primary.append('S'); alt.append('S')
            else:
                primary.append('K'); alt.append('K')
        elif ch == 'G':
            if i + 1 < len(name) and name[i+1] in ('E', 'I', 'Y'):
                primary.append('J'); alt.append('K')
            else:
                primary.append('K'); alt.append('K')
        elif ch == 'H':
            if i == 0 or name[i-1] not in vowels:
                primary.append('H'); alt.append('H')
        elif ch == 'Q':
            primary.append('K'); alt.append('K')
        elif ch == 'S':
            if i + 1 < len(name) and name[i+1] in ('H',):
                primary.append('X'); alt.append('X')
            else:
                primary.append('S'); alt.append('S')
        elif ch == 'W':
            if i + 1 < len(name) and name[i+1] in vowels:
                primary.append('W'); alt.append('W')
        elif ch == 'X':
            primary.append('KS'); alt.append('KS')
        elif ch == 'Z':
            primary.append('S'); alt.append('S')

        i += 1

    return (''.join(primary)[:6], ''.join(alt)[:6])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STRING SIMILARITY (Jaro-Winkler — pure Python)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def jaro_similarity(s1: str, s2: str) -> float:
    """Jaro similarity between two strings."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 +
            (matches - transpositions / 2) / matches) / 3
    return jaro


def jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    """Jaro-Winkler similarity. Boosts score for common prefixes."""
    jaro = jaro_similarity(s1, s2)
    # Common prefix length (max 4)
    prefix_len = 0
    for i in range(min(4, len(s1), len(s2))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break
    return jaro + prefix_len * p * (1 - jaro)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TOKEN SET SIMILARITY (Jaccard + IDF-weighted)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def tokenize_name(name: str) -> set[str]:
    """Split a name/username into meaningful tokens.

    Handles:
      - Space/separator splitting: "rishi_mehta" → {"rishi", "mehta"}
      - CamelCase: "RishiMehta" → {"rishi", "mehta"}
      - Digit boundaries: "rishi04" → {"rishi", "04"}
      - Concatenated lowercase: "rishimehta" → {"rishimehta", "rishi", "mehta"}
        (via substring decomposition against the token itself)
    """
    # Replace separators with spaces
    name = re.sub(r'[._\-@/\\|]', ' ', name)
    # CamelCase split: "RishiMehta" → "Rishi Mehta"
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Digit boundaries: "rishi04" → "rishi 04"
    name = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', name)
    name = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', name)
    tokens = set()
    for t in name.lower().split():
        t = t.strip()
        if len(t) >= 2:  # Skip single chars
            tokens.add(t)
    # Substring decomposition: for long single tokens (likely concatenated
    # names like "rishimehta"), generate all substrings of length 3-8 so they
    # can match against individual name tokens ("rishi", "mehta").
    # This is a lightweight n-gram approach — the Jaccard/IDF scoring will
    # naturally reward real name overlaps over noise.
    raw_tokens = set(tokens)
    for t in raw_tokens:
        if len(t) >= 6:  # Only decompose long tokens
            for length in range(3, min(len(t), 9)):
                for start in range(0, len(t) - length + 1):
                    sub = t[start:start + length]
                    if len(sub) >= 3:
                        tokens.add(sub)
    return tokens


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard index of two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def weighted_token_overlap(tokens_a: set[str], tokens_b: set[str],
                           idf: dict[str, float] | None = None) -> float:
    """IDF-weighted overlap score between two token sets.
    Rare tokens (high IDF) get more weight than common ones."""
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    if not intersection:
        return 0.0

    if idf is None:
        # Uniform weighting fallback
        return len(intersection) / max(len(tokens_a), len(tokens_b))

    matched_weight = sum(idf.get(t, 1.0) for t in intersection)
    total_weight_a = sum(idf.get(t, 1.0) for t in tokens_a)
    total_weight_b = sum(idf.get(t, 1.0) for t in tokens_b)

    # Normalized: how much of the smaller set's weight is covered
    min_total = min(total_weight_a, total_weight_b)
    if min_total == 0:
        return 0.0
    return matched_weight / min_total


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  USERNAME SIMILARITY (cross-platform handle correlation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def normalize_username(handle: str) -> str:
    """Normalize a username/handle for comparison.
    'rishi_mehta' / 'rishi-mehta' / 'rishimehta' / 'RishiMehta04' → 'rishimehta'"""
    # Strip common prefixes
    handle = handle.lstrip('@')
    # Remove separators and digits for core comparison
    core = re.sub(r'[._\-\d]', '', handle).lower()
    return core


def username_similarity(u1: str, u2: str) -> float:
    """Compute cross-platform username similarity.
    Returns [0.0, 1.0]."""
    if not u1 or not u2:
        return 0.0

    u1_lower = u1.lower().lstrip('@')
    u2_lower = u2.lower().lstrip('@')

    # Exact match (case-insensitive)
    if u1_lower == u2_lower:
        return 1.0

    # Normalized core match (strips separators and digits)
    core1 = normalize_username(u1)
    core2 = normalize_username(u2)
    if core1 and core2 and core1 == core2:
        return 0.9

    # One contains the other
    if core1 in core2 or core2 in core1:
        shorter = min(len(core1), len(core2))
        longer = max(len(core1), len(core2))
        if shorter >= 4 and shorter / longer >= 0.6:
            return 0.75

    # Token overlap between usernames
    tokens1 = tokenize_name(u1)
    tokens2 = tokenize_name(u2)
    if tokens1 and tokens2:
        j = jaccard_similarity(tokens1, tokens2)
        if j > 0.5:
            return j * 0.7  # Dampen — usernames are short, high false-positive risk

    # Jaro-Winkler on normalized
    jw = jaro_winkler(core1, core2)
    if jw > 0.92:
        return jw * 0.6

    return 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL EXTRACTION — pull identity signals from raw data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Common field names across different scrapers that carry identity info
_NAME_FIELDS = {'name', 'contact_name', 'user', 'username', 'author', 'sender',
                'full_name', 'display_name', 'from', 'by', 'person', 'member',
                'avatar_name', 'title', 'heading', 'text_1', 'text'}
_USERNAME_FIELDS = {'username', 'handle', 'login', 'user_id', 'screen_name',
                    'user_url', 'link', 'url', 'profile_url', 'user_link'}
_AVATAR_FIELDS = {'avatar', 'avatar_url', 'image', 'profile_image', 'photo',
                  'src', 'icon', 'thumbnail'}
_PHONE_FIELDS = {'phone', 'phone_number', 'mobile', 'tel', 'contact'}
_EMAIL_FIELDS = {'email', 'mail', 'email_address'}

# Regex patterns
_PHONE_RE = re.compile(r'^\+?[\d\s\-().]{7,20}$')
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_URL_PROFILE_RE = re.compile(
    r'(?:github\.com|linkedin\.com/in|twitter\.com|x\.com|instagram\.com|'
    r'facebook\.com|t\.me)/([a-zA-Z0-9._\-]+)',
    re.IGNORECASE
)


@dataclass
class IdentitySignals:
    """Extracted identity signals from a single scraped item."""
    names: list[str] = field(default_factory=list)
    usernames: list[str] = field(default_factory=list)
    avatars: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    raw: dict | str = field(default_factory=dict)
    source_organ: str = ''
    source_class: str = ''

    @property
    def primary_name(self) -> str:
        """Best guess at the display name."""
        if self.names:
            # Prefer the longest name (likely the full name)
            return max(self.names, key=len)
        if self.usernames:
            return self.usernames[0]
        return ''

    @property
    def has_identity(self) -> bool:
        """Does this signal set have enough to identify a person?"""
        return bool(self.names or self.usernames or self.phones or self.emails)

    @property
    def name_tokens(self) -> set[str]:
        tokens = set()
        for n in self.names:
            tokens |= tokenize_name(n)
        return tokens

    @property
    def phonetic_keys(self) -> list[str]:
        keys = []
        for n in self.names:
            for part in n.split():
                part = part.strip()
                if len(part) >= 2:
                    keys.append(soundex(part))
                    mp, ma = double_metaphone(part)
                    if mp:
                        keys.append(f'MP:{mp}')
                    if ma and ma != mp:
                        keys.append(f'MA:{ma}')
        return list(set(keys))


def extract_signals(item: dict | str, organ_id: str = '',
                    class_name: str = '') -> IdentitySignals:
    """Extract identity signals from a single scraped data item.
    Works with both structured dicts and flat strings."""
    signals = IdentitySignals(
        raw=item,
        source_organ=organ_id,
        source_class=class_name,
    )

    if isinstance(item, str):
        # Flat string — try to extract a name from it
        text = item.strip()
        if text and not text.startswith('http') and len(text) < 200:
            # Check if it looks like a phone number
            if _PHONE_RE.match(text):
                signals.phones.append(text)
            elif _EMAIL_RE.match(text):
                signals.emails.append(text)
            else:
                # Assume it's a name or message — extract the name part
                # Common pattern: "Name: message" or "Name message more text"
                # Take first meaningful segment
                signals.names.append(text)
        # Check for embedded profile URLs
        m = _URL_PROFILE_RE.search(text)
        if m:
            signals.usernames.append(m.group(1))
        return signals

    if not isinstance(item, dict):
        return signals

    # Structured dict — inspect each field
    for key, value in item.items():
        if not value or not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue

        key_lower = key.lower()

        # Check for names
        if key_lower in _NAME_FIELDS:
            if not _PHONE_RE.match(value) and not _EMAIL_RE.match(value):
                signals.names.append(value)

        # Check for usernames / handles
        if key_lower in _USERNAME_FIELDS:
            # Extract username from URLs
            m = _URL_PROFILE_RE.search(value)
            if m:
                signals.usernames.append(m.group(1))
            elif not value.startswith('http'):
                signals.usernames.append(value)

        # Check for avatars
        if key_lower in _AVATAR_FIELDS:
            if value.startswith('http') or value.startswith('data:'):
                signals.avatars.append(value)

        # Phone numbers
        if key_lower in _PHONE_FIELDS or _PHONE_RE.match(value):
            if _PHONE_RE.match(value):
                signals.phones.append(value)

        # Emails
        if key_lower in _EMAIL_FIELDS or _EMAIL_RE.match(value):
            if _EMAIL_RE.match(value):
                signals.emails.append(value)

        # Scan all URL-like values for profile usernames
        if 'url' in key_lower or 'link' in key_lower or 'href' in key_lower:
            m = _URL_PROFILE_RE.search(value)
            if m:
                signals.usernames.append(m.group(1))

    # Deduplicate
    signals.names = list(dict.fromkeys(signals.names))
    signals.usernames = list(dict.fromkeys(signals.usernames))
    signals.avatars = list(dict.fromkeys(signals.avatars))
    signals.phones = list(dict.fromkeys(signals.phones))
    signals.emails = list(dict.fromkeys(signals.emails))

    return signals


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MATCHING STRATEGIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class StrategyVote:
    """A single strategy's vote on whether two signal sets match."""
    strategy: str
    confidence: float  # 0.0 to 1.0
    reason: str = ''


def strategy_fingerprint(signals: IdentitySignals,
                         node: dict) -> StrategyVote:
    """Strategy 1: Exact fingerprint match on phone/email.
    Deterministic — if phone or email matches, it's the same person."""
    node_phones = set(node.get('phones', []))
    node_emails = set(node.get('emails', []))

    for p in signals.phones:
        # Normalize phone: strip spaces, dashes, parens
        p_norm = re.sub(r'[\s\-().]+', '', p)
        for np in node_phones:
            np_norm = re.sub(r'[\s\-().]+', '', np)
            if p_norm == np_norm:
                return StrategyVote('fingerprint', 1.0,
                                    f'phone match: {p}')

    for e in signals.emails:
        if e.lower() in {x.lower() for x in node_emails}:
            return StrategyVote('fingerprint', 1.0,
                                f'email match: {e}')

    return StrategyVote('fingerprint', 0.0)


def strategy_name_similarity(signals: IdentitySignals,
                             node: dict) -> StrategyVote:
    """Strategy 2: Name similarity via Jaro-Winkler + phonetic matching."""
    if not signals.names:
        return StrategyVote('name_similarity', 0.0)

    node_aliases = node.get('aliases', [])
    if not node_aliases:
        return StrategyVote('name_similarity', 0.0)

    best_score = 0.0
    best_pair = ('', '')

    for sig_name in signals.names:
        sig_lower = sig_name.lower().strip()
        for alias in node_aliases:
            alias_lower = alias.lower().strip()

            # Exact match (case-insensitive)
            if sig_lower == alias_lower:
                return StrategyVote('name_similarity', 1.0,
                                    f'exact name: "{sig_name}" = "{alias}"')

            # Jaro-Winkler
            jw = jaro_winkler(sig_lower, alias_lower)

            # Phonetic boost: if Soundex or Metaphone matches, boost
            phonetic_boost = 0.0
            sig_parts = sig_lower.split()
            alias_parts = alias_lower.split()
            if sig_parts and alias_parts:
                # Compare first-name Soundex
                if soundex(sig_parts[0]) == soundex(alias_parts[0]):
                    phonetic_boost += 0.05
                # Compare last-name Soundex (if multi-word)
                if len(sig_parts) > 1 and len(alias_parts) > 1:
                    if soundex(sig_parts[-1]) == soundex(alias_parts[-1]):
                        phonetic_boost += 0.08

                # Double Metaphone match on whole name
                mp1, _ = double_metaphone(sig_lower.replace(' ', ''))
                mp2, _ = double_metaphone(alias_lower.replace(' ', ''))
                if mp1 and mp2 and mp1 == mp2:
                    phonetic_boost += 0.1

            score = min(1.0, jw + phonetic_boost)
            if score > best_score:
                best_score = score
                best_pair = (sig_name, alias)

    if best_score >= 0.88:
        return StrategyVote('name_similarity', best_score,
                            f'JW+phonetic: "{best_pair[0]}" ~ "{best_pair[1]}" = {best_score:.3f}')
    return StrategyVote('name_similarity', best_score * 0.5,
                        f'weak: "{best_pair[0]}" ~ "{best_pair[1]}" = {best_score:.3f}')


def strategy_username_match(signals: IdentitySignals,
                            node: dict) -> StrategyVote:
    """Strategy 3: Cross-platform username/handle correlation."""
    if not signals.usernames:
        return StrategyVote('username_match', 0.0)

    node_usernames = node.get('usernames', [])
    node_aliases = node.get('aliases', [])
    all_node_handles = node_usernames + node_aliases

    if not all_node_handles:
        return StrategyVote('username_match', 0.0)

    best_score = 0.0
    best_pair = ('', '')

    for sig_u in signals.usernames:
        for node_u in all_node_handles:
            score = username_similarity(sig_u, node_u)
            if score > best_score:
                best_score = score
                best_pair = (sig_u, node_u)

    if best_score >= 0.7:
        return StrategyVote('username_match', best_score,
                            f'handle: "{best_pair[0]}" ~ "{best_pair[1]}" = {best_score:.3f}')
    return StrategyVote('username_match', best_score * 0.3)


def strategy_token_overlap(signals: IdentitySignals,
                           node: dict,
                           idf: dict[str, float] | None = None) -> StrategyVote:
    """Strategy 4: Token-set overlap with IDF weighting.
    e.g., tokens("Rishi Mehta") ∩ tokens("rishimehta04") → {"rishi", "mehta"}

    Uses a two-tier approach:
      1. Direct token set overlap (Jaccard / IDF-weighted)
      2. Substring containment: check if node tokens appear as substrings
         of the signal's raw tokens (handles concatenated usernames like
         "rishimehta" containing "rishi" + "mehta")
    """
    # Collect raw (non-decomposed) tokens from names
    sig_raw_tokens = set()
    for n in signals.names:
        name = re.sub(r'[._\-@/\\|]', ' ', n)
        name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
        name = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', name)
        name = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', name)
        for t in name.lower().split():
            t = t.strip()
            if len(t) >= 2:
                sig_raw_tokens.add(t)
    # Also collect raw tokens from usernames
    for u in signals.usernames:
        uname = re.sub(r'[._\-@/\\|]', ' ', u)
        uname = re.sub(r'([a-z])([A-Z])', r'\1 \2', uname)
        uname = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', uname)
        uname = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', uname)
        for t in uname.lower().split():
            t = t.strip()
            if len(t) >= 2:
                sig_raw_tokens.add(t)

    node_tokens = set(node.get('name_tokens', []))

    if not sig_raw_tokens or not node_tokens:
        return StrategyVote('token_overlap', 0.0)

    # Tier 1: Direct overlap
    direct_overlap = sig_raw_tokens & node_tokens
    score_direct = 0.0
    if direct_overlap:
        score_direct = weighted_token_overlap(sig_raw_tokens, node_tokens, idf)
        j = jaccard_similarity(sig_raw_tokens, node_tokens)
        score_direct = max(score_direct, j)

    # Tier 2: Substring containment — check if node tokens are contained
    # within signal's longer concatenated tokens, or vice versa.
    # e.g., "rishimehta" contains "rishi" and "mehta"
    substring_matches = set()
    for sig_t in sig_raw_tokens:
        if len(sig_t) >= 6:  # Only check long tokens for containment
            for node_t in node_tokens:
                if len(node_t) >= 3 and node_t in sig_t and node_t != sig_t:
                    substring_matches.add(node_t)
    for node_t in node_tokens:
        if len(node_t) >= 6:
            for sig_t in sig_raw_tokens:
                if len(sig_t) >= 3 and sig_t in node_t and sig_t != node_t:
                    substring_matches.add(sig_t)

    score_substring = 0.0
    if substring_matches:
        # How many of the node's tokens did we find as substrings?
        coverage = len(substring_matches) / max(len(node_tokens), 1)
        score_substring = min(1.0, coverage * 0.9)

    final = max(score_direct, score_substring)

    if final >= 0.5:
        matched = direct_overlap | substring_matches
        return StrategyVote('token_overlap', final,
                            f'tokens matched: {matched}, score={final:.3f}')
    return StrategyVote('token_overlap', final * 0.4)


def strategy_contextual(signals: IdentitySignals,
                        node: dict) -> StrategyVote:
    """Strategy 5: Contextual co-occurrence.
    Same avatar URL across sources = strong signal.
    Same org/group membership = weak supporting signal."""
    score = 0.0
    reasons = []

    # Avatar URL match (very strong — avatars are usually unique per person)
    if signals.avatars and node.get('avatars'):
        sig_avatars = set(signals.avatars)
        node_avatars = set(node.get('avatars', []))
        if sig_avatars & node_avatars:
            score += 0.85
            reasons.append('avatar URL match')

    # Phone partial match (last 7 digits)
    if signals.phones and node.get('phones'):
        for p in signals.phones:
            p_digits = re.sub(r'\D', '', p)[-7:]
            for np in node.get('phones', []):
                np_digits = re.sub(r'\D', '', np)[-7:]
                if len(p_digits) >= 7 and p_digits == np_digits:
                    score += 0.9
                    reasons.append('phone digits match')

    return StrategyVote('contextual', min(1.0, score),
                        '; '.join(reasons) if reasons else '')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONSENSUS ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Strategy weights for the consensus vote
STRATEGY_WEIGHTS = {
    'fingerprint':    5.0,   # Deterministic matches dominate
    'name_similarity': 2.5,
    'username_match':  2.0,
    'token_overlap':   1.5,
    'contextual':      4.5,   # Avatar/phone matches are very strong signals
}

# Merge threshold — weighted consensus must exceed this
MERGE_THRESHOLD = 0.50


@dataclass
class ConsensusResult:
    """Result of the multi-strategy consensus vote."""
    should_merge: bool
    consensus_score: float  # [0.0, 1.0]
    votes: list[StrategyVote] = field(default_factory=list)
    matched_entity_id: str = ''

    @property
    def explanation(self) -> str:
        parts = [f'consensus={self.consensus_score:.3f} '
                 f'(threshold={MERGE_THRESHOLD})']
        for v in self.votes:
            if v.confidence > 0:
                parts.append(f'  {v.strategy}: {v.confidence:.3f}'
                             + (f' ({v.reason})' if v.reason else ''))
        return '\n'.join(parts)


def compute_consensus(signals: IdentitySignals, node: dict,
                      idf: dict[str, float] | None = None) -> ConsensusResult:
    """Run all strategies and compute weighted consensus.

    Only APPLICABLE strategies participate in the vote — a strategy is
    non-applicable when neither side has the relevant signal type (e.g.,
    fingerprint is non-applicable when neither side has phone/email).
    This prevents absent signals from diluting strong matches.
    """
    votes = [
        strategy_fingerprint(signals, node),
        strategy_name_similarity(signals, node),
        strategy_username_match(signals, node),
        strategy_token_overlap(signals, node, idf),
        strategy_contextual(signals, node),
    ]

    # If any deterministic match (fingerprint) has confidence = 1.0,
    # auto-merge regardless of other strategies
    for v in votes:
        if v.strategy == 'fingerprint' and v.confidence >= 1.0:
            return ConsensusResult(
                should_merge=True,
                consensus_score=1.0,
                votes=votes,
            )

    # Determine which strategies are applicable (both sides have signals)
    def _is_applicable(v: StrategyVote) -> bool:
        s = v.strategy
        if s == 'fingerprint':
            has_sig = bool(signals.phones or signals.emails)
            has_node = bool(node.get('phones') or node.get('emails'))
            return has_sig and has_node
        if s == 'name_similarity':
            return bool(signals.names) and bool(node.get('aliases'))
        if s == 'username_match':
            return bool(signals.usernames) and bool(
                node.get('usernames') or node.get('aliases'))
        if s == 'token_overlap':
            has_sig_tokens = bool(signals.names or signals.usernames)
            return has_sig_tokens and bool(node.get('name_tokens'))
        if s == 'contextual':
            has_sig = bool(signals.avatars or signals.phones)
            has_node = bool(node.get('avatars') or node.get('phones'))
            return has_sig and has_node
        return True

    # Weighted average over applicable strategies only
    total_weight = 0.0
    weighted_sum = 0.0
    for v in votes:
        if not _is_applicable(v):
            continue
        w = STRATEGY_WEIGHTS.get(v.strategy, 1.0)
        weighted_sum += v.confidence * w
        total_weight += w

    consensus = weighted_sum / total_weight if total_weight > 0 else 0.0

    return ConsensusResult(
        should_merge=consensus >= MERGE_THRESHOLD,
        consensus_score=consensus,
        votes=votes,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  IDF COMPUTATION (global token rarity)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_idf(entities: list[dict]) -> dict[str, float]:
    """Compute IDF scores for name tokens across all entities.
    Rarer tokens get higher IDF → more weight in matching."""
    doc_count = len(entities)
    if doc_count == 0:
        return {}

    token_doc_freq: dict[str, int] = {}
    for ent in entities:
        tokens = set(ent.get('name_tokens', []))
        for t in tokens:
            token_doc_freq[t] = token_doc_freq.get(t, 0) + 1

    idf = {}
    for token, df in token_doc_freq.items():
        idf[token] = math.log((doc_count + 1) / (df + 1)) + 1.0

    return idf


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CANONICAL NAME SELECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def choose_canonical_name(aliases: list[str]) -> str:
    """Pick the best canonical display name from a list of aliases.

    Heuristics:
      1. Prefer properly capitalized names (Title Case)
      2. Prefer names with spaces (multi-word = full name)
      3. Prefer longer names (more complete)
      4. Avoid usernames / handles (no digits, no @)
    """
    if not aliases:
        return 'Unknown'
    if len(aliases) == 1:
        return aliases[0]

    scored = []
    for name in aliases:
        s = 0.0
        # Multi-word bonus
        parts = name.split()
        if len(parts) >= 2:
            s += 20.0
        if len(parts) >= 3:
            s += 5.0

        # Title case bonus
        if name == name.title():
            s += 10.0
        elif name[0].isupper():
            s += 5.0

        # Length bonus (diminishing)
        s += min(len(name), 30) * 0.5

        # Penalty for digits (likely a username)
        digit_ratio = sum(c.isdigit() for c in name) / max(len(name), 1)
        s -= digit_ratio * 15.0

        # Penalty for @ prefix
        if name.startswith('@'):
            s -= 10.0

        # Penalty for all-lowercase single word (likely handle)
        if len(parts) == 1 and name == name.lower():
            s -= 5.0

        scored.append((s, name))

    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTITY RESOLVER (main class)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EntityResolver:
    """Resolves raw scraped data into person-based entity nodes.

    Usage:
        resolver = EntityResolver(memory)
        stats = await resolver.resolve(organ_id, class_name, scraped_values)
        # → creates/updates entity nodes in Memory
    """

    def __init__(self, memory):
        self.memory = memory

    async def resolve(self, organ_id: str, class_name: str,
                      values: list) -> dict:
        """Process a batch of scraped values and resolve them into entities.

        Returns stats: { created, merged, skipped, entities }
        """
        stats = {'created': 0, 'merged': 0, 'skipped': 0, 'entities': []}

        # 1. Extract signals from each item
        all_signals = []
        for i, item in enumerate(values):
            sig = extract_signals(item, organ_id, class_name)
            if sig.has_identity:
                all_signals.append((i, sig))
            else:
                stats['skipped'] += 1

        if not all_signals:
            return stats

        # 2. Load existing entities from memory
        existing_entities = await self.memory.list_entities()

        # 3. Compute IDF from existing entities for token weighting
        idf = compute_idf(existing_entities)

        # 4. For each signal set, find best matching entity or create new
        for item_idx, signals in all_signals:
            best_match: ConsensusResult | None = None
            best_entity: dict | None = None

            # Compare against all existing entities
            for entity in existing_entities:
                result = compute_consensus(signals, entity, idf)
                if result.should_merge:
                    if (best_match is None or
                            result.consensus_score > best_match.consensus_score):
                        best_match = result
                        best_entity = entity

            if best_match and best_entity:
                # Merge into existing entity
                await self._merge_into_entity(
                    best_entity['entity_id'], signals, organ_id,
                    class_name, item_idx
                )
                stats['merged'] += 1
                stats['entities'].append(best_entity['entity_id'])

                # Update the in-memory copy for subsequent comparisons
                self._update_entity_in_list(
                    existing_entities, best_entity['entity_id'], signals
                )
                # Recompute IDF periodically (every 50 items)
                if stats['merged'] % 50 == 0:
                    idf = compute_idf(existing_entities)
            else:
                # Create new entity
                entity_id = await self._create_entity(
                    signals, organ_id, class_name, item_idx
                )
                stats['created'] += 1
                stats['entities'].append(entity_id)

                # Add to in-memory list for subsequent comparisons
                new_entity = self._build_entity_dict(entity_id, signals,
                                                     organ_id, class_name,
                                                     item_idx)
                existing_entities.append(new_entity)
                idf = compute_idf(existing_entities)

        return stats

    async def resolve_all_sources(self) -> dict:
        """Re-resolve ALL scraped data across ALL organs.
        Useful for rebuilding the entity graph from scratch."""
        # Clear existing entities
        await self.memory.clear_entities()

        # Get all organs
        organs = await self.memory.list_organs()
        total_stats = {'created': 0, 'merged': 0, 'skipped': 0,
                       'organs_processed': 0}

        for organ in organs:
            oid = organ.get('organ_id', '')
            if not oid:
                continue

            data = await self.memory.get_scraped_data(oid)
            for dataset in data:
                cname = dataset.get('class_name', '')
                values = dataset.get('values', [])
                if not values:
                    continue

                stats = await self.resolve(oid, cname, values)
                total_stats['created'] += stats['created']
                total_stats['merged'] += stats['merged']
                total_stats['skipped'] += stats['skipped']

            total_stats['organs_processed'] += 1

        return total_stats

    def _build_entity_dict(self, entity_id: str, signals: IdentitySignals,
                           organ_id: str, class_name: str,
                           item_idx: int) -> dict:
        """Build a dict representation of a new entity (for in-memory list)."""
        aliases = list(signals.names)
        all_names = aliases + list(signals.usernames)
        canonical = choose_canonical_name(all_names) if all_names else 'Unknown'

        tokens = list(signals.name_tokens)
        # Also add username tokens
        for u in signals.usernames:
            tokens.extend(tokenize_name(u))
        tokens = list(set(tokens))

        return {
            'entity_id': entity_id,
            'canonical_name': canonical,
            'aliases': aliases,
            'usernames': list(signals.usernames),
            'phones': list(signals.phones),
            'emails': list(signals.emails),
            'avatars': list(signals.avatars),
            'name_tokens': tokens,
            'phonetic_keys': signals.phonetic_keys,
            'sources': [{
                'organ_id': organ_id,
                'class_name': class_name,
                'item_index': item_idx,
                'raw': signals.raw,
            }],
        }

    async def _create_entity(self, signals: IdentitySignals,
                             organ_id: str, class_name: str,
                             item_idx: int) -> str:
        """Create a new entity node in the database."""
        entity_id = uuid.uuid4().hex[:16]
        entity = self._build_entity_dict(entity_id, signals,
                                          organ_id, class_name, item_idx)
        await self.memory.create_entity(entity)
        return entity_id

    async def _merge_into_entity(self, entity_id: str,
                                 signals: IdentitySignals,
                                 organ_id: str, class_name: str,
                                 item_idx: int):
        """Merge new signals into an existing entity node."""
        source = {
            'organ_id': organ_id,
            'class_name': class_name,
            'item_index': item_idx,
            'raw': signals.raw,
        }
        await self.memory.merge_entity(
            entity_id=entity_id,
            new_names=signals.names,
            new_usernames=signals.usernames,
            new_phones=signals.phones,
            new_emails=signals.emails,
            new_avatars=signals.avatars,
            new_source=source,
            new_name_tokens=list(signals.name_tokens),
            new_phonetic_keys=signals.phonetic_keys,
        )

    def _update_entity_in_list(self, entities: list[dict],
                               entity_id: str,
                               signals: IdentitySignals):
        """Update the in-memory entity list after a merge
        (so subsequent comparisons in the same batch see the new data)."""
        for ent in entities:
            if ent['entity_id'] == entity_id:
                # Merge aliases
                existing_aliases = set(ent.get('aliases', []))
                existing_aliases.update(signals.names)
                ent['aliases'] = list(existing_aliases)

                # Merge usernames
                existing_u = set(ent.get('usernames', []))
                existing_u.update(signals.usernames)
                ent['usernames'] = list(existing_u)

                # Merge tokens
                existing_t = set(ent.get('name_tokens', []))
                existing_t.update(signals.name_tokens)
                for u in signals.usernames:
                    existing_t.update(tokenize_name(u))
                ent['name_tokens'] = list(existing_t)

                # Merge phonetic keys
                existing_pk = set(ent.get('phonetic_keys', []))
                existing_pk.update(signals.phonetic_keys)
                ent['phonetic_keys'] = list(existing_pk)

                # Merge phones/emails/avatars
                for field_name, new_vals in [
                    ('phones', signals.phones),
                    ('emails', signals.emails),
                    ('avatars', signals.avatars),
                ]:
                    existing = set(ent.get(field_name, []))
                    existing.update(new_vals)
                    ent[field_name] = list(existing)

                # Update canonical name
                all_names = ent['aliases'] + ent.get('usernames', [])
                ent['canonical_name'] = choose_canonical_name(all_names)

                break
