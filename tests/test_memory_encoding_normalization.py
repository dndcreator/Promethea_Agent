from __future__ import annotations

from memory.adapter import MemoryAdapter


def test_normalize_message_text_keeps_multilingual_text():
    src = "你好，世界 | Привет мир | Bonjour le monde | こんにちは世界"
    out = MemoryAdapter._normalize_message_text(src)
    assert out == src


def test_normalize_message_text_repairs_utf8_decoded_as_gbk():
    bad = "\u6d63\u72b2\u30bd\u951b\u5c7c\u7b18\u9423\u5c7b\u20ac"
    out = MemoryAdapter._normalize_message_text(bad)
    assert out == "你好，世界"


def test_normalize_message_text_repairs_latin_mojibake():
    bad = "Fran\u00c3\u00a7ais na\u00c3\u00afve d\u00c3\u00a9j\u00c3\u00a0 vu"
    out = MemoryAdapter._normalize_message_text(bad)
    assert out == "Français naïve déjà vu"


def test_normalize_message_text_normalizes_newlines_and_nfc():
    src = "Cafe\u0301\r\nLine2\rLine3\x00"
    out = MemoryAdapter._normalize_message_text(src)
    assert out == "Café\nLine2\nLine3"
