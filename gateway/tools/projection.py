"""Stateless projections of the current Runtime tool catalog."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .spec import SideEffectLevel


def capability_identifiers_overlap(declared: str, requested: str) -> bool:
    left = str(declared or "").strip().lower()
    right = str(requested or "").strip().lower()
    return bool(left and right and (left == right or left.startswith(f"{right}.") or right.startswith(f"{left}.")))


def registry_revision(catalog: List[Dict[str, Any]]) -> str:
    stable = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def project_capability_snapshot(
    catalog: List[Dict[str, Any]],
    *,
    preferred_tools: Optional[List[str]] = None,
    schema_budget_chars: int = 12000,
) -> Dict[str, Any]:
    """Compute model-visible content; the service owns identity and publication."""
    preferred = {str(item).strip() for item in (preferred_tools or []) if str(item).strip()}
    compact_index: List[Dict[str, Any]] = []
    candidates: List[tuple[int, str, Dict[str, Any]]] = []
    for row in catalog:
        service_name = str(row.get("service_name") or "").strip()
        tool_name = str(row.get("tool_name") or "").strip()
        if not tool_name:
            continue
        full_name = (
            tool_name
            if not service_name or tool_name == service_name or tool_name.startswith(f"{service_name}.")
            else f"{service_name}.{tool_name}"
        )
        compact_index.append(
            {
                "name": full_name,
                "description": str(row.get("description") or "").strip(),
                "callable_now": bool(row.get("callable_now", False)),
                "callable_reason": str(row.get("callable_reason") or ""),
                "requires_confirmation": bool(row.get("requires_confirmation", False)),
                "side_effect_level": str(row.get("side_effect_level") or ""),
                "side_effect_selector": dict(row.get("side_effect_selector") or {}),
                "schema_status": str(row.get("schema_status") or "missing"),
                "capability_type": str(row.get("capability_type") or "general"),
                "required_capability": str(row.get("required_capability") or "") or None,
                "capability_details": dict(row.get("capability_details") or {}),
            }
        )
        schema = row.get("input_schema") if isinstance(row.get("input_schema"), dict) else {}
        if not schema:
            continue
        priority = 0 if full_name in preferred else 1
        candidates.append(
            (
                priority,
                full_name,
                {
                    "name": full_name,
                    "description": str(row.get("description") or "").strip(),
                    "input_schema": schema,
                    "output_schema": dict(row.get("output_schema") or {}),
                    "side_effect_level": str(row.get("side_effect_level") or ""),
                    "side_effect_selector": dict(row.get("side_effect_selector") or {}),
                    "required_capability": str(row.get("required_capability") or "") or None,
                },
            )
        )

    selected_specs: List[Dict[str, Any]] = []
    remaining = max(0, int(schema_budget_chars))
    for _, _, spec in sorted(candidates, key=lambda item: (item[0], item[1])):
        size = len(json.dumps(spec, ensure_ascii=False, separators=(",", ":")))
        if size > remaining and selected_specs:
            continue
        if size > remaining:
            break
        selected_specs.append(spec)
        remaining -= size

    return {
        "registry_revision": registry_revision(catalog),
        "total_count": len(compact_index),
        "callable_count": sum(1 for item in compact_index if item["callable_now"]),
        "compact_index": compact_index,
        "selected_specs": selected_specs,
        "schema_budget_chars": int(schema_budget_chars),
        "missing_schema_count": sum(1 for item in compact_index if item["schema_status"] == "missing"),
    }

def resolve_capability_candidates(
    catalog: List[Dict[str, Any]],
    *,
    request: Dict[str, Any],
    required: set[str],
    max_effect: str,
    preferred_tools: Optional[List[str]] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    """Rank a policy/readiness-annotated catalog; never authorize or execute a tool."""
    effect_rank = {
        SideEffectLevel.READ_ONLY.value: 0,
        SideEffectLevel.WORKSPACE_WRITE.value: 1,
        SideEffectLevel.EXTERNAL_WRITE.value: 2,
        SideEffectLevel.PRIVILEGED_HOST_ACTION.value: 3,
    }
    preferred = {str(item).strip() for item in (preferred_tools or []) if str(item).strip()}
    candidates: List[tuple[int, int, str, Dict[str, Any]]] = []
    unavailable: List[Dict[str, Any]] = []
    for row in catalog:
        declared = str(row.get("required_capability") or "").strip()
        if not declared or not any(capability_identifiers_overlap(declared, item) for item in required):
            continue
        if not bool(row.get("callable_now")):
            unavailable.append({key: row.get(key) for key in (
                "service_name", "tool_name", "required_capability", "callable_reason", "dependency_ready", "config_ready",
            )})
            continue
        effect = str(row.get("side_effect_level") or SideEffectLevel.PRIVILEGED_HOST_ACTION.value)
        selector = row.get("side_effect_selector") if isinstance(row.get("side_effect_selector"), dict) else {}
        groups = selector.get("groups") if isinstance(selector.get("groups"), dict) else {}
        effect_options = {effect, *(str(item) for item in groups if str(item) in effect_rank)}
        eligible_effects = [item for item in effect_options if effect_rank.get(item, 3) <= effect_rank[max_effect]]
        if not eligible_effects:
            continue
        service_name = str(row.get("service_name") or "").strip()
        tool_name = str(row.get("tool_name") or "").strip()
        full_name = (
            tool_name
            if not service_name or tool_name == service_name or tool_name.startswith(f"{service_name}.")
            else f"{service_name}.{tool_name}"
        )
        candidate = {
            "name": full_name,
            "description": str(row.get("description") or "").strip(),
            "required_capability": declared,
            "side_effect_level": effect,
            "side_effect_options": sorted(effect_options, key=lambda item: effect_rank.get(item, 3)),
            "requires_confirmation": bool(row.get("requires_confirmation")),
            "confirmation_depends_on_arguments": bool(groups),
            "input_schema": dict(row.get("input_schema") or {}),
            "output_schema": dict(row.get("output_schema") or {}),
        }
        candidates.append(
            (
                0 if full_name in preferred else 1,
                min(effect_rank.get(item, 3) for item in eligible_effects),
                full_name,
                candidate,
            )
        )

    resolved = [item[3] for item in sorted(candidates, key=lambda item: (item[0], item[1], item[2]))[:max(1, limit)]]
    return {
        "objective": str(request.get("objective") or "").strip(),
        "required_capabilities": sorted(required),
        "preferred_modalities": [
            str(item).strip()
            for item in (request.get("preferred_modalities") or [])
            if str(item).strip()
        ],
        "max_side_effect": max_effect,
        "candidate_count": len(resolved),
        "candidates": resolved,
        "unavailable_candidates": unavailable[:max(1, limit)],
        "registry_revision": registry_revision(catalog),
    }
