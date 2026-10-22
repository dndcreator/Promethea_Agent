"""Organization document preparation and extraction; no membership or publication authority."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def as_int(value: Any, default: int, *, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    out = max(minimum, out)
    if maximum is not None:
        out = min(maximum, out)
    return out


async def extract_context_items(
    llm_client: Optional[Any],
    *,
    text: str,
    audience: Optional[str],
    register: Optional[str],
    use_llm: bool,
    extract_text_max_chars: int,
    heuristic_max_lines: int,
    heuristic_max_items: int,
    user_config: Optional[Dict[str, Any]],
    user_id: Optional[str],
) -> List[Dict[str, Any]]:
    aud = normalize_text(audience or "")
    reg = normalize_text(register or "")
    if use_llm and llm_client and hasattr(llm_client, "call_llm"):
        prompt_system = (
            "Extract enterprise expression context from document text.\n"
            "Output strict JSON: {\"items\":[{\"concept\":\"...\",\"expression\":\"...\",\"knowledge_kind\":"
            "\"fact|policy|style|terminology|template\",\"audience\":\"...\",\"register\":\"...\","
            "\"terms_locked\":[...],\"confidence\":0.0-1.0}]}"
        )
        prompt_user = (
            f"Document:\n{text[: max(1, int(extract_text_max_chars))]}\n\n"
            f"Default audience: {aud or 'unknown'}\nDefault register: {reg or 'unknown'}\n"
        )
        try:
            out = await llm_client.call_llm(
                [{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}],
                user_config=user_config,
                user_id=user_id,
            )
            data = extract_json_object(str((out or {}).get("content") or ""))
            rows = data.get("items") if isinstance(data.get("items"), list) else []
            cleaned: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                concept = normalize_text(row.get("concept"))
                expr = normalize_text(row.get("expression"))
                if not concept or not expr:
                    continue
                cleaned.append(
                    {
                        "concept": concept,
                        "expression": expr,
                        "knowledge_kind": normalize_text(row.get("knowledge_kind") or "fact").lower(),
                        "audience": normalize_text(row.get("audience") or aud),
                        "register": normalize_text(row.get("register") or reg),
                        "terms_locked": [
                            str(x).strip()
                            for x in (row.get("terms_locked") or [])
                            if str(x).strip()
                        ],
                        "confidence": as_float(row.get("confidence", 0.6), 0.6),
                    }
                )
            if cleaned:
                return cleaned
        except Exception as e:
            logger.debug("OrgContextService: llm extract failed, fallback to heuristic: {}", e)

    return heuristic_extract(
        text=text,
        audience=aud,
        register=reg,
        max_lines=as_int(heuristic_max_lines, 30, minimum=1, maximum=1000),
        max_items=as_int(heuristic_max_items, 15, minimum=1, maximum=200),
    )


def chunk_text(text: str, *, chunk_chars: int, max_chunks: int) -> List[str]:
    content = str(text or "").strip()
    if not content:
        return []
    size = max(500, int(chunk_chars))
    limit = max(1, int(max_chunks))
    chunks: List[str] = []
    cursor = 0
    while cursor < len(content) and len(chunks) < limit:
        end = min(len(content), cursor + size)
        if end < len(content):
            boundary = content.rfind("\n", cursor + size // 2, end)
            if boundary > cursor:
                end = boundary
        chunk = content[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        cursor = max(end, cursor + 1)
    return chunks


def heuristic_extract(
    *,
    text: str,
    audience: str,
    register: str,
    max_lines: int = 30,
    max_items: int = 15,
) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    picked = []
    for ln in lines[: max(1, int(max_lines))]:
        if len(ln) < 6:
            continue
        concept = ln[:32].strip()
        if not concept:
            continue
        picked.append(
            {
                "concept": concept,
                "expression": ln[:200],
                "knowledge_kind": "fact",
                "audience": audience,
                "register": register,
                "terms_locked": [],
                "confidence": 0.45,
            }
        )
    return picked[: max(1, int(max_items))]
