"""
Tests for the Entity Resolver — multi-strategy identity resolution.

Tests cover:
  - Signal extraction from various data formats
  - Individual matching strategies
  - Consensus engine
  - Cross-source entity merging
  - Phonetic algorithms
  - String similarity
  - Edge cases
"""

import pytest
from src.entity_resolver import (
    # Phonetic
    soundex, double_metaphone,
    # String similarity
    jaro_similarity, jaro_winkler,
    # Token utils
    tokenize_name, jaccard_similarity, weighted_token_overlap,
    # Username matching
    normalize_username, username_similarity,
    # Signal extraction
    extract_signals, IdentitySignals,
    # Strategies
    strategy_fingerprint, strategy_name_similarity,
    strategy_username_match, strategy_token_overlap,
    strategy_contextual,
    # Consensus
    compute_consensus, MERGE_THRESHOLD,
    # IDF
    compute_idf,
    # Canonical name
    choose_canonical_name,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHONETIC ALGORITHMS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSoundex:
    def test_basic(self):
        assert soundex("Robert") == "R163"
        assert soundex("Rupert") == "R163"

    def test_same_family_names(self):
        # Mehta variants should share prefix
        s1 = soundex("Mehta")
        s2 = soundex("Meta")
        assert s1[0] == s2[0]  # Same first letter

    def test_empty(self):
        assert soundex("") == "0000"

    def test_single_char(self):
        assert len(soundex("A")) == 4

    def test_rishi_variants(self):
        s1 = soundex("Rishi")
        s2 = soundex("Rishi")
        assert s1 == s2

    def test_different_names(self):
        s1 = soundex("John")
        s2 = soundex("Mary")
        assert s1 != s2


class TestDoubleMetaphone:
    def test_basic(self):
        p, a = double_metaphone("Smith")
        assert p  # Should produce a code

    def test_phone_vs_fone(self):
        p1, _ = double_metaphone("Phone")
        p2, _ = double_metaphone("Fone")
        # Both should start with F
        assert p1[0] == 'F' or p2[0] == 'F'

    def test_empty(self):
        assert double_metaphone("") == ('', '')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STRING SIMILARITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestJaroWinkler:
    def test_identical(self):
        assert jaro_winkler("rishi", "rishi") == 1.0

    def test_empty(self):
        assert jaro_winkler("", "") == 1.0
        assert jaro_winkler("abc", "") == 0.0

    def test_similar(self):
        score = jaro_winkler("rishi mehta", "rishi metha")
        assert score > 0.9

    def test_different(self):
        score = jaro_winkler("john", "mary")
        assert score < 0.6

    def test_prefix_boost(self):
        # Jaro-Winkler should boost for common prefix
        jw = jaro_winkler("rishim", "rishik")
        j = jaro_similarity("rishim", "rishik")
        assert jw >= j

    def test_case_sensitivity(self):
        # JW is case-sensitive; lowercasing should happen before calling
        score = jaro_winkler("rishi", "Rishi")
        assert score < 1.0  # Different case = different chars


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TOKEN UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTokenizeName:
    def test_spaces(self):
        tokens = tokenize_name("Rishi Mehta")
        assert "rishi" in tokens
        assert "mehta" in tokens

    def test_camel_case(self):
        tokens = tokenize_name("RishiMehta")
        assert "rishi" in tokens
        assert "mehta" in tokens

    def test_username_separators(self):
        tokens = tokenize_name("rishi_mehta-04")
        assert "rishi" in tokens
        assert "mehta" in tokens
        assert "04" in tokens

    def test_digits(self):
        tokens = tokenize_name("rishi04mehta")
        assert "rishi" in tokens
        assert "mehta" in tokens
        assert "04" in tokens

    def test_single_char_filtered(self):
        tokens = tokenize_name("A B Rishi")
        assert "rishi" in tokens
        assert "a" not in tokens  # Too short

    def test_concatenated_substrings(self):
        """Concatenated lowercase names should produce substrings."""
        tokens = tokenize_name("rishimehta")
        assert "rishi" in tokens
        assert "mehta" in tokens


class TestJaccardSimilarity:
    def test_identical(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial(self):
        j = jaccard_similarity({"rishi", "mehta"}, {"rishi", "kumar"})
        assert 0.3 < j < 0.6  # 1 out of 3 unique

    def test_empty(self):
        assert jaccard_similarity(set(), set()) == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  USERNAME SIMILARITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestUsernameSimilarity:
    def test_exact(self):
        assert username_similarity("rishimehta", "rishimehta") == 1.0

    def test_case_insensitive(self):
        assert username_similarity("RishiMehta", "rishimehta") == 1.0

    def test_with_separators(self):
        score = username_similarity("rishi_mehta", "rishi-mehta")
        assert score >= 0.9

    def test_with_digits(self):
        score = username_similarity("rishimehta04", "rishimehta")
        assert score >= 0.9  # Core match after stripping digits

    def test_cross_platform(self):
        score = username_similarity("rishi.mehta", "rishi_mehta")
        assert score >= 0.9

    def test_different_people(self):
        score = username_similarity("johndoe", "janedoe")
        assert score < 0.7

    def test_empty(self):
        assert username_similarity("", "rishi") == 0.0

    def test_at_prefix(self):
        score = username_similarity("@rishimehta", "rishimehta")
        assert score == 1.0


class TestNormalizeUsername:
    def test_strips_at(self):
        assert normalize_username("@rishi") == "rishi"

    def test_strips_separators_and_digits(self):
        assert normalize_username("rishi_mehta-04") == "rishimehta"

    def test_lowercase(self):
        assert normalize_username("RishiMehta") == "rishimehta"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestExtractSignals:
    def test_whatsapp_dict(self):
        """Typical WhatsApp scrape: name + text fields."""
        item = {
            "name": "Rishi Mehta",
            "text": "hello there",
            "image": "https://pps.whatsapp.net/v/t61/rishi.jpg",
        }
        sig = extract_signals(item, "whatsapp", "contact")
        assert "Rishi Mehta" in sig.names
        assert sig.avatars == ["https://pps.whatsapp.net/v/t61/rishi.jpg"]
        assert sig.has_identity

    def test_github_dict(self):
        """Typical GitHub scrape: user + repo + link."""
        item = {
            "user": "rishimehta04",
            "title": "awesome-project",
            "link": "https://github.com/rishimehta04",
        }
        sig = extract_signals(item, "github", "feed_card")
        assert "rishimehta04" in sig.usernames or "rishimehta04" in sig.names
        assert sig.has_identity

    def test_flat_string_name(self):
        sig = extract_signals("Rishi Mehta", "whatsapp", "contact")
        assert sig.names == ["Rishi Mehta"]

    def test_flat_string_phone(self):
        sig = extract_signals("+91 98765 43210", "whatsapp", "contact")
        assert "+91 98765 43210" in sig.phones

    def test_flat_string_email(self):
        sig = extract_signals("rishi@example.com", "email", "inbox")
        assert "rishi@example.com" in sig.emails

    def test_url_username_extraction(self):
        item = {"url": "https://github.com/rishimehta04/project"}
        sig = extract_signals(item, "github", "repos")
        assert "rishimehta04" in sig.usernames

    def test_no_identity(self):
        item = {"color": "red", "size": "large"}
        sig = extract_signals(item, "shop", "product")
        assert not sig.has_identity

    def test_primary_name_prefers_longest(self):
        sig = IdentitySignals(names=["Rishi", "Rishi Mehta"])
        assert sig.primary_name == "Rishi Mehta"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MATCHING STRATEGIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_node(**kwargs):
    """Helper: build a minimal entity node dict."""
    defaults = {
        "entity_id": "test-001",
        "canonical_name": "Unknown",
        "aliases": [],
        "usernames": [],
        "phones": [],
        "emails": [],
        "avatars": [],
        "name_tokens": [],
        "phonetic_keys": [],
        "sources": [],
    }
    defaults.update(kwargs)
    return defaults


class TestStrategyFingerprint:
    def test_phone_match(self):
        sig = IdentitySignals(phones=["+91-9876543210"])
        node = _make_node(phones=["+91 9876543210"])
        vote = strategy_fingerprint(sig, node)
        assert vote.confidence == 1.0

    def test_email_match(self):
        sig = IdentitySignals(emails=["rishi@example.com"])
        node = _make_node(emails=["Rishi@Example.com"])
        vote = strategy_fingerprint(sig, node)
        assert vote.confidence == 1.0

    def test_no_match(self):
        sig = IdentitySignals(phones=["+1234567890"])
        node = _make_node(phones=["+0987654321"])
        vote = strategy_fingerprint(sig, node)
        assert vote.confidence == 0.0


class TestStrategyNameSimilarity:
    def test_exact_match(self):
        sig = IdentitySignals(names=["Rishi Mehta"])
        node = _make_node(aliases=["Rishi Mehta"])
        vote = strategy_name_similarity(sig, node)
        assert vote.confidence == 1.0

    def test_case_insensitive(self):
        sig = IdentitySignals(names=["rishi mehta"])
        node = _make_node(aliases=["Rishi Mehta"])
        vote = strategy_name_similarity(sig, node)
        assert vote.confidence == 1.0

    def test_typo(self):
        sig = IdentitySignals(names=["Rishi Metha"])
        node = _make_node(aliases=["Rishi Mehta"])
        vote = strategy_name_similarity(sig, node)
        assert vote.confidence > 0.8  # Should still match

    def test_different_names(self):
        sig = IdentitySignals(names=["John Smith"])
        node = _make_node(aliases=["Rishi Mehta"])
        vote = strategy_name_similarity(sig, node)
        assert vote.confidence < 0.5

    def test_no_names(self):
        sig = IdentitySignals()
        node = _make_node(aliases=["Rishi Mehta"])
        vote = strategy_name_similarity(sig, node)
        assert vote.confidence == 0.0


class TestStrategyUsernameMatch:
    def test_cross_platform(self):
        sig = IdentitySignals(usernames=["rishimehta04"])
        node = _make_node(usernames=["rishi_mehta"])
        vote = strategy_username_match(sig, node)
        assert vote.confidence > 0.6

    def test_exact(self):
        sig = IdentitySignals(usernames=["rishimehta"])
        node = _make_node(usernames=["rishimehta"])
        vote = strategy_username_match(sig, node)
        assert vote.confidence >= 0.9

    def test_no_match(self):
        sig = IdentitySignals(usernames=["johndoe123"])
        node = _make_node(usernames=["janedoe456"])
        vote = strategy_username_match(sig, node)
        assert vote.confidence < 0.5


class TestStrategyTokenOverlap:
    def test_full_overlap(self):
        sig = IdentitySignals(names=["Rishi Mehta"])
        node = _make_node(name_tokens=["rishi", "mehta"])
        vote = strategy_token_overlap(sig, node)
        assert vote.confidence >= 0.6

    def test_partial_overlap(self):
        sig = IdentitySignals(names=["Rishi Kumar"])
        node = _make_node(name_tokens=["rishi", "mehta"])
        vote = strategy_token_overlap(sig, node)
        # "rishi" overlaps, but "kumar" vs "mehta" don't
        assert vote.confidence > 0.0

    def test_username_tokens(self):
        """Username tokens should also participate."""
        sig = IdentitySignals(usernames=["rishimehta04"])
        node = _make_node(name_tokens=["rishi", "mehta"])
        vote = strategy_token_overlap(sig, node)
        assert vote.confidence > 0.5


class TestStrategyContextual:
    def test_avatar_match(self):
        sig = IdentitySignals(avatars=["https://example.com/avatar.jpg"])
        node = _make_node(avatars=["https://example.com/avatar.jpg"])
        vote = strategy_contextual(sig, node)
        assert vote.confidence > 0.8

    def test_no_contextual(self):
        sig = IdentitySignals()
        node = _make_node()
        vote = strategy_contextual(sig, node)
        assert vote.confidence == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONSENSUS ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestConsensus:
    def test_strong_merge_same_name(self):
        """Same full name → should merge."""
        sig = IdentitySignals(names=["Rishi Mehta"])
        node = _make_node(
            aliases=["Rishi Mehta"],
            name_tokens=["rishi", "mehta"],
        )
        result = compute_consensus(sig, node)
        assert result.should_merge
        assert result.consensus_score > MERGE_THRESHOLD

    def test_strong_merge_phone(self):
        """Same phone → deterministic merge."""
        sig = IdentitySignals(phones=["+919876543210"])
        node = _make_node(phones=["+91 9876 543210"])
        result = compute_consensus(sig, node)
        assert result.should_merge
        assert result.consensus_score == 1.0

    def test_cross_source_merge(self):
        """WhatsApp name + GitHub username → should merge via token overlap."""
        sig = IdentitySignals(
            names=["Rishi Mehta"],
            usernames=["rishimehta04"],
        )
        node = _make_node(
            aliases=["Rishi Mehta"],
            usernames=["rishi-mehta"],
            name_tokens=["rishi", "mehta"],
        )
        result = compute_consensus(sig, node)
        assert result.should_merge

    def test_no_merge_different_people(self):
        """Completely different people → should not merge."""
        sig = IdentitySignals(names=["John Smith"])
        node = _make_node(
            aliases=["Rishi Mehta"],
            name_tokens=["rishi", "mehta"],
        )
        result = compute_consensus(sig, node)
        assert not result.should_merge

    def test_weak_signals_no_merge(self):
        """Minimal shared data → should not merge."""
        sig = IdentitySignals(names=["A"])
        node = _make_node(aliases=["B"], name_tokens=["b"])
        result = compute_consensus(sig, node)
        assert not result.should_merge


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  IDF COMPUTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestIDF:
    def test_rare_tokens_higher_idf(self):
        entities = [
            {"name_tokens": ["rishi", "mehta"]},
            {"name_tokens": ["rishi", "kumar"]},
            {"name_tokens": ["john", "smith"]},
        ]
        idf = compute_idf(entities)
        # "rishi" appears in 2 docs, "john" in 1 → john should have higher IDF
        assert idf["john"] > idf["rishi"]

    def test_empty(self):
        assert compute_idf([]) == {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CANONICAL NAME SELECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCanonicalName:
    def test_prefers_full_name(self):
        result = choose_canonical_name(["rishimehta04", "Rishi Mehta"])
        assert result == "Rishi Mehta"

    def test_prefers_title_case(self):
        result = choose_canonical_name(["rishi mehta", "Rishi Mehta"])
        assert result == "Rishi Mehta"

    def test_avoids_handles(self):
        result = choose_canonical_name(["@rishi04", "Rishi Mehta"])
        assert result == "Rishi Mehta"

    def test_single_alias(self):
        result = choose_canonical_name(["rishimehta"])
        assert result == "rishimehta"

    def test_empty(self):
        result = choose_canonical_name([])
        assert result == "Unknown"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  END-TO-END SCENARIOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestE2EScenarios:
    def test_whatsapp_messages_same_person(self):
        """Multiple WhatsApp items with same name → should all resolve
        to the same entity."""
        items = [
            {"name": "Rishi Mehta", "text": "hello"},
            {"name": "Rishi Mehta", "text": "how are you"},
            {"name": "Rishi Mehta", "image": "https://wa.me/photo.jpg"},
        ]
        # Extract signals
        signals = [extract_signals(item, "whatsapp", "chat") for item in items]
        # All should have the same name
        assert all("Rishi Mehta" in s.names for s in signals)

        # Create node from first, check others match
        node = _make_node(
            aliases=["Rishi Mehta"],
            name_tokens=["rishi", "mehta"],
        )
        for sig in signals[1:]:
            result = compute_consensus(sig, node)
            assert result.should_merge, f"Failed to merge: {result.explanation}"

    def test_github_username_to_whatsapp_name(self):
        """GitHub handle 'rishimehta04' should match WhatsApp 'Rishi Mehta'."""
        github_item = {
            "user": "rishimehta04",
            "link": "https://github.com/rishimehta04",
        }
        github_sig = extract_signals(github_item, "github", "feed")

        wa_node = _make_node(
            aliases=["Rishi Mehta"],
            usernames=[],
            name_tokens=["rishi", "mehta"],
        )

        result = compute_consensus(github_sig, wa_node)
        # The token overlap of "rishi" + "mehta" from username tokenization
        # should produce a match
        assert result.consensus_score > 0.3

    def test_same_avatar_across_sources(self):
        """Same avatar URL from different sources → strong merge."""
        avatar = "https://cdn.example.com/avatars/rishi123.jpg"
        sig = IdentitySignals(
            names=["R Mehta"],
            avatars=[avatar],
        )
        node = _make_node(
            aliases=["Rishi"],
            avatars=[avatar],
            name_tokens=["rishi"],
        )
        result = compute_consensus(sig, node)
        assert result.should_merge

    def test_phone_deterministic_merge(self):
        """Phone match should force merge regardless of name mismatch."""
        sig = IdentitySignals(
            names=["RM"],  # Very abbreviated
            phones=["+919876543210"],
        )
        node = _make_node(
            aliases=["Rishi Mehta"],
            phones=["+91-9876-543210"],
            name_tokens=["rishi", "mehta"],
        )
        result = compute_consensus(sig, node)
        assert result.should_merge
        assert result.consensus_score == 1.0
