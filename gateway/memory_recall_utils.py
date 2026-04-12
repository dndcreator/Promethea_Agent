from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def normalize_query_text(text: str) -> str:
    lowered = (text or "").strip().lower()
    return re.sub(r"\s+", " ", lowered)


def tokenize_text(text: str) -> List[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", normalize_query_text(text))
    tokens: List[str] = []
    for chunk in chunks:
        if re.match(r"^[a-z0-9_]+$", chunk):
            tokens.extend([x for x in chunk.split("_") if x])
        else:
            tokens.append(chunk)
    return tokens


def resolve_recall_policy(
    *,
    mode: str,
    cfg: Optional[Dict[str, Any]],
    request_top_k: int,
) -> Dict[str, Any]:
    mode_normalized = str(mode or "fast").strip().lower()
    if mode_normalized not in {"fast", "deep", "workflow"}:
        mode_normalized = "fast"

    defaults = {
        "fast": {"top_k": 4, "allowed_layers": ["summary", "direct", "recent"], "max_age_days": 30},
        "deep": {"top_k": 8, "allowed_layers": ["summary", "concept", "direct", "related", "salient", "recent"], "max_age_days": 90},
        "workflow": {"top_k": 8, "allowed_layers": ["summary", "concept", "direct", "related"], "max_age_days": 45},
    }
    policy = dict(defaults[mode_normalized])
    data = cfg or {}
    recall_cfg = data.get("memory", {}).get("recall_policy", {})
    mode_cfg = recall_cfg.get(mode_normalized, {}) if isinstance(recall_cfg, dict) else {}
    if isinstance(mode_cfg, dict):
        if "top_k" in mode_cfg:
            policy["top_k"] = int(mode_cfg.get("top_k") or policy["top_k"])
        if "allowed_layers" in mode_cfg and isinstance(mode_cfg.get("allowed_layers"), list):
            policy["allowed_layers"] = [str(x) for x in mode_cfg.get("allowed_layers") if str(x).strip()]
        if "max_age_days" in mode_cfg:
            policy["max_age_days"] = int(mode_cfg.get("max_age_days") or policy["max_age_days"])
    profile = str(data.get("memory", {}).get("profile", "balanced") or "balanced").strip().lower()
    if profile == "conservative":
        policy["top_k"] = max(2, int(policy["top_k"]) - 2)
        policy["max_age_days"] = max(7, int(policy["max_age_days"]) // 2)
    elif profile == "aggressive":
        policy["top_k"] = min(20, int(policy["top_k"]) + 2)
        policy["max_age_days"] = min(365, int(policy["max_age_days"]) + 30)

    policy["top_k"] = max(1, min(20, int(request_top_k or policy["top_k"] or 5)))
    policy["max_age_days"] = max(1, min(365, int(policy["max_age_days"])))
    policy["mode"] = mode_normalized
    return policy


def source_layer_to_memory_type(layer: str) -> str:
    mapping = {
        "summary": "semantic",
        "concept": "semantic",
        "direct": "episodic",
        "related": "episodic",
        "salient": "episodic",
        "recent": "working",
    }
    return mapping.get(str(layer or "").lower(), "episodic")


def parse_candidate_datetime(raw_value: Optional[str]) -> Optional[datetime]:
    if not raw_value:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def build_recall_reason(candidate: Dict[str, Any], *, mode: str, session_id: str) -> str:
    layer = str(candidate.get("source_layer") or "")
    if mode == "workflow" and candidate.get("source_session") == session_id:
        return "active_workflow_context"
    if layer == "summary":
        return "project_memory_match"
    if layer == "concept":
        return "reasoning_template_match"
    if layer == "recent":
        return "recent_session_context"
    if layer in {"direct", "related", "salient"}:
        return "user_profile_match"
    return "memory_layer_match"


def format_recall_context(records: List[Any]) -> str:
    if not records:
        return ""
    lines: List[str] = []
    current_layer = ""
    for item in records:
        source_layer = getattr(item, "source_layer", "")
        content = getattr(item, "content", "")
        if source_layer != current_layer:
            current_layer = source_layer
            lines.append(f"[{current_layer}]")
        snippet = (content or "").strip().replace("\n", " ")
        if len(snippet) > 140:
            snippet = snippet[:137] + "..."
        lines.append(f"- {snippet}")
    return "\n".join(lines)
