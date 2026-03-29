from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from gateway.tool_service import ToolInvocationContext


class TextWordStatsTool:
    tool_id = "text.word_stats"
    name = "text.word_stats"
    description = "Compute basic text stats: chars/words/lines."
    official = True
    official_domain = "text"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        text = str((args or {}).get("text") or "")
        words = [w for w in text.replace("\r\n", "\n").replace("\r", "\n").split() if w]
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if text else []
        return {
            "chars": len(text),
            "words": len(words),
            "lines": len(lines),
        }


class TextFindMatchesTool:
    tool_id = "text.find_matches"
    name = "text.find_matches"
    description = "Find query occurrences in text and return previews."
    official = True
    official_domain = "text"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        text = str((args or {}).get("text") or "")
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        case_sensitive = bool((args or {}).get("case_sensitive", False))
        max_results = int((args or {}).get("max_results") or 20)
        max_results = max(1, min(max_results, 200))

        source = text if case_sensitive else text.lower()
        needle = query if case_sensitive else query.lower()

        hits: List[Dict[str, Any]] = []
        cursor = 0
        while len(hits) < max_results:
            idx = source.find(needle, cursor)
            if idx < 0:
                break
            start = max(0, idx - 120)
            end = min(len(text), idx + len(query) + 120)
            hits.append(
                {
                    "index": idx,
                    "preview": text[start:end],
                }
            )
            cursor = idx + max(1, len(query))
        return {"query": query, "count": len(hits), "hits": hits}


class TextNormalizeJsonTool:
    tool_id = "text.normalize_json"
    name = "text.normalize_json"
    description = "Validate and normalize JSON text."
    official = True
    official_domain = "text"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        raw = str((args or {}).get("text") or "")
        if not raw.strip():
            raise ValueError("text is required")
        indent = int((args or {}).get("indent") or 2)
        indent = max(0, min(indent, 8))
        sort_keys = bool((args or {}).get("sort_keys", True))
        obj = json.loads(raw)
        normalized = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys)
        return {"valid": True, "normalized": normalized, "type": type(obj).__name__}

