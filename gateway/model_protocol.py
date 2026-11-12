"""Chat Completions wire codec. No dispatch, authorization, or Agent decisions."""
from copy import deepcopy
import json

from gateway.action.completion import parse_final_answer
from gateway.action.model_action import InvalidModelAction, decode_action_object, parse_model_action
from gateway.tool_prompt_blocks import build_action_protocol_prompt


def native_functions():
    text = {"type": "string"}
    strings = {"type": "array", "items": text}
    tool = {"type": "object", "properties": {"tool_name": text, "args": {"type": "object"}, "id": text}, "required": ["tool_name", "args"]}
    shapes = {
        "tool_call": ({"tool_name": text, "args": {"type": "object"}}, ["tool_name", "args"]),
        "tool_calls": ({"calls": {"type": "array", "items": tool, "minItems": 1}}, ["calls"]),
        "capability_inspect": ({"capability_names": strings}, ["capability_names"]),
        "capability_request": ({"objective": text, "required_capabilities": strings, "preferred_modalities": strings,
                                "max_side_effect": {"type": "string", "enum": ["read_only", "workspace_write", "external_write", "privileged_host_action"]}}, ["objective", "required_capabilities"]),
        "answer": ({"content": text, "evidence_refs": strings,
                    "disposition": {"type": "string", "enum": ["blocked"]}}, ["content"]),
        "await_user": ({"content": {"type": "string", "minLength": 1, "maxLength": 4000},
                        "input_kind": {"type": "string", "enum": ["acknowledgement", "text"]},
                        "user_dependency": {"type": "object", "properties": {
                            "kind": {"type": "string", "enum": ["user_information", "user_choice", "human_action"]},
                            "reason": {"type": "string", "minLength": 1, "maxLength": 400},
                            "gap_ids": strings, "evidence_refs": strings},
                            "required": ["kind", "reason"], "additionalProperties": False}}, ["content", "user_dependency"]),
    }
    return [{"type": "function", "function": {"name": name, "description": "Propose canonical Runtime action: " + name,
             "parameters": {"type": "object", "properties": {**properties, "procedure_refs": strings, "gap_update": {"type": "object"}},
                            "required": required, "additionalProperties": False}}}
            for name, (properties, required) in shapes.items()]


def decode_native(message, *, final=False):
    if not isinstance(message, dict):
        raise InvalidModelAction("native message must be an object")
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list):
        raise InvalidModelAction("native calls must be an array")
    if not calls:
        action = parse_final_answer(message.get("content") or "")
        return {"action": "answer", "content": action.content, **{k: v for k, v in action.raw.items() if k != "action"}}, {}
    ids, actions, bindings = set(), [], {}
    permitted = {row["function"]["name"] for row in native_functions()}
    metadata = {}
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise InvalidModelAction("native function call must be an object")
        identifier = call.get("id")
        function = call.get("function") or {}
        kind = function.get("name")
        if final and kind not in {"answer", "await_user"}:
            raise InvalidModelAction("execution is disabled during final completion")
        if call.get("type") != "function" or not isinstance(identifier, str) or not identifier or identifier in ids or not isinstance(kind, str) or kind not in permitted:
            raise InvalidModelAction("native function and unique call id must be declared")
        ids.add(identifier)
        args = decode_action_object(function.get("arguments") or "")
        if "action" in args:
            raise InvalidModelAction("native function arguments cannot override their action kind")
        raw = {"action": kind, **args}
        if kind in {"tool_call", "capability_inspect", "capability_request"}:
            raw["id"] = identifier
        elif kind == "tool_calls":
            for index, item in enumerate(raw.get("calls") or []):
                if isinstance(item, dict) and not item.get("id"):
                    item["id"] = f"{identifier}_{index}"
        action = parse_model_action(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        for key in ("gap_update", "procedure_refs"):
            if key in raw:
                if key in metadata:
                    raise InvalidModelAction("declare batch metadata on only one native call")
                metadata[key] = raw[key]
        actions.append(action)
        bindings[identifier] = [item.call_id for item in action.calls]
    if len(actions) == 1:
        return actions[0].raw, bindings
    if any(action.kind in {"answer", "await_user"} for action in actions):
        raise InvalidModelAction("answer and await_user operations cannot be mixed with an execution batch")
    raw = {"action": "tool_calls", "calls": [call.as_action() for action in actions for call in action.calls], **metadata}
    return parse_model_action(json.dumps(raw, ensure_ascii=False, allow_nan=False)).raw, bindings


def response_fields(message, *, final=False):
    """Malformed proposals go through the existing bounded action recovery path."""
    packet = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else deepcopy(message)
    if not packet.get("tool_calls") and not str(packet.get("content") or "").strip():
        return {"content": "", "native_message": packet}
    try:
        action, bindings = decode_native(packet, final=final)
    except InvalidModelAction as exc:
        return {"content": json.dumps({"action": "invalid_native_action", "reason": str(exc)}), "native_message": packet}
    return {"content": json.dumps(action, ensure_ascii=False), "native_message": packet, "native_bindings": bindings}


def request_fields(messages, runtime):
    """Rebuild only retained accepted turns, not an append-only parallel transcript."""
    native = runtime.get("protocol") == "native"
    wire = runtime.get("wire_history") or {}
    observations = runtime.get("observations") or []
    rows, pending = [], None
    for original in messages:
        row = {key: deepcopy(value) for key, value in original.items() if not key.startswith("_")}
        if isinstance(row.get("content"), list):
            for block in row["content"]:
                if isinstance(block, dict):
                    block.pop("_workspace_media", None)
        if row.get("role") == "system" and isinstance(row.get("content"), str) and native:
            row["content"] = row["content"].replace(build_action_protocol_prompt(), build_action_protocol_prompt(native=True))
        step = original.get("_model_step_id")
        if native and step:
            record = wire.get(step)
            if not record or pending is not None:
                raise ValueError("native history is missing its accepted provider packet")
            actual = decode_action_object(row["content"])
            expected, _ = decode_native(record["message"])
            actual.pop("gap_update", None)
            expected.pop("gap_update", None)
            if actual != expected:
                raise ValueError("native history differs from the accepted canonical action")
            # Output-only metadata (annotations, provider trace fields) is not a
            # Chat request parameter; retain it in the checkpoint/audit instead.
            rows.append({key: deepcopy(value) for key, value in record["message"].items()
                         if key in {"role", "content", "reasoning_content", "tool_calls"}})
            pending = (step, record)
            continue
        if pending is not None:
            if row.get("role") != "user" or not isinstance(row.get("content"), list):
                raise ValueError("native action is not followed by Runtime observations")
            facts, remaining = {}, []
            for block in row["content"]:
                try:
                    fact = json.loads(block.get("text", "")) if block.get("type") == "text" else None
                except ValueError:
                    fact = None
                if isinstance(fact, dict) and fact.get("observation_id"):
                    facts[fact["observation_id"]] = fact
                else:
                    remaining.append(block)
            step, record = pending
            used = set()
            for call in record["message"].get("tool_calls") or []:
                bound = record["bindings"].get(call["id"], [])
                selected = [item["observation_id"] for item in observations if item.get("observation_id") in facts
                            and (item.get("tool_call_id") in bound if bound else item.get("model_step_id") == step)]
                if not selected or bound and any(not any(item.get("tool_call_id") == identifier and item.get("observation_id") in selected for item in observations) for identifier in bound):
                    raise ValueError("native call has no matching committed Runtime observation")
                rows.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"observations": [facts[key] for key in selected]}, ensure_ascii=False)})
                used.update(selected)
            remaining.extend({"type": "text", "text": json.dumps(value, ensure_ascii=False)} for key, value in facts.items() if key not in used)
            if remaining:
                rows.append({**row, "content": remaining})
            pending = None
        else:
            rows.append(row)
    if pending is not None:
        raise ValueError("native history has an unanswered proposal")
    result = {"messages": rows}
    if native and runtime.get("purpose") in {"action", "final_response"}:
        result.update(tools=native_functions(), tool_choice="auto")
    return result


class NativeStream:
    """Assemble indexed deltas; no partial function can become an action."""
    def __init__(self):
        self.content, self.reasoning, self.calls = [], [], {}
        self.reasoning_seen = False

    def feed(self, delta):
        self.content.append(getattr(delta, "content", None) or "")
        reasoning = getattr(delta, "reasoning_content", None)
        self.reasoning_seen |= reasoning is not None
        self.reasoning.append(reasoning or "")
        for item in getattr(delta, "tool_calls", None) or []:
            index = item.index
            if type(index) is not int or index < 0:
                raise ValueError("native stream call index is invalid")
            call = self.calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if item.id:
                call["id"] += item.id
            if item.type and item.type != "function":
                raise ValueError("unsupported native stream call type")
            if item.function:
                call["function"]["name"] += item.function.name or ""
                call["function"]["arguments"] += item.function.arguments or ""

    def message(self):
        return {"role": "assistant", "content": "".join(self.content),
                **({"reasoning_content": "".join(self.reasoning)} if self.reasoning_seen else {}),
                **({"tool_calls": [self.calls[key] for key in sorted(self.calls)]} if self.calls else {})}
