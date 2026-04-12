from __future__ import annotations

import unicodedata
from typing import Any

MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "�",
    "锟",
    "锛",
    "浣",
    "鏄",
    "鐨",
    "鍙",
    "鎴",
    "涓",
    "闂",
    "鎵",
)


def text_corruption_score(text: str) -> int:
    if not text:
        return 0
    score = 0
    score += text.count("�") * 20
    for marker in MOJIBAKE_MARKERS:
        score += text.count(marker)
    for ch in text:
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
            score += 5
    return score


def repair_common_mojibake(text: str) -> str:
    if not text:
        return text
    marker_hits = sum(text.count(m) for m in MOJIBAKE_MARKERS)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    has_katakana = any("\u30a0" <= ch <= "\u30ff" for ch in text)
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in text)
    has_euro = "€" in text
    if marker_hits < 2 and "�" not in text and not (has_cjk and (has_katakana or has_hangul or has_euro)):
        return text

    best = text
    best_score = text_corruption_score(text)
    original_digits = sum(ch.isdigit() for ch in text)
    for enc in ("gb18030", "cp1252", "latin-1"):
        for mode in ("strict", "ignore"):
            try:
                candidate = text.encode(enc, errors=mode).decode("utf-8", errors=mode)
            except Exception:
                continue
            if not candidate.strip():
                continue
            score = text_corruption_score(candidate)
            digit_drift = max(0, sum(ch.isdigit() for ch in candidate) - original_digits)
            score += digit_drift * 2
            if score < best_score:
                best = candidate
                best_score = score
    return best


def normalize_message_text(content: Any) -> str:
    text = str(content or "")
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return repair_common_mojibake(text)
