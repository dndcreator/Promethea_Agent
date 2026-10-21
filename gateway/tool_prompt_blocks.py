from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

CAPABILITIES_HEADER = "Runtime capabilities:\n"


def build_action_protocol_prompt() -> str:
    """Render the canonical model-to-runtime action contract."""
    examples = {
        "single": {"action": "tool_call", "tool_name": "service.tool", "args": {}},
        "batch": {
            "action": "tool_calls",
            "calls": [{"id": "optional", "tool_name": "service.tool", "args": {}}],
        },
        "inspect": {"action": "capability_inspect", "capability_names": ["service.tool"]},
        "resolve": {
            "action": "capability_request",
            "objective": "the evidence or effect needed for the next step",
            "required_capabilities": ["declared.capability"],
            "preferred_modalities": [],
            "max_side_effect": "read_only",
        },
    }
    return (
        "Runtime action protocol:\n"
        "Return exactly one JSON action object and no surrounding prose on every model step. "
        "When the task is complete, return "
        "{\"action\":\"answer\",\"content\":\"the natural-language reply for the user\",\"evidence_refs\":[]}. "
        "Only the content of a validated answer action is user-visible. "
        "You decide the next action; the runtime alone validates availability, executes tools, and commits observations. "
        "When you know the needed capability but not the correct tool, use capability_request with capability identifiers "
        "declared by the Runtime snapshot; describe the required evidence or effect, not a guessed implementation. "
        "Use capability_inspect when the compact capability index shows a relevant tool but its full input schema is not present. "
        "Use tool_calls for independent calls that may execute concurrently. "
        "Base claims about external or runtime results only on supplied observations. "
        "A failed observation is an obstacle, not the end of your task: inspect it, adapt the next action, "
        "or explain the remaining block in an answer in the user's language. Never bypass authorization or sandbox limits. "
        "Process experience is advisory: adapt or combine it and continue general planning when it does not fit. "
        "When adopting an exposed process rule for tool calls, include its exact versioned reference in procedure_refs. "
        "This declares use, not proof that the rule caused success. "
        "For multi-step work, optionally attach gap_update to the same action: "
        '{"revision":0,"create":[{"id":"g1","kind":"epistemic|achievement","requirement":"what remains unknown or undone"}],"updates":[],"focus":["g1"]}. '
        "Omit it for direct replies and unchanged gaps. Use the current Runtime gap revision, stable ids, and small deltas. "
        'An update is {"id":"g1","state":"open|blocked|resolved","evidence_refs":["obs_..."]}. '
        "Resolution requires supplied successful observations; inferred resolution is not verified goal completion. "
        'A new gap may declare check={"tool_name":"registered.tool","pointer":"/result_field","expected":true} before obtaining verifying evidence. '
        "Checks are immutable exact JSON-value assertions, not proof of full goal coverage. Reopen gaps when contradicted. "
        "Recent Runtime obstacles are projected beside gaps even before you have declared any; "
        "use their observation references when creating or updating relevant gaps. Failure is not evidence of resolution. "
        "Do not discard goals or rename gaps to hide lack of progress. Final replies may report blocked or unfinished work. "
        "This protocol is internal and must not be mentioned to the user.\n"
        f"Shapes: {json.dumps(examples, ensure_ascii=False, separators=(',', ':'))}"
    )


def build_tool_execution_prompt(
    *,
    registered_tools: Optional[Iterable[Dict[str, Any]]] = None,
    capability_snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the model-visible projection of the authoritative capability snapshot."""
    tools = [dict(item) for item in (registered_tools or []) if isinstance(item, dict)]
    snapshot = capability_snapshot if isinstance(capability_snapshot, dict) else {}
    metadata = {
        key: snapshot.get(key)
        for key in (
            "snapshot_id",
            "registry_revision",
            "generated_at",
            "total_count",
            "callable_count",
            "missing_schema_count",
        )
    }
    return (
        CAPABILITIES_HEADER +
        "- This snapshot is the source of truth for tools available in this turn.\n"
        "- Invoke only entries with callable_now=true.\n"
        "- Use the registered identifier exactly; do not invent or simulate calls.\n"
        "- Choose the callable capability with the lowest declared side effect that can satisfy the goal. "
        "Do not substitute an arbitrary command or host-control action for an available read-only capability.\n"
        "- Runtime observations, not model narration, establish whether a call ran or succeeded.\n"
        f"Snapshot: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))}\n"
        "Compact index and selected schemas:\n"
        f"{json.dumps(tools, ensure_ascii=False, separators=(',', ':'))}"
    )
