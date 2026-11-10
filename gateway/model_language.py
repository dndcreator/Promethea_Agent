"""Shared response-language instructions, separate from execution policy."""
import json


LANGUAGE_POLICY = (
    "Language policy:\n"
    "- Default to the same language as the user's original request, not the language of internal task wrappers or tool observations.\n"
    "- If the user explicitly asks for a different language, follow that language.\n"
    "- Use that language for readable reasoning, step titles, summaries and the final answer.\n"
    "- If the request has no clear language, use the UI language supplied by Runtime metadata.\n"
    "- Preserve protocol keys, enum values, identifiers, URLs and file paths exactly."
)


def response_language_context(user_message, run_context=None):
    payload = run_context.get("input_payload", {}) if isinstance(run_context, dict) else getattr(run_context, "input_payload", {})
    payload = payload if isinstance(payload, dict) else {}
    metadata = payload.get("metadata") or {}
    language = metadata.get("ui_language") if isinstance(metadata, dict) else None
    return {"original_request": str(payload.get("message") or user_message),
            "ui_language": language if language in {"zh", "en"} else None}


def with_response_language(messages, context=None):
    result = [dict(message) for message in messages]
    if not any(message.get("role") == "system" and LANGUAGE_POLICY in str(message.get("content") or "") for message in result):
        result.insert(0, {"role": "system", "content": LANGUAGE_POLICY})
    if context:
        result = [message for message in result if message.get("name") != "promethea_response_language"]
        result.append({"role": "user", "name": "promethea_response_language", "content": json.dumps(context, ensure_ascii=False)})
    return result
