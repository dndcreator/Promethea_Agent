from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .models import RunContext, SessionState


def resolve_request_user_id(connection: Any, request: Any) -> str:
    identity = getattr(connection, "identity", None)
    device_id = getattr(identity, "device_id", None) if identity else None
    if device_id:
        return str(device_id)
    user_id = request.params.get("user_id") if isinstance(request.params, dict) else None
    if user_id:
        return str(user_id)
    return "default_user"


def resolve_request_trace_id(request: Any) -> str:
    params = request.params if isinstance(request.params, dict) else {}
    return str(params.get("trace_id") or f"trace_{request.id}")


def build_run_context(
    *,
    request: Any,
    session_id: str,
    user_id: str,
    channel_id: str,
    input_payload: Optional[Dict[str, Any]] = None,
) -> RunContext:
    params = dict(input_payload or request.params or {})
    trace_id = str(params.get("trace_id") or f"trace_{request.id}")
    requested_mode = params.get("requested_mode")
    requested_skill = params.get("requested_skill")
    tenant_id = str(params.get("tenant_id") or "").strip() or None
    environment = str(params.get("environment") or params.get("env") or "").strip() or None

    session_state = SessionState(
        session_id=str(session_id),
        user_id=str(user_id),
        tenant_id=tenant_id,
        environment=environment,
        channel_id=str(channel_id),
        reasoning_mode=str(requested_mode) if requested_mode else None,
        active_skill_id=str(requested_skill) if requested_skill else None,
        trace_id=trace_id,
        session_metadata={
            "request_id": request.id,
            "channel_id": channel_id,
        },
    )

    return RunContext(
        request_id=request.id,
        trace_id=trace_id,
        session_state=session_state,
        user_identity={"user_id": str(user_id), "tenant_id": tenant_id, "environment": environment},
        input_payload=params,
        normalized_input={
            "text": str(params.get("message") or params.get("query") or ""),
            "attachments": params.get("attachments") or [],
            "metadata": params.get("metadata") or {},
        },
        requested_mode=str(requested_mode) if requested_mode else None,
        requested_skill=str(requested_skill) if requested_skill else None,
        debug_flags=params.get("debug_flags") or {},
    )


def resolve_tool_identity(entry_tool_name: str, params: Dict[str, Any]) -> Tuple[str, str]:
    explicit_service = params.get("service_name")
    explicit_tool = params.get("tool_name") or params.get("command")
    if explicit_service or explicit_tool:
        service_name = str(explicit_service or entry_tool_name)
        tool_name = str(explicit_tool or entry_tool_name)
        return service_name, tool_name

    if "." in str(entry_tool_name):
        service_name, tool_name = str(entry_tool_name).split(".", 1)
        return service_name, tool_name

    service_name = str(entry_tool_name)
    tool_name = str(entry_tool_name)
    return service_name, tool_name


def resolve_provider_id(user_config: Optional[Dict[str, Any]]) -> str:
    if not isinstance(user_config, dict):
        return "default"
    api_cfg = user_config.get("api")
    if not isinstance(api_cfg, dict):
        return "default"
    model = str(api_cfg.get("model") or "").strip().lower()
    base_url = str(api_cfg.get("base_url") or "").strip().lower()
    if model and "/" in model:
        return model.split("/", 1)[0]
    if "openrouter" in base_url:
        return "openrouter"
    if "openai" in base_url:
        return "openai"
    return "default"
