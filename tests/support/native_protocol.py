"""Experimental model wire adapter; no tool execution or Agent decisions."""
from copy import deepcopy
import json

from gateway.action.completion import parse_final_answer
from gateway.action.model_action import InvalidModelAction, decode_action_object, parse_model_action
from gateway.runtime_io import CAPABILITY_CONTEXT, ENVIRONMENT_CONTEXT, GOAL_CONTEXT


from gateway.model_protocol import decode_native, native_functions



class NativeTranscript:
    """Lossless provider transcript for the append-only, text-only pilot scope."""
    def __init__(self):
        self.base, self.wire, self.pending, self.bindings, self.observations = [], [], None, {}, []
        self.canonical = None

    async def observe(self, event):
        self.observations.append(dict(event.payload))

    def accept(self, message, canonical=None, bindings=None):
        self.pending = deepcopy(message)
        self.bindings = dict(bindings or {})
        self.canonical = deepcopy(canonical)

    def prepare(self, messages):
        dynamic = [deepcopy(row) for row in messages if row.get("name") in {CAPABILITY_CONTEXT, ENVIRONMENT_CONTEXT, GOAL_CONTEXT}]
        base = [deepcopy(row) for row in messages if row.get("name") not in {CAPABILITY_CONTEXT, ENVIRONMENT_CONTEXT, GOAL_CONTEXT}]
        if base[:len(self.base)] != self.base:
            raise ValueError("pilot native transcript cannot silently rebuild changed canonical history")
        delta = base[len(self.base):]
        if self.pending is None:
            self.wire.extend(delta)
        else:
            self.wire.append(self.pending)
            facts, remaining = {}, []
            for row in delta:
                if row.get("role") == "assistant":
                    expected = dict(self.canonical or {})
                    expected.pop("gap_update", None)
                    if decode_action_object(row["content"]) != expected:
                        raise ValueError("canonical history does not match the native proposal")
                    continue
                if row.get("role") == "user" and isinstance(row.get("content"), list):
                    kept = []
                    for block in row["content"]:
                        try:
                            value = json.loads(block.get("text", "")) if block.get("type") == "text" else None
                        except ValueError:
                            value = None
                        if isinstance(value, dict) and value.get("observation_id"):
                            facts[value["observation_id"]] = value
                        else:
                            kept.append(block)
                    if kept:
                        remaining.append({**row, "content": kept})
                else:
                    remaining.append(row)
            unused = set(facts)
            bound_ids = {identifier for identifiers in self.bindings.values() for identifier in identifiers}
            for call in self.pending.get("tool_calls") or []:
                ids = self.bindings.get(call["id"], [])
                selected = [row["observation_id"] for row in self.observations if row.get("tool_call_id") in ids and row.get("observation_id") in facts]
                if not selected:
                    selected = [row["observation_id"] for row in self.observations if row.get("observation_id") in facts
                                and (not ids or row.get("ok") is False and row.get("tool_call_id") not in bound_ids)]
                if not selected:
                    raise ValueError("native call has no committed Runtime observation")
                self.wire.append({"role": "tool", "tool_call_id": call["id"],
                                  "content": json.dumps({"observations": [facts[key] for key in selected]}, ensure_ascii=False)})
                unused.difference_update(selected)
            if unused:
                remaining.append({"role": "user", "content": [{"type": "text", "text": json.dumps(facts[key], ensure_ascii=False)} for key in sorted(unused)]})
            self.wire.extend(remaining)
        self.base, self.pending, self.observations = base, None, []
        return deepcopy(self.wire) + dynamic
