"""Quick validation of the content-based classifier."""
from src.entity_resolver import extract_signals, classify_value, looks_like_person_name


def test_whatsapp_contacts():
    """The exact data from the WhatsApp scrape example.
    Names > 3 words are now filtered out (likely messages, not names)."""
    items_expected = [
        ({"text": "Leera IT", "text_1": "9:14 pm"},           ["Leera IT"]),
        ({"text": "Nehal varma cse iot", "text_1": "Yesterday"}, []),  # 4 words = filtered
        ({"text": "Vardhin", "text_1": "Yesterday"},            ["Vardhin"]),
        ({"text": "Rishi Mehta M block Complex", "text_1": "Yesterday"}, []),  # 5 words = filtered
        ({"text": "upendra kv", "text_1": "Wednesday"},         ["upendra kv"]),
        ({"text": "varshith", "text_1": "Tuesday"},             ["varshith"]),
        ({"text": "Shanmuganadhan EEE", "text_1": "Saturday"},  ["Shanmuganadhan EEE"]),
        ({"text": "navaneet Goldu", "text_1": "Saturday"},      ["navaneet Goldu"]),
    ]

    for item, expected in items_expected:
        sig = extract_signals(item, "whatsapp", "chat_list")
        assert sig.names == expected, f"Expected {expected}, got {sig.names} for {item}"


def test_non_contact_data():
    """Non-person data should NOT create entities."""
    items = [
        {"color": "red", "size": "large"},
        {"label": "Settings", "icon": "gear"},
        {"text": "12345", "text_1": "67890"},
    ]
    for item in items:
        sig = extract_signals(item, "test", "test")
        assert not sig.has_identity, f"Should NOT have identity for {item}, got names={sig.names}"


def test_structured_data_still_works():
    """Known field names should still work via field-name-aware path."""
    sig = extract_signals(
        {"name": "Alice Bob", "phone": "+1 555-1234", "email": "alice@example.com"},
        "test", "structured"
    )
    assert sig.names == ["Alice Bob"]
    assert sig.phones == ["+1 555-1234"]
    assert sig.emails == ["alice@example.com"]

    sig = extract_signals(
        {"username": "rishi_m", "display_name": "Rishi Mehta"},
        "test", "structured"
    )
    assert "Rishi Mehta" in sig.names
    assert "rishi_m" in sig.usernames


def test_classify_value_categories():
    """Verify classify_value returns correct categories."""
    assert classify_value("9:14 pm") == "noise"
    assert classify_value("Yesterday") == "noise"
    assert classify_value("Tuesday") == "noise"
    assert classify_value("Saturday") == "noise"
    assert classify_value("2 hours ago") == "noise"
    assert classify_value("+91 98765 43210") == "phone"
    assert classify_value("user@example.com") == "email"
    assert classify_value("https://github.com/rishi") == "url"
    assert classify_value("Rishi Mehta") == "name"
    assert classify_value("upendra kv") == "name"
    assert classify_value("Leera IT") == "name"
    assert classify_value("Shanmuganadhan EEE") == "name"
    assert classify_value("navaneet Goldu") == "name"
    # > 3 words = noise (message, not a name)
    assert classify_value("Rishi Mehta M block Complex") == "noise"
    assert classify_value("Nehal varma cse iot") == "noise"
    # Single lowercase — ambiguous, classified as noise by default
    # (promoted to name only in item context)
    assert classify_value("varshith") == "noise"
    assert classify_value("red") == "noise"
    assert classify_value("large") == "noise"
    # Avatar URLs
    assert classify_value("https://pps.whatsapp.net/v/t61.24/photo.jpg") == "avatar"
    assert classify_value("https://avatars.githubusercontent.com/u/12345") == "avatar"
    assert classify_value("https://example.com/photo.png") == "avatar"
    assert classify_value("data:image/png;base64,abc123") == "avatar"
    assert classify_value("blob:https://web.whatsapp.com/abc-def") == "avatar"
    # Generic URLs stay as 'url'
    assert classify_value("https://github.com/vardhin/lexicon") == "url"


def test_looks_like_person_name():
    """Verify positive name classification."""
    assert looks_like_person_name("Rishi Mehta") is True
    assert looks_like_person_name("Vardhin") is True
    assert looks_like_person_name("upendra kv") is True
    assert looks_like_person_name("navaneet Goldu") is True
    assert looks_like_person_name("Shanmuganadhan EEE") is True

    # > 3 words = not a name
    assert looks_like_person_name("Nehal varma cse iot") is False
    assert looks_like_person_name("Rishi Mehta M block Complex") is False

    # Not names
    assert looks_like_person_name("9:14 pm") is False
    assert looks_like_person_name("Yesterday") is False
    assert looks_like_person_name("red") is False
    assert looks_like_person_name("large") is False
    assert looks_like_person_name("") is False
    assert looks_like_person_name("12345") is False
    assert looks_like_person_name("online") is False


def test_context_promotion():
    """Single lowercase names should be promoted when alongside noise."""
    # "varshith" alone wouldn't be classified as a name,
    # but next to "Tuesday" (noise) it gets promoted
    sig = extract_signals({"text": "varshith", "text_1": "Tuesday"}, "wa", "chat")
    assert sig.names == ["varshith"]
    assert sig.has_identity

    # Two noise values — nothing to promote
    sig = extract_signals({"text": "online", "text_1": "active"}, "wa", "chat")
    assert not sig.has_identity


def test_mixed_generic_fields():
    """Various generic-field scenarios."""
    # Instagram-style
    sig = extract_signals({"span": "Priya Singh", "span_1": "Following"}, "ig", "profile")
    assert sig.names == ["Priya Singh"]

    # Telegram-style
    sig = extract_signals({"div": "Alex Kumar", "div_1": "last seen recently"}, "tg", "contact")
    assert sig.names == ["Alex Kumar"]


if __name__ == "__main__":
    test_whatsapp_contacts()
    print("PASS: test_whatsapp_contacts")

    test_non_contact_data()
    print("PASS: test_non_contact_data")

    test_structured_data_still_works()
    print("PASS: test_structured_data_still_works")

    test_classify_value_categories()
    print("PASS: test_classify_value_categories")

    test_looks_like_person_name()
    print("PASS: test_looks_like_person_name")

    test_context_promotion()
    print("PASS: test_context_promotion")

    test_mixed_generic_fields()
    print("PASS: test_mixed_generic_fields")

    print("\nAll content classifier tests passed")
