from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def normalize_content(text: str) -> str:
    content = (text or "").strip().lower()
    content = re.sub(r"\s+", " ", content)
    return content


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def extract_tokens(text: str) -> List[str]:
    cleaned = normalize_content(text)
    if not cleaned:
        return []
    chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", cleaned)
    tokens: List[str] = []
    for chunk in chunks:
        if re.match(r"^[a-z0-9_]+$", chunk):
            tokens.extend([p for p in chunk.split("_") if p])
        else:
            tokens.append(chunk)
    return tokens


def build_semantic_keys(content: str, llm_keys: Optional[List[str]] = None) -> List[str]:
    keys: set[str] = set()
    if llm_keys:
        for k in llm_keys:
            norm = normalize_content(str(k))
            if norm:
                keys.add(norm)

    tokens = extract_tokens(content)
    for token in tokens:
        if len(token) >= 2:
            keys.add(token)

    return sorted(keys)


def normalize_candidates(candidates: Any) -> List[Dict[str, Any]]:
    allowed_types = {
        "goal",
        "preference",
        "constraint",
        "identity",
        "project_state",
    }
    result: List[Dict[str, Any]] = []
    if not isinstance(candidates, list):
        return result

    for item in candidates:
        if not isinstance(item, dict):
            continue
        raw_type = str(item.get("type", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if raw_type not in allowed_types or not content:
            continue
        semantic_keys = build_semantic_keys(
            content=content,
            llm_keys=item.get("semantic_keys"),
        )
        result.append(
            {
                "type": raw_type,
                "content": content,
                "semantic_keys": semantic_keys,
            }
        )
    return result
