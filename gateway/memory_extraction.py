"""Memory candidate language extraction and verification, without write authority."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from .memory_text_utils import (
    extract_json_object, extract_tokens, normalize_candidates,
    normalize_memory_modality, normalize_memory_persistence,
)


def verify_candidates_fallback(
    user_input: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Lightweight guard when verifier LLM is unavailable.
    Keep candidates with minimum semantic overlap against user input.
    """
    user_tokens = set(extract_tokens(user_input))
    if not user_tokens:
        return []
    accepted: List[Dict[str, Any]] = []
    for c in candidates or []:
        cand_tokens = set(extract_tokens(str(c.get("content", ""))))
        if not cand_tokens:
            continue
        overlap = len(user_tokens.intersection(cand_tokens)) / max(1, len(cand_tokens))
        if overlap < 0.25:
            continue
        row = dict(c)
        row["verify_confidence"] = round(float(overlap), 3)
        row["verify_reason"] = "fallback_overlap"
        row["verify_evidence"] = ""
        row["verify_attribution"] = "user"
        row["modality"] = normalize_memory_modality(row.get("modality"))
        row["persistence"] = normalize_memory_persistence(row.get("persistence"))
        accepted.append(row)
    return accepted


async def verify_candidates(
    call_llm: Callable[..., Awaitable[str]],
    user_id: str,
    user_input: str,
    assistant_output: str,
    candidates: List[Dict[str, Any]],
    interaction_context: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Verify candidate meaning/attribution before writing to memory.
    This prevents memory drift caused by assistant-side interpretations.
    """
    if not candidates:
        return []
    prompt = (
        "You are a memory write verifier.\n"
        "Given RECENT_CONTEXT, USER_INPUT, ASSISTANT_OUTPUT, candidate memories, and their RELATED_MEMORIES, "
        "decide whether each candidate can be safely written.\n"
        "Acceptance requirements:\n"
        "1) Candidate meaning is supported by the current interaction or by immediate conversational context.\n"
        "2) Attribution is correct: should not convert assistant explanation into user preference.\n"
        "3) Short answers may be valid when they answer a direct prior question in RECENT_CONTEXT.\n"
        "For every accepted candidate, verify its semantic scope:\n"
        "- modality: actual for asserted state, plan for committed intention, hypothetical for possibilities, examples, roleplay, or uncommitted conditions.\n"
        "- persistence: ephemeral for the current moment/turn/operation, bounded for state useful across turns but expected to expire or change, durable for long-lived state.\n"
        "For each accepted candidate, classify its relationship to RELATED_MEMORIES as one of: "
        "new, equivalent, compatible, updates, contradicts, unclear. "
        "Shared topics are not contradictions. Contradicts means both statements cannot be true in the same scope and time.\n"
        "Return strict JSON:\n"
        "{\"decisions\":[{\"index\":0,\"accept\":true|false,\"confidence\":0..1,"
        "\"reason\":\"...\",\"evidence\":\"...\",\"attribution\":\"user|assistant|project|unclear\","
        "\"modality\":\"actual|plan|hypothetical\","
        "\"persistence\":\"ephemeral|bounded|durable\","
        "\"relationship\":\"new|equivalent|compatible|updates|contradicts|unclear\","
        "\"related_indexes\":[0]}]}\n"
        "Reject unsupported candidates, but let the deterministic write gate handle modality and persistence policy."
    )
    cands_json = json.dumps(candidates, ensure_ascii=False)
    context_json = json.dumps(interaction_context or [], ensure_ascii=False)
    query = (
        f"[RECENT_CONTEXT]\n{context_json}\n\n"
        f"[USER_INPUT]\n{user_input}\n\n"
        f"[ASSISTANT_OUTPUT]\n{assistant_output}\n\n"
        f"[CANDIDATES]\n{cands_json}\n"
    )
    text = await call_llm(user_id, prompt, query)
    if not text:
        return verify_candidates_fallback(user_input, candidates)
    obj = extract_json_object(text)
    if not isinstance(obj, dict):
        return verify_candidates_fallback(user_input, candidates)
    decisions = obj.get("decisions")
    if not isinstance(decisions, list):
        return verify_candidates_fallback(user_input, candidates)

    accepted: List[Dict[str, Any]] = []
    by_index: Dict[int, Dict[str, Any]] = {}
    for d in decisions:
        if not isinstance(d, dict):
            continue
        try:
            idx = int(d.get("index"))
        except Exception:
            continue
        by_index[idx] = d

    for idx, c in enumerate(candidates):
        d = by_index.get(idx, {})
        accept = bool(d.get("accept", False))
        conf = float(d.get("confidence", 0.0) or 0.0)
        attribution = str(d.get("attribution", "unclear")).strip().lower()
        if (not accept) or conf < 0.5 or attribution in {"assistant", "unclear"}:
            continue
        row = dict(c)
        row["verify_confidence"] = round(conf, 3)
        row["verify_reason"] = str(d.get("reason", "")).strip()[:300]
        row["verify_evidence"] = str(d.get("evidence", "")).strip()[:500]
        row["verify_attribution"] = attribution
        row["modality"] = normalize_memory_modality(d.get("modality") or row.get("modality"))
        row["persistence"] = normalize_memory_persistence(d.get("persistence") or row.get("persistence"))
        related = row.get("related_memories") if isinstance(row.get("related_memories"), list) else []
        relationship = str(d.get("relationship") or "").strip().lower()
        allowed_relationships = {
            "new",
            "equivalent",
            "compatible",
            "updates",
            "contradicts",
            "unclear",
        }
        if relationship not in allowed_relationships:
            relationship = "unclear" if related else "new"
        related_indexes: List[int] = []
        for value in d.get("related_indexes") or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(related) and index not in related_indexes:
                related_indexes.append(index)
        row["memory_relationship"] = relationship
        row["relationship_indexes"] = related_indexes
        accepted.append(row)
    return accepted


async def classify_interaction(
    call_llm: Callable[..., Awaitable[str]],
    user_input: str,
    assistant_output: str,
    user_id: str,
    interaction_context: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    prompt = (
        "You are a strict memory classifier. Input is one completed interaction "
        "(recent context + user input + assistant output). Ignore tool logs and execution traces. "
        "Extract user or project state that may be relevant to memory policy; the write gate decides whether it belongs in long-term memory.\n"
        "Allowed types: goal, preference, constraint, identity, project_state.\n"
        "Return strict JSON with this schema:\n"
        "{\"has_long_term_state\": true|false, "
        "\"candidates\": [{\"type\": \"...\", \"content\": \"...\", \"semantic_keys\": [\"...\"], "
        "\"modality\": \"actual|plan|hypothetical\", \"persistence\": \"ephemeral|bounded|durable\"}]}\n"
        "Rules:\n"
        "- If no memory-relevant state exists, return has_long_term_state=false and empty candidates.\n"
        "- Keep each content concise and factual.\n"
        "- modality describes whether the state is asserted, a committed plan, or merely hypothetical/example/roleplay.\n"
        "- persistence describes whether it lasts only for the current moment, for a bounded period, or is genuinely durable.\n"
        "- semantic_keys should include cross-lingual equivalents when obvious (example: apple / 苹果).\n"
        "- semantic_keys should be lower-case normalized concepts, not long sentences.\n"
        "- Do not infer semantic scope from particular English words; interpret the interaction in its own language and context.\n"
        "- Ignore raw tool/output details that do not describe user or project state.\n"
        "- Candidate must reflect user/project meaning from the interaction; do not transform assistant explanation into user preference.\n"
        "- If the current user input is a short answer to an immediate prior assistant question, use RECENT_CONTEXT to resolve what it means."
    )
    context_json = json.dumps(interaction_context or [], ensure_ascii=False)
    query = (
        f"[RECENT_CONTEXT]\n{context_json}\n\n"
        f"[USER_INPUT]\n{user_input}\n\n"
        f"[ASSISTANT_OUTPUT]\n{assistant_output}\n"
    )
    try:
        text = await call_llm(user_id, prompt, query)
        if not text:
            return {"has_long_term_state": False, "candidates": []}
        obj = extract_json_object(text)
        if not obj:
            return {"has_long_term_state": False, "candidates": []}

        has_state = bool(obj.get("has_long_term_state", False))
        candidates = normalize_candidates(obj.get("candidates", []))
        if not candidates:
            return {"has_long_term_state": False, "candidates": []}
        return {"has_long_term_state": has_state, "candidates": candidates}
    except Exception as e:
        logger.debug("MemoryService: LLM interaction classifier failed: {}", e)
        return {"has_long_term_state": False, "candidates": []}
