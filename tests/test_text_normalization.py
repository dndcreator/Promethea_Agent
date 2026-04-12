from memory.text_normalization import normalize_message_text


def test_normalize_message_text_basic_cleanup():
    out = normalize_message_text("a\r\nb\x00c")
    assert out == "a\nbc"


def test_normalize_message_text_mojibake_repair_safe():
    # Should never raise and should preserve non-empty text.
    out = normalize_message_text("Ã¤Â½Â Ã¥Â¥Â½")
    assert isinstance(out, str)
    assert out.strip() != ""
