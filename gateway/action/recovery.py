"""Bounded model-output recovery policy; execution remains in ActionService."""
from __future__ import annotations


def recover(state: dict, *, code: str, signature: str, initial: int, ceiling: int, retries: int) -> tuple[bool, str]:
    family = "output_limit" if code == "MODEL_OUTPUT_LIMIT" else "empty_response" if code == "MODEL_EMPTY_RESPONSE" else "protocol"
    counter = state.setdefault("families", {}).setdefault(family, {})
    previous_error = counter.get("last_error")
    repeated = previous_error == code and counter.get("signature") == signature
    counter["failures"] = int(counter.get("failures", 0)) + 1
    counter.update(last_error=code, signature=signature)
    if counter["failures"] > retries:
        return False, f"Model {family} recovery limit reached; committed work is retained."
    if code == "MODEL_OUTPUT_LIMIT":
        current = min(ceiling, int(state.get("output_tokens") or initial))
        if current < ceiling:
            state["output_tokens"] = min(ceiling, current * 2)
            return True, f"No partial action executed. The next output allowance is {state['output_tokens']} tokens. Split large file/code work into bounded writes rather than repeating a monolithic action."
        if previous_error == code:
            return False, "Output still truncates at the configured ceiling; stop repeating the same generation."
        return True, "No partial action executed. The output ceiling cannot increase; use a smaller complete action and split file/code work into bounded writes."
    if repeated:
        return False, "The same invalid model output repeated after correction; stop ineffective recovery."
    if code == "MULTIPLE_ACTIONS":
        return True, "No proposed action executed. Return exactly one top-level action object. Use the canonical tool_calls calls array for a batch; never concatenate objects."
    if code == "JSON_ENVELOPE_INVALID":
        return True, "No proposed action executed. Return one complete JSON object without surrounding prose. A single complete JSON fence is accepted; incomplete JSON is never repaired."
    if code == "DUPLICATE_ACTION_FIELD":
        return True, "No proposed action executed. Each JSON object must have unique field names, including nested tool arguments."
    return True, "No proposed action executed. Return one complete canonical JSON action with valid schema and evidence references."


def reset_failures(state: dict) -> None:
    for key in ("families", "failures", "last_error", "signature"):
        state.pop(key, None)
