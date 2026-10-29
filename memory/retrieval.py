"""Deterministic lexical matching and rank fusion shared by memory backends."""
from __future__ import annotations

import re
from typing import Any


def tokenize_text(text: str) -> list[str]:
    tokens: list[str] = []
    for chunk in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", str(text or "").lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", chunk):
            if len(chunk) > 1:
                tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
            else:
                tokens.append(chunk)
        else:
            tokens.append(chunk)
    return list(dict.fromkeys(tokens))


def lexical_score(query: str, content: str) -> float:
    terms = tokenize_text(query)
    haystack = str(content or "").lower()
    return sum(term in haystack for term in terms) / max(1, len(terms))


def fuse_candidates(*rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RRF combines independent rankings without comparing incompatible scores."""
    rows: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    channels: dict[str, list[str]] = {}
    active = [ranking for ranking in rankings if ranking]
    for ranking in active:
        seen: set[str] = set()
        for rank, item in enumerate(ranking, 1):
            key = str(item.get("memory_id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.setdefault(key, dict(item))
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
            channels.setdefault(key, []).extend(item.get("retrieval_channels") or ["lexical_graph"])
    for key, row in rows.items():
        row["retrieval_score"] = scores[key] * 61 / max(1, len(active))
        row["retrieval_channels"] = list(dict.fromkeys(channels[key]))
    return sorted(rows.values(), key=lambda row: (-row["retrieval_score"], str(row["memory_id"])))
