from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Literal, Optional


ACTION_MODE_CONTRACT_MARKER = "Action mode contract:"


@dataclass(frozen=True)
class ActionEnvelope:
    action: Literal["tool_call", "answer"]
    tool_name: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    content: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


def iter_json_objects(content: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    pos = 0
    content = content or ""

    while True:
        start_idx = -1
        idx1 = content.find("{", pos)
        idx2 = content.find("\uFF5B", pos)

        if idx1 != -1 and idx2 != -1:
            start_idx = min(idx1, idx2)
        elif idx1 != -1:
            start_idx = idx1
        elif idx2 != -1:
            start_idx = idx2

        if start_idx == -1:
            break

        try:
            if content[start_idx] == "\uFF5B":
                pos = start_idx + 1
                continue
            obj, end_idx = decoder.raw_decode(content, start_idx)
            pos = start_idx + end_idx
            yield obj
        except json.JSONDecodeError:
            pos = start_idx + 1


def parse_action_envelope(content: str) -> Optional[ActionEnvelope]:
    for obj in iter_json_objects(content):
        if not isinstance(obj, dict):
            continue
        action = str(obj.get("action") or "").lower()
        if action == "tool_call":
            args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
            return ActionEnvelope(
                action="tool_call",
                tool_name=str(obj.get("tool_name") or ""),
                args=dict(args),
                raw=dict(obj),
            )
        if action == "answer":
            content_value = obj.get("content")
            if content_value is None:
                content_value = obj.get("answer")
            return ActionEnvelope(
                action="answer",
                content=str(content_value or ""),
                raw=dict(obj),
            )
    return None


def build_action_mode_contract() -> str:
    return (
        f"{ACTION_MODE_CONTRACT_MARKER}\n"
        "- This turn has already been routed to action mode by the gateway.\n"
        "- Every assistant action turn in this lifecycle must be exactly one strict JSON action object and no prose.\n"
        '- Use {"action":"tool_call","tool_name":"<registered tool>","args":{...}} if an available runtime tool can advance the user\'s concrete goal.\n'
        '- Use {"action":"answer","content":"..."} if no tool should be called or the action budget is exhausted.\n'
        "- Do not narrate tool usage, do not write pseudo calls, and do not claim external results before an Observation is provided.\n"
        "- If no available tool can advance the goal, explain the capability gap in the JSON answer instead of simulating a tool call.\n"
        "- This protocol is internal. Never mention action mode, JSON envelopes, tool schema, or protocol corrections to the user."
    )


def build_protocol_correction(*, final_answer: bool = False) -> str:
    if final_answer:
        return (
            "Protocol correction: return exactly one JSON answer object and no prose. "
            'Use {"action":"answer","content":"..."} based only on the runtime Observations. '
            "Do not propose or narrate another tool call because no tool budget remains. "
            "Do not mention action mode, JSON envelopes, tool schema, or this correction to the user."
        )
    return (
        "Protocol correction: your previous response was not a valid action object. "
        "Return exactly one JSON object and no prose. "
        'Use {"action":"tool_call","tool_name":"<registered tool>","args":{...}} '
        "when a tool can advance the task, or "
        '{"action":"answer","content":"..."} when no available tool should be called. '
        "Do not mention action mode, JSON envelopes, tool schema, or this correction to the user."
    )


def build_observation_gate(*, failed: bool, remaining_steps: int) -> str:
    base = (
        "\nLightweight ReAct gate: treat the tool result blocks above as Observation. "
        "Before answering, check whether the user's concrete action goal is actually satisfied. "
        "Do not expose hidden chain-of-thought. "
        "Because this is action mode, the next assistant action turn must still be exactly one JSON action object."
    )
    if failed:
        if remaining_steps <= 0:
            return (
                base
                + ' No tool steps remain. Return {"action":"answer","content":"..."} with the observed failure, '
                "what was verified, and the next actionable retry suggestion. Do not output a tool_call."
            )
        return (
            base
            + ' A required tool call failed. If a safe alternative tool can still complete or verify the task, return {"action":"tool_call",...}; '
            'otherwise return {"action":"answer","content":"..."} with the observed failure and next step.'
        )
    if remaining_steps > 0:
        return (
            base
            + ' If cheap verification is available for a state-changing or external-data claim, return {"action":"tool_call",...}. '
            'If the Observation itself proves the result, return {"action":"answer","content":"..."} and cite the Observation.'
        )
    return (
        base
        + ' No tool steps remain. Return {"action":"answer","content":"..."} only from the observed result. '
        "If the Observation does not prove completion, state the uncertainty instead of claiming success."
    )


def build_tool_prompt_protocol(
    *,
    registered_tools: Optional[Iterable[Dict[str, Any]]] = None,
) -> str:
    snapshot = [
        dict(item)
        for item in (registered_tools or [])
        if isinstance(item, dict)
    ]
    return (
        "Tool execution protocol:\n"
        "- Tools are available only through the runtime tool-call loop. Use them when the user's request requires current data, exact calculation, file/workspace changes, code execution, search, or another external action.\n"
        "- The runtime registered-tools snapshot below is the source of truth for this turn. Invoke only entries with callable_now=true.\n"
        '- In action mode, every assistant action turn must use the standard action envelope: {"action":"tool_call","tool_name":"<registered tool>","args":{...}} or {"action":"answer","content":"..."}.\n'
        "- Do not mix prose with an action envelope.\n"
        "- For normal tool-call loop compatibility outside action mode, the runtime still accepts the registered tool JSON shape with tool_name, agentType, service_name, and args.\n"
        '- Local official tool JSON shape: {"tool_name":"<tool id>","agentType":"local","service_name":"<tool id>","args":{...}}.\n'
        '- MCP/extension tool JSON shape: {"tool_name":"<service>.<action>","agentType":"mcp","service_name":"<service>","args":{"tool_name":"<action>", ...}}.\n'
        "- Never write invented function-call syntax or claim an unregistered tool invocation.\n"
        "- Never claim a tool ran, returned data, searched the web, read a file, or created a file unless a runtime observation/result has been provided in the conversation.\n"
        "- After a tool result is provided, answer with an action answer envelope in action mode, or normal prose outside action mode.\n"
        "Runtime registered tools (structured JSON):\n"
        f"{json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))}"
    )
