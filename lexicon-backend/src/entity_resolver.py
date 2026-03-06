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
       │  SIGNAL EXTRACTION  │  spaCy NER + field-name heuristics
       │  (NLP-first)        │  classify PERSON, DATE, TIME, etc.
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
       ┌─────────▼──────────────────────────────────────────┐
       │  ENTITY NODE STORE  │  SurrealDB (graph DB):       │
       │  (graph-native)     │  entity nodes + RELATE edges │
       │                     │  + shared token/word nodes    │
       │                     │  + frequency tracking         │
       └────────────────────────────────────────────────────┘

Entity Node Schema (in SurrealDB):
  entity {
    entity_id:         string (uuid)
    canonical_name:    string ("Rishi Mehta")
    aliases:           [string] — all name variants seen
    alias_freq:        { alias → count } — observation frequency per alias
    usernames:         [string] — handles across platforms
    phones:            [string]
    emails:            [string]
    avatars:           [string] — avatar URLs
    sources:           [{ organ_id, class_name, item_index, raw }]
    name_tokens:       [string] — lowercased name tokens for search
    phonetic_keys:     [string] — Soundex/Metaphone codes
    observation_count: int — total times this entity was observed
    confidence:        float — [0.0, 1.0] grows with evidence
    created_at:        datetime
    updated_at:        datetime
  }

Graph Edges (SurrealDB RELATE):
  entity -[mentions]-> word    (shared word node, deduplicated)
  entity -[observed_as]-> alias_node  (name variant with count)
  entity -[linked_to]-> entity (cross-source identity links)

NER:
  Uses spaCy (en_core_web_sm) for entity classification instead of
  hardcoded regex/word-lists. The model handles PERSON, DATE, TIME,
  GPE, ORG, CARDINAL, ORDINAL, etc. natively.
"""

from __future__ import annotations

import re
import uuid
import math
from dataclasses import dataclass, field
from typing import Optional

import spacy

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  spaCy NLP MODEL (loaded once, shared across all calls)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

try:
    _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
except OSError:
    # Fallback: if model not installed, NER features degrade gracefully
    _nlp = None
    print("⚠️  spaCy model 'en_core_web_sm' not found. "
          "NER will fall back to heuristics. "
          "Install with: uv pip install en-core-web-sm@https://github.com/"
          "explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/"
          "en_core_web_sm-3.8.0-py3-none-any.whl")


def _ner_classify(text: str) -> list[tuple[str, str]]:
    """Run spaCy NER on text. Returns [(entity_text, label), ...].

    Labels include: PERSON, DATE, TIME, GPE (geo-political entity),
    ORG (organization), CARDINAL, ORDINAL, MONEY, PERCENT, etc.
    """
    if _nlp is None:
        return []
    doc = _nlp(text)
    return [(ent.text, ent.label_) for ent in doc.ents]


def _ner_is_person(text: str) -> bool:
    """Check if spaCy considers this text a PERSON entity."""
    entities = _ner_classify(text)
    for ent_text, label in entities:
        if label == "PERSON":
            return True
    return False


def _ner_label(text: str) -> str | None:
    """Get the dominant NER label for a text string.

    Returns the label if spaCy recognizes it as a single entity,
    None if ambiguous or unrecognized.
    """
    entities = _ner_classify(text)
    if not entities:
        return None
    # If the whole text (or most of it) is one entity, return that label
    for ent_text, label in entities:
        # The entity covers most of the input text
        if len(ent_text) / max(len(text.strip()), 1) > 0.6:
            return label
    return entities[0][1] if len(entities) == 1 else None


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

# Minimal noise tokens — only the most obvious functional words.
# spaCy handles the real classification; this is just for token-set math.
_NOISE_TOKENS = frozenset({
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'not', 'are',
    'was', 'were', 'been', 'has', 'have', 'had', 'will', 'can', 'may',
    'but', 'its', 'your', 'you', 'our', 'all', 'any', 'few',
    'ago', 'just', 'now',
    # Time/date words that should never be name tokens
    'today', 'yesterday', 'tomorrow', 'tonight', 'morning', 'evening',
    'afternoon', 'night', 'week', 'month', 'year', 'day', 'days',
    'hours', 'hour', 'minutes', 'minute', 'seconds', 'second',
    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    'saturday', 'sunday',
    'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct',
    'nov', 'dec', 'january', 'february', 'march', 'april',
    'june', 'july', 'august', 'september', 'october', 'november',
    'december',
    # UI / messaging noise
    'online', 'offline', 'typing', 'seen', 'read', 'sent', 'pending',
    'message', 'messages', 'chat', 'call', 'photo', 'video', 'audio',
    'file', 'image', 'link', 'media', 'group', 'channel',
    'deleted', 'blocked', 'muted', 'archived',
    'unknown', 'none', 'null', 'undefined', 'anonymous',
})


def tokenize_name(name: str) -> set[str]:
    """Split a name/username into meaningful tokens.

    Handles:
      - Space/separator splitting: "rishi_mehta" → {"rishi", "mehta"}
      - CamelCase: "RishiMehta" → {"rishi", "mehta"}
      - Digit boundaries: "rishi04" → {"rishi", "04"}
      - Concatenated lowercase: "rishimehta" → {"rishimehta", "rishi", "mehta"}
        (via substring decomposition against the token itself)
      - Noise token filtering: "yesterday", "online", "message" are excluded
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
        if len(t) >= 2 and t not in _NOISE_TOKENS:
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
                    if len(sub) >= 3 and sub not in _NOISE_TOKENS:
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
# NOTE: 'text', 'heading', 'title' are intentionally excluded — they
# typically contain message bodies, article titles, or UI labels, not
# person names. Only fields that specifically denote a person are here.
_NAME_FIELDS = {'name', 'contact_name', 'user', 'username', 'author', 'sender',
                'full_name', 'display_name', 'from', 'by', 'person', 'member',
                'avatar_name'}
_USERNAME_FIELDS = {'username', 'handle', 'login', 'user_id', 'screen_name',
                    'user_url', 'link', 'url', 'profile_url', 'user_link'}
_AVATAR_FIELDS = {'avatar', 'avatar_url', 'image', 'profile_image', 'photo',
                  'src', 'icon', 'thumbnail'}
_PHONE_FIELDS = {'phone', 'phone_number', 'mobile', 'tel', 'contact'}
_EMAIL_FIELDS = {'email', 'mail', 'email_address'}

# Regex patterns
# Phone: requires either a '+' prefix (international) OR at least one
# separator char (space, dash, dot, parens) to distinguish from bare
# numeric IDs and Unix timestamps. Pure digit strings like "1704067200"
# won't match — those are handled by _TIMESTAMP_RE.
_PHONE_RE = re.compile(
    r'^(?:'
    r'\+[\d\s\-().]{6,19}'              # International: +91 9876543210
    r'|[\d]{1,4}[\s\-().]+[\d\s\-().]{4,18}'  # Local with separators: 98765-43210
    r'|\([\d]+\)\s*[\d\s\-().]{4,15}'   # Parens prefix: (555) 123-4567
    r')$'
)
# More lenient phone regex for when the field is explicitly named 'phone'/
# 'mobile'/etc. — the field name provides semantic context, so bare digit
# strings are acceptable (but still 7-15 digits, not timestamps).
_PHONE_FIELD_RE = re.compile(r'^[\d\s\-().+]{7,18}$')
_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_URL_PROFILE_RE = re.compile(
    r'(?:github\.com|linkedin\.com/in|twitter\.com|x\.com|instagram\.com|'
    r'facebook\.com|t\.me)/([a-zA-Z0-9._\-]+)',
    re.IGNORECASE
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  NOISE FILTERING — NLP-first with regex fallbacks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── Pure-digit or pure-punctuation ──
_PURE_DIGITS_RE = re.compile(r'^[\d\s.,;:!?\-+*/=<>()[\]{}#@$%^&|~`"\'\\]+$')

# ── ISO / Unix timestamps ──
_TIMESTAMP_RE = re.compile(
    r'^(?:'
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}'            # ISO 8601
    r'|\d{10,13}'                                 # Unix timestamp (sec or ms)
    r')$'
)

# ── Time patterns (structural — spaCy sometimes misses bare times) ──
_TIME_RE = re.compile(
    r'^'
    r'(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)'  # 9:00, 9:00 PM, 15:00:00
    r'|(?:\d{1,2}\s*[AaPp][Mm])'                         # 9AM, 9 PM
    r'$'
)

# ── Noise words — UI/status labels + short time/day words spaCy misses ──
# spaCy is the primary NER classifier, but single short words like "now",
# "Wed", "message" aren't reliably tagged by the model. These serve as
# a safety net for `is_noise()`.
_NOISE_WORDS = frozenset({
    # Status / state words
    'online', 'offline', 'away', 'busy', 'idle', 'active', 'inactive',
    'available', 'unavailable', 'typing', 'typing...', 'seen', 'unseen',
    'read', 'unread', 'delivered', 'sent', 'pending', 'failed',
    'connected', 'disconnected', 'loading', 'loading...', 'error',
    # UI labels
    'unknown', 'n/a', 'none', 'null', 'undefined', 'anonymous',
    'deleted', 'removed', 'blocked', 'archived', 'muted', 'pinned',
    'group', 'channel', 'broadcast', 'community', 'admin', 'moderator',
    'system', 'notification', 'notifications', 'alert', 'alerts',
    'settings', 'preferences', 'profile', 'account', 'help', 'support',
    'home', 'search', 'menu', 'back', 'close', 'cancel', 'ok', 'yes',
    'no', 'true', 'false', 'on', 'off',
    # Generic nouns that aren't people
    'message', 'messages', 'chat', 'chats', 'call', 'calls',
    'photo', 'photos', 'video', 'videos', 'audio', 'voice',
    'file', 'files', 'document', 'documents', 'link', 'links',
    'image', 'images', 'sticker', 'gif', 'emoji', 'reaction',
    'story', 'stories', 'status', 'post', 'posts', 'comment',
    'comments', 'reply', 'replies', 'forward', 'forwarded',
    'attachment', 'media', 'download', 'upload',
    'am', 'pm',
    # Short time/day/month words that spaCy often misses as standalone
    'now', 'ago', 'recently', 'earlier', 'later', 'just now',
    'yesterday', 'today', 'tomorrow', 'tonight',
    'this morning', 'this evening', 'this afternoon', 'last night',
    'last week', 'this week', 'next week',
    'last month', 'this month', 'next month',
    'last year', 'this year', 'next year',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    'saturday', 'sunday',
    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
    'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct',
    'nov', 'dec',
    # WhatsApp-specific noise
    'you', 'me', 'this message was deleted', 'waiting for this message',
    'missed voice call', 'missed video call', 'end-to-end encrypted',
    'messages and calls are end-to-end encrypted',
    'tap for more info', 'click here', 'learn more',
    'default', 'general', 'main',
    # Social media UI labels
    'following', 'follower', 'followers', 'follow', 'unfollow',
    'like', 'likes', 'liked', 'unlike', 'share', 'shared', 'shares',
    'retweet', 'retweeted', 'repost', 'reposted', 'save', 'saved',
    'subscribe', 'subscribed', 'subscriber', 'subscribers',
    'view', 'views', 'viewed', 'watching', 'watched',
    'joined', 'invited', 'accepted', 'declined', 'requested',
    'mutual', 'suggested', 'recommended', 'trending', 'popular',
    'verified', 'sponsored', 'promoted', 'advertisement', 'ad',
    'edited', 'original', 'draft', 'published', 'unpublished',
    'public', 'private', 'hidden', 'visible', 'restricted',
    'last seen recently', 'last seen within a week',
    'last seen within a month', 'last seen a long time ago',
})

# ── Low alphabetic ratio threshold ──
_LOW_ALPHA_THRESHOLD = 0.3


def is_noise(value: str) -> bool:
    """Returns True if the value is NOT a plausible person name.

    Uses spaCy NER as the primary classifier, with structural regex
    fallbacks for patterns the model might miss (bare timestamps,
    pure digits, UI labels).
    """
    if not value:
        return True

    text = value.strip()

    # Too short — not a meaningful name
    if len(text) < 2:
        return True

    # Too long — likely a sentence or message, not a name
    if len(text) > 80:
        return True

    # Too many words — sentences, not names
    words = text.split()
    if len(words) > 5:
        return True

    text_lower = text.lower().strip()

    # Exact match against UI noise words (spaCy won't catch these)
    if text_lower in _NOISE_WORDS:
        return True

    # Pure digits / punctuation / symbols
    if _PURE_DIGITS_RE.match(text):
        return True

    # ISO/Unix timestamps
    if _TIMESTAMP_RE.match(text):
        return True

    # Bare time patterns: "9:14 pm", "15:00"
    if _TIME_RE.match(text):
        return True

    # Low alphabetic ratio
    alpha_count = sum(c.isalpha() for c in text)
    if alpha_count == 0:
        return True
    if len(text) >= 3 and (alpha_count / len(text)) < _LOW_ALPHA_THRESHOLD:
        return True

    # ── spaCy NER classification ──
    # If spaCy recognizes this as DATE, TIME, CARDINAL, ORDINAL, MONEY,
    # PERCENT, QUANTITY — it's not a person name.
    ner_label = _ner_label(text)
    if ner_label in ('DATE', 'TIME', 'CARDINAL', 'ORDINAL',
                     'MONEY', 'PERCENT', 'QUANTITY'):
        return True

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VALUE CLASSIFIER — NLP-first classification for all fields
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Character pattern for plausible person names (letters, hyphens, apostrophes, dots)
_PERSON_NAME_RE = re.compile(
    r'^[A-Za-zÀ-ÖØ-öø-ÿ\u0900-\u097F\u0980-\u09FF\u0C00-\u0C7F'
    r'\u0C80-\u0CFF\u0D00-\u0D7F\u4E00-\u9FFF\u3040-\u30FF'
    r'\'\-\.\s]+$'
)

# Common English words that survive noise + NER filters but aren't person names.
# spaCy doesn't tag these as entities, and they're not in _NOISE_WORDS because
# they're not UI/status/messaging terms. This is the safety net for
# content-based classification when field names are generic.
_COMMON_NON_NAMES = frozenset({
    'red', 'blue', 'green', 'yellow', 'orange', 'purple', 'pink',
    'black', 'white', 'brown', 'gray', 'grey', 'gold', 'silver',
    'small', 'medium', 'large', 'extra', 'tiny', 'huge', 'big',
    'new', 'old', 'open', 'free', 'full', 'empty', 'real', 'fake',
    'good', 'bad', 'best', 'worst', 'top', 'bottom', 'left', 'right',
    'high', 'low', 'fast', 'slow', 'hot', 'cold', 'warm', 'cool',
    'first', 'last', 'next', 'prev', 'previous', 'other', 'more',
    'less', 'all', 'any', 'some', 'each', 'every', 'both', 'same',
    'different', 'special', 'normal', 'regular', 'standard', 'custom',
    'male', 'female', 'unspecified',
    'english', 'hindi', 'tamil', 'french', 'spanish', 'german',
    'important', 'urgent', 'critical', 'info', 'warning', 'danger',
})


def looks_like_person_name(value: str) -> bool:
    """Positive classifier: does this value look like a person name?

    Uses spaCy NER as the primary signal, with structural heuristics
    as fallback for short names the model might not recognize.

    Criteria:
      1. Not noise (timestamps, dates, status words, etc.)
      2. 2-60 chars, 1-3 words
      3. spaCy labels it PERSON → yes
      4. Fallback: predominantly alphabetic, matches name char pattern,
         has capitalization signal
    """
    if not value:
        return False

    text = value.strip()
    if len(text) < 2 or len(text) > 60:
        return False

    if is_noise(text):
        return False

    words = text.split()
    if len(words) > 3:
        return False

    # ── Primary: spaCy NER ──
    ner_label = _ner_label(text)
    if ner_label == 'PERSON':
        return True

    # If spaCy says it's something else (ORG, GPE, etc.), trust it ONLY
    # if the structural heuristics also don't support it being a name.
    # spaCy often misclassifies South Asian names or name+abbreviation
    # combos (e.g., "Shanmuganadhan EEE" → ORG, "Priya Singh" → GPE).
    # So we note the NER opinion but fall through to structural checks.
    spacy_says_not_person = ner_label in (
        'ORG', 'GPE', 'LOC', 'FAC', 'PRODUCT', 'EVENT',
        'WORK_OF_ART', 'LAW', 'LANGUAGE', 'NORP'
    )

    # ── Fallback: structural heuristics for short names spaCy misses ──
    alpha_count = sum(c.isalpha() for c in text)
    if alpha_count == 0:
        return False
    if (alpha_count / len(text)) < 0.6:
        return False

    if not _PERSON_NAME_RE.match(text):
        return False

    # At least one word must have ≥ 2 alphabetic chars
    has_real_word = any(sum(c.isalpha() for c in w) >= 2 for w in words)
    if not has_real_word:
        return False

    # Single-word: require capitalization (spaCy didn't confirm it)
    if len(words) == 1 and text.islower():
        return False

    # Common English words that aren't names
    text_lower = text.lower().strip()
    if text_lower in _COMMON_NON_NAMES:
        return False

    # If spaCy labeled this as ORG/GPE/etc but structural heuristics
    # passed (multi-word, capitalized, name-pattern match) — we still
    # accept it. South Asian names are commonly misclassified by the
    # English model. Only reject single-word values that spaCy rejects.
    if spacy_says_not_person and len(words) == 1:
        return False

    return True


# ── Image/avatar URL detection ──
_IMAGE_EXT_RE = re.compile(
    r'\.(?:jpg|jpeg|png|gif|webp|svg|bmp|ico|avif|tiff)(?:\?|#|$)',
    re.IGNORECASE
)
_IMAGE_CDN_RE = re.compile(
    r'(?:'
    r'pps\.whatsapp\.net'
    r'|web\.whatsapp\.com/pp'
    r'|instagram.*?/(?:t51|s\d+x\d+)'
    r'|(?:avatars|avatar)\d*\.githubusercontent'
    r'|(?:pbs|abs)\.twimg\.com'
    r'|cdn\.(?:discordapp|discord)\.com/avatars'
    r'|(?:graph\.facebook|scontent)'
    r'|t\.me/i/userpic'
    r'|(?:lh\d+\.googleusercontent)'
    r'|(?:media|images?)\.(?:licdn|linkedin)\.com'
    r'|gravatar\.com/avatar'
    r')',
    re.IGNORECASE
)


def _is_image_url(url: str) -> bool:
    """Check if a URL points to an image (avatar/profile pic).

    Uses two heuristics:
      1. File extension check (.jpg, .png, .webp, etc.)
      2. CDN pattern match (WhatsApp, GitHub, Instagram CDN paths)
    """
    if _IMAGE_EXT_RE.search(url):
        return True
    if _IMAGE_CDN_RE.search(url):
        return True
    return False


def classify_value(value: str) -> str:
    """Classify a string value by its content pattern.

    Returns one of: 'phone', 'email', 'avatar', 'url', 'name', 'noise'.

    This is the core of the content-first approach: instead of
    relying on what field name the value came from, we look at
    the value itself and determine what it is.
    """
    if not value:
        return 'noise'

    text = value.strip()
    if not text:
        return 'noise'

    # ── 1. Phone number ──
    if _PHONE_RE.match(text):
        return 'phone'

    # ── 2. Email ──
    if _EMAIL_RE.match(text):
        return 'email'

    # ── 3. Data URI images (base64-encoded avatars) ──
    if text.startswith('data:image/'):
        return 'avatar'

    # ── 4. Blob URLs (browser-local image references) ──
    if text.startswith('blob:'):
        return 'avatar'

    # ── 5. URL — sub-classify into avatar vs generic URL ──
    if text.startswith('http://') or text.startswith('https://'):
        if _is_image_url(text):
            return 'avatar'
        return 'url'

    # ── 6. Noise (time, date, status, label, etc.) ──
    if is_noise(text):
        return 'noise'

    # ── 7. Person name ──
    if looks_like_person_name(text):
        return 'name'

    # ── 8. Fallback — unknown content (message body, etc.) ──
    return 'noise'


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
            elif not is_noise(text):
                # Only add if it passes the noise filter
                signals.names.append(text)
        # Check for embedded profile URLs
        m = _URL_PROFILE_RE.search(text if isinstance(item, str) else '')
        if m:
            signals.usernames.append(m.group(1))
        return signals

    if not isinstance(item, dict):
        return signals

    # Structured dict — inspect each field.
    #
    # Strategy: Two-pass approach.
    #   Pass 1: Check if any field key matches a known semantic field set
    #           (_NAME_FIELDS, _PHONE_FIELDS, etc.). If so, use field-name-
    #           aware extraction (the key tells us what the value means).
    #   Pass 2: If NO field key matched any known set, fall back to pure
    #           content-based classification — look at each value and decide
    #           what it is by its content pattern (name? phone? timestamp?).
    #
    # This handles scrapers that produce generic keys like "text", "text_1",
    # "span", "div_0" where the key gives us zero semantic information.

    _ALL_KNOWN_FIELDS = (
        _NAME_FIELDS | _USERNAME_FIELDS | _AVATAR_FIELDS |
        _PHONE_FIELDS | _EMAIL_FIELDS
    )
    has_known_field = any(
        k.lower() in _ALL_KNOWN_FIELDS for k in item.keys()
    )

    for key, value in item.items():
        if not value or not isinstance(value, str):
            continue
        value = value.strip()
        if not value:
            continue

        key_lower = key.lower()

        if has_known_field:
            # ── Field-name-aware extraction (structured data) ──

            # Names
            if key_lower in _NAME_FIELDS:
                if (not _PHONE_RE.match(value) and not _EMAIL_RE.match(value)
                        and not is_noise(value)):
                    signals.names.append(value)

            # Usernames / handles
            if key_lower in _USERNAME_FIELDS:
                m = _URL_PROFILE_RE.search(value)
                if m:
                    signals.usernames.append(m.group(1))
                elif not value.startswith('http'):
                    signals.usernames.append(value)

            # Avatars — explicit field name match
            if key_lower in _AVATAR_FIELDS:
                if (value.startswith('http') or value.startswith('data:')
                        or value.startswith('blob:')):
                    signals.avatars.append(value)

            # Avatar detection by URL content — any field with an image URL
            # (catches fields like "img_src", "photo_url", "pic", etc.)
            elif (value.startswith('http') or value.startswith('data:image/')
                    or value.startswith('blob:')):
                if _is_image_url(value) or value.startswith('data:image/'):
                    signals.avatars.append(value)

            # Phone numbers
            if key_lower in _PHONE_FIELDS:
                if _PHONE_FIELD_RE.match(value):
                    signals.phones.append(value)
            elif _PHONE_RE.match(value):
                signals.phones.append(value)

            # Emails
            if key_lower in _EMAIL_FIELDS or _EMAIL_RE.match(value):
                if _EMAIL_RE.match(value):
                    signals.emails.append(value)

            # URL scanning
            if 'url' in key_lower or 'link' in key_lower or 'href' in key_lower:
                m = _URL_PROFILE_RE.search(value)
                if m:
                    signals.usernames.append(m.group(1))

        else:
            # ── Content-based classification (generic/unknown keys) ──
            # Handled below in the two-pass approach.
            pass

    if not has_known_field:
        # ── Two-pass content classification for generic-keyed dicts ──
        #
        # Pass 1: Classify all values. Some will be definite ('phone',
        #         'email', 'noise'), some may be 'ambiguous' (single
        #         lowercase word — could be a name or a generic word).
        #
        # Pass 2: Use item-level context to resolve ambiguity.
        #         If the item has a mix of name-like values and noise
        #         (timestamps, day names), it's likely a contact-list
        #         row, so promote ambiguous values to 'name'.

        classified = []   # (key, value, category)
        for key, value in item.items():
            if not value or not isinstance(value, str):
                continue
            v = value.strip()
            if not v:
                continue
            cat = classify_value(v)
            classified.append((key, v, cat))

        # Count categories for context awareness
        has_noise = any(c == 'noise' for _, _, c in classified)
        has_definite_name = any(c == 'name' for _, _, c in classified)
        has_phone = any(c == 'phone' for _, _, c in classified)
        has_email = any(c == 'email' for _, _, c in classified)

        # Identify "ambiguous" values — single-word, mostly-alpha strings
        # that weren't classified as 'name' due to lack of capitalization
        # but could be names in context (e.g. "varshith" next to "Tuesday")
        ambiguous = []
        for i, (key, v, cat) in enumerate(classified):
            if cat == 'noise' and _PERSON_NAME_RE.match(v) and len(v) >= 3:
                # Must be ≤ 3 words to be a plausible name
                if len(v.split()) > 3:
                    continue
                # It was classified noise, but it's all-alpha — maybe a name
                v_lower = v.lower().strip()
                if (v_lower not in _NOISE_WORDS
                        and v_lower not in _COMMON_NON_NAMES
                        and not _TIME_RE.match(v)
                        and not _TIMESTAMP_RE.match(v)):
                    # Ask spaCy — if it says DATE/TIME/CARDINAL, skip
                    ner_lbl = _ner_label(v)
                    if ner_lbl not in ('DATE', 'TIME', 'CARDINAL', 'ORDINAL',
                                       'MONEY', 'PERCENT', 'QUANTITY',
                                       'ORG', 'GPE', 'LOC', 'FAC',
                                       'PRODUCT', 'EVENT', 'LANGUAGE',
                                       'NORP'):
                        ambiguous.append(i)

        # Context promotion: if we have noise values (timestamps, days)
        # alongside ambiguous alpha-only values, the ambiguous ones are
        # likely names. This is the WhatsApp contact list pattern:
        #   {"text": "varshith", "text_1": "Tuesday"}
        if ambiguous and has_noise and not has_definite_name:
            for idx in ambiguous:
                k, v, _ = classified[idx]
                classified[idx] = (k, v, 'name')

        # Apply classifications
        for key, v, cat in classified:
            if cat == 'name':
                signals.names.append(v)
            elif cat == 'phone':
                signals.phones.append(v)
            elif cat == 'email':
                signals.emails.append(v)
            elif cat == 'avatar':
                signals.avatars.append(v)
            elif cat == 'url':
                m = _URL_PROFILE_RE.search(v)
                if m:
                    signals.usernames.append(m.group(1))
            # 'noise' → skip

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

def choose_canonical_name(aliases: list[str],
                         alias_freq: dict[str, int] | None = None) -> str:
    """Pick the best canonical display name from a list of aliases.

    Considers observation frequency — a name seen 100 times should
    beat one seen once. This enables dynamic evolution as data grows.

    Heuristics:
      1. Frequency bonus (higher observation count → more likely the real name)
      2. Prefer properly capitalized names (Title Case)
      3. Prefer names with spaces (multi-word = full name)
      4. Prefer longer names (more complete)
      5. Avoid usernames / handles (no digits, no @)
      6. Penalize noise values (dates, times, labels)
      7. spaCy PERSON label → bonus
    """
    if not aliases:
        return 'Unknown'

    if alias_freq is None:
        alias_freq = {}

    # Filter out noise values before scoring
    clean = [a for a in aliases if not is_noise(a)]
    if not clean:
        return aliases[0] if aliases else 'Unknown'
    if len(clean) == 1:
        return clean[0]

    # Max frequency for normalization
    max_freq = max((alias_freq.get(a, 1) for a in clean), default=1)

    scored = []
    for name in clean:
        s = 0.0
        freq = alias_freq.get(name, 1)

        # ── Frequency bonus (logarithmic, up to +25) ──
        # A name seen 100x vs 1x gets a massive boost
        if max_freq > 1:
            s += (math.log(freq + 1) / math.log(max_freq + 1)) * 25.0

        # ── spaCy PERSON label bonus ──
        if _ner_is_person(name):
            s += 15.0

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

    Features:
      - Frequency tracking: observation counts per alias grow over time
      - Confidence evolution: entity confidence increases with evidence
      - Dynamic canonical name: re-elected as frequency data changes
      - Graph deduplication: shared word/token nodes via SurrealDB RELATE
      - Periodic re-evaluation: re-scores entities as data accumulates

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

        Items with strong identity signals are resolved immediately.
        Items with weak signals (e.g. only a single name, no corroborating
        data) go to a buffer. After the main resolve pass, the buffer is
        re-checked against the now-larger entity set.

        Returns stats: { created, merged, skipped, buffered, entities }
        """
        stats = {'created': 0, 'merged': 0, 'skipped': 0,
                 'buffered': 0, 'promoted': 0, 'entities': []}

        # 1. Extract signals from each item, classify strength
        strong_signals = []
        weak_signals = []
        for i, item in enumerate(values):
            sig = extract_signals(item, organ_id, class_name)
            if sig.has_identity:
                if self._has_strong_identity(sig):
                    strong_signals.append((i, sig))
                else:
                    weak_signals.append((i, sig))
            else:
                stats['skipped'] += 1

        # 2. Load existing entities from memory
        existing_entities = await self.memory.list_entities()

        # 3. Compute IDF from existing entities for token weighting
        idf = compute_idf(existing_entities)

        # 4. Resolve strong signals first (they create the entity anchors)
        for item_idx, signals in strong_signals:
            await self._resolve_single(
                signals, organ_id, class_name, item_idx,
                existing_entities, idf, stats
            )

        # 5. Try weak signals against the now-richer entity set
        still_weak = []
        for item_idx, signals in weak_signals:
            best_match, best_entity = self._find_best_match(
                signals, existing_entities, idf
            )
            if best_match and best_entity:
                # Weak signal matched an existing entity — merge it
                await self._merge_into_entity(
                    best_entity['entity_id'], signals, organ_id,
                    class_name, item_idx
                )
                stats['merged'] += 1
                stats['entities'].append(best_entity['entity_id'])
                self._update_entity_in_list(
                    existing_entities, best_entity['entity_id'], signals
                )
            else:
                # Still can't correlate — buffer it
                still_weak.append((item_idx, signals))

        # 6. Buffer remaining weak signals for future correlation
        for item_idx, signals in still_weak:
            buffer_id = uuid.uuid4().hex[:16]
            sig_dict = {
                'names': signals.names,
                'usernames': signals.usernames,
                'phones': signals.phones,
                'emails': signals.emails,
                'avatars': signals.avatars,
                'raw': signals.raw,
            }
            await self.memory.buffer_entity_signal(
                buffer_id, sig_dict, organ_id, class_name, item_idx
            )
            stats['buffered'] += 1

        # 7. After creating new entities, sweep the buffer —
        #    previously buffered items may now match
        promoted = await self._sweep_buffer(existing_entities, idf)
        stats['promoted'] += promoted

        # 8. Deduplicate word tokens into shared graph nodes
        await self._deduplicate_tokens(existing_entities)

        return stats

    def _has_strong_identity(self, signals: IdentitySignals) -> bool:
        """Check if signals have strong enough identity to create an entity.

        Strong = at least one name AND at least one corroborating signal
        (phone, email, username, avatar), OR a deterministic fingerprint
        (phone/email alone is enough).
        """
        # Deterministic fingerprints are always strong
        if signals.phones or signals.emails:
            return True

        # Name + corroborating signal
        if signals.names:
            if signals.usernames or signals.avatars:
                return True
            # Multiple distinct names from the same item = strong
            if len(signals.names) >= 2:
                return True

        # Username alone is strong enough (it's a unique identifier)
        if signals.usernames:
            return True

        return False

    def _find_best_match(self, signals: IdentitySignals,
                         existing_entities: list, idf: dict):
        """Find the best matching entity for a signal set."""
        best_match = None
        best_entity = None
        for entity in existing_entities:
            result = compute_consensus(signals, entity, idf)
            if result.should_merge:
                if (best_match is None or
                        result.consensus_score > best_match.consensus_score):
                    best_match = result
                    best_entity = entity
        return best_match, best_entity

    async def _resolve_single(self, signals: IdentitySignals,
                               organ_id: str, class_name: str,
                               item_idx: int, existing_entities: list,
                               idf: dict, stats: dict):
        """Resolve a single signal set — merge or create."""
        best_match, best_entity = self._find_best_match(
            signals, existing_entities, idf
        )

        if best_match and best_entity:
            await self._merge_into_entity(
                best_entity['entity_id'], signals, organ_id,
                class_name, item_idx
            )
            stats['merged'] += 1
            stats['entities'].append(best_entity['entity_id'])
            self._update_entity_in_list(
                existing_entities, best_entity['entity_id'], signals
            )
            if stats['merged'] % 50 == 0:
                idf.update(compute_idf(existing_entities))
        else:
            entity_id = await self._create_entity(
                signals, organ_id, class_name, item_idx
            )
            stats['created'] += 1
            stats['entities'].append(entity_id)
            new_entity = self._build_entity_dict(entity_id, signals,
                                                  organ_id, class_name,
                                                  item_idx)
            existing_entities.append(new_entity)
            idf.update(compute_idf(existing_entities))

    async def _sweep_buffer(self, existing_entities: list,
                             idf: dict) -> int:
        """Re-check buffered items against the current entity set.

        Returns the number of items promoted from buffer to entities.
        """
        buffered = await self.memory.list_buffered_signals()
        if not buffered:
            return 0

        promoted = 0
        for item in buffered:
            sig_dict = item.get('signals', {})
            signals = IdentitySignals(
                names=sig_dict.get('names', []),
                usernames=sig_dict.get('usernames', []),
                phones=sig_dict.get('phones', []),
                emails=sig_dict.get('emails', []),
                avatars=sig_dict.get('avatars', []),
                raw=sig_dict.get('raw', {}),
                source_organ=item.get('organ_id', ''),
                source_class=item.get('class_name', ''),
            )

            best_match, best_entity = self._find_best_match(
                signals, existing_entities, idf
            )

            if best_match and best_entity:
                # Promote: merge into entity and remove from buffer
                await self._merge_into_entity(
                    best_entity['entity_id'], signals,
                    item.get('organ_id', ''),
                    item.get('class_name', ''),
                    item.get('item_index', 0),
                )
                self._update_entity_in_list(
                    existing_entities, best_entity['entity_id'], signals
                )
                await self.memory.remove_buffered_signal(item['buffer_id'])
                promoted += 1

        return promoted

    async def resolve_all_sources(self) -> dict:
        """Re-resolve ALL scraped data across ALL organs.
        Useful for rebuilding the entity graph from scratch."""
        # Clear existing entities and graph edges
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

    # ── Re-evaluation: dynamic confidence as data accumulates ──

    async def re_evaluate_entities(self) -> dict:
        """Re-evaluate ALL entities based on accumulated evidence.

        This is the key method for dynamic evolution. As new data pours
        in, entities that were created with low confidence should be
        re-scored. Entities with high observation counts become more
        confident. Entities that were wrongly split may get merged.

        Call this periodically (e.g., after every N scrapes) or on demand.

        Returns: { re_scored, merged_pairs, canonical_updates }
        """
        stats = {'re_scored': 0, 'merged_pairs': 0,
                 'canonical_updates': 0}

        entities = await self.memory.list_entities()
        if not entities:
            return stats

        idf = compute_idf(entities)

        # 1. Re-score confidence for each entity based on evidence
        for ent in entities:
            old_confidence = ent.get('confidence', 0.0)
            new_confidence = self._compute_confidence(ent)
            if abs(new_confidence - old_confidence) > 0.01:
                await self.memory.update_entity_confidence(
                    ent['entity_id'], new_confidence
                )
                stats['re_scored'] += 1

            # Re-elect canonical name with frequency data
            alias_freq = ent.get('alias_freq', {})
            aliases = ent.get('aliases', [])
            usernames = ent.get('usernames', [])
            all_names = aliases + usernames
            old_canonical = ent.get('canonical_name', '')
            new_canonical = choose_canonical_name(all_names, alias_freq)
            if new_canonical != old_canonical:
                await self.memory.update_entity_canonical(
                    ent['entity_id'], new_canonical
                )
                stats['canonical_updates'] += 1

        # 2. Check for entity pairs that should be merged
        #    (may have been created separately but now have enough
        #    overlapping evidence)
        merged_ids = set()
        for i, ent_a in enumerate(entities):
            if ent_a['entity_id'] in merged_ids:
                continue
            for j in range(i + 1, len(entities)):
                ent_b = entities[j]
                if ent_b['entity_id'] in merged_ids:
                    continue

                # Build signals from ent_b and test against ent_a
                sig_b = IdentitySignals(
                    names=ent_b.get('aliases', []),
                    usernames=ent_b.get('usernames', []),
                    phones=ent_b.get('phones', []),
                    emails=ent_b.get('emails', []),
                    avatars=ent_b.get('avatars', []),
                )
                result = compute_consensus(sig_b, ent_a, idf)
                if result.should_merge and result.consensus_score >= 0.7:
                    # Merge ent_b into ent_a
                    await self._merge_entities(
                        ent_a['entity_id'], ent_b['entity_id']
                    )
                    merged_ids.add(ent_b['entity_id'])
                    stats['merged_pairs'] += 1

        return stats

    def _compute_confidence(self, entity: dict) -> float:
        """Compute entity confidence based on accumulated evidence.

        Factors:
          - observation_count: more observations → higher confidence
          - signal diversity: phone + email + name > just name
          - alias consistency: many aliases for same name → higher
          - source diversity: seen across multiple organs → higher
        """
        obs_count = entity.get('observation_count', 1)
        aliases = entity.get('aliases', [])
        phones = entity.get('phones', [])
        emails = entity.get('emails', [])
        usernames = entity.get('usernames', [])
        avatars = entity.get('avatars', [])
        sources = entity.get('sources', [])

        confidence = 0.0

        # Observation frequency (logarithmic, caps at ~0.4)
        confidence += min(0.4, math.log(obs_count + 1) / 10.0)

        # Signal diversity (each signal type adds confidence)
        signal_types = sum([
            bool(aliases),
            bool(phones),
            bool(emails),
            bool(usernames),
            bool(avatars),
        ])
        confidence += signal_types * 0.1  # up to 0.5

        # Source diversity (seen from multiple organs)
        unique_organs = len(set(
            s.get('organ_id', '') for s in sources if isinstance(s, dict)
        ))
        if unique_organs >= 2:
            confidence += 0.1

        # spaCy validation: if canonical name is recognized as PERSON
        canonical = entity.get('canonical_name', '')
        if canonical and _ner_is_person(canonical):
            confidence += 0.05

        return min(1.0, confidence)

    async def _merge_entities(self, keep_id: str, absorb_id: str):
        """Merge two entity nodes: absorb one into the other.

        The absorbed entity is deleted; all its data merges into the keeper.
        """
        absorbed = await self.memory.get_entity(absorb_id)
        if not absorbed:
            return

        # Build signals from the absorbed entity
        signals = IdentitySignals(
            names=absorbed.get('aliases', []),
            usernames=absorbed.get('usernames', []),
            phones=absorbed.get('phones', []),
            emails=absorbed.get('emails', []),
            avatars=absorbed.get('avatars', []),
        )

        # Merge all sources
        for source in absorbed.get('sources', []):
            await self._merge_into_entity(
                keep_id, signals,
                source.get('organ_id', ''),
                source.get('class_name', ''),
                source.get('item_index', 0),
            )

        # Merge alias frequencies
        absorbed_freq = absorbed.get('alias_freq', {})
        if absorbed_freq:
            await self.memory.merge_alias_frequencies(keep_id, absorbed_freq)

        # Transfer observation count
        absorbed_obs = absorbed.get('observation_count', 1)
        await self.memory.increment_observation_count(keep_id, absorbed_obs)

        # Create a graph edge recording the merge (for audit trail)
        await self.memory.create_entity_link(keep_id, absorb_id, 'merged')

        # Delete the absorbed entity
        await self.memory.delete_entity(absorb_id)

    # ── Graph deduplication: shared word nodes ──

    async def _deduplicate_tokens(self, entities: list[dict]):
        """Create shared word nodes in the graph and link entities to them.

        Instead of every entity storing its own copy of common tokens
        like "hi", "hello", "the", we create a single `word` node and
        RELATE entities to it. This is what a graph DB is for.
        """
        # Collect all tokens across all entities with their frequencies
        token_entity_map: dict[str, list[str]] = {}
        for ent in entities:
            eid = ent.get('entity_id', '')
            for token in ent.get('name_tokens', []):
                token_entity_map.setdefault(token, []).append(eid)

        # Only create shared nodes for tokens that appear in 2+ entities
        # (deduplication only matters when there's actual duplication)
        for token, entity_ids in token_entity_map.items():
            if len(entity_ids) >= 2:
                await self.memory.ensure_word_node(token, len(entity_ids))
                for eid in set(entity_ids):
                    await self.memory.relate_entity_to_word(eid, token)

    def _build_entity_dict(self, entity_id: str, signals: IdentitySignals,
                           organ_id: str, class_name: str,
                           item_idx: int) -> dict:
        """Build a dict representation of a new entity (for in-memory list)."""
        aliases = list(signals.names)
        all_names = aliases + list(signals.usernames)

        # Initialize alias frequency map
        alias_freq: dict[str, int] = {}
        for a in aliases:
            alias_freq[a] = alias_freq.get(a, 0) + 1

        canonical = choose_canonical_name(all_names, alias_freq) if all_names else 'Unknown'

        tokens = list(signals.name_tokens)
        # Also add username tokens
        for u in signals.usernames:
            tokens.extend(tokenize_name(u))
        tokens = list(set(tokens))

        return {
            'entity_id': entity_id,
            'canonical_name': canonical,
            'aliases': aliases,
            'alias_freq': alias_freq,
            'usernames': list(signals.usernames),
            'phones': list(signals.phones),
            'emails': list(signals.emails),
            'avatars': list(signals.avatars),
            'name_tokens': tokens,
            'phonetic_keys': signals.phonetic_keys,
            'observation_count': 1,
            'confidence': 0.0,
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

        # Compute initial confidence
        entity['confidence'] = self._compute_confidence(entity)

        await self.memory.create_entity(entity)
        return entity_id

    async def _merge_into_entity(self, entity_id: str,
                                 signals: IdentitySignals,
                                 organ_id: str, class_name: str,
                                 item_idx: int):
        """Merge new signals into an existing entity node.
        Increments observation count and alias frequencies."""
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
        # Increment observation count
        await self.memory.increment_observation_count(entity_id, 1)
        # Update alias frequencies
        alias_freq_delta = {}
        for name in signals.names:
            alias_freq_delta[name] = alias_freq_delta.get(name, 0) + 1
        if alias_freq_delta:
            await self.memory.merge_alias_frequencies(entity_id, alias_freq_delta)

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

                # Update alias frequencies
                alias_freq = ent.get('alias_freq', {})
                for name in signals.names:
                    alias_freq[name] = alias_freq.get(name, 0) + 1
                ent['alias_freq'] = alias_freq

                # Increment observation count
                ent['observation_count'] = ent.get('observation_count', 1) + 1

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

                # Re-elect canonical name with frequency data
                all_names = ent['aliases'] + ent.get('usernames', [])
                ent['canonical_name'] = choose_canonical_name(
                    all_names, alias_freq
                )

                # Recompute confidence
                ent['confidence'] = self._compute_confidence(ent)

                break
