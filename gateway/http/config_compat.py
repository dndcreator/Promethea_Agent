from __future__ import annotations

from typing import Any, Dict

from .schemas import UserConfigUpdate


def build_user_config_payload(req: UserConfigUpdate) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if req.agent_name is not None:
        payload["agent_name"] = req.agent_name
    if req.system_prompt is not None:
        payload["system_prompt"] = req.system_prompt
    if req.api is not None:
        api_payload: Dict[str, Any] = {}
        for field_name in ("api_key", "base_url", "model", "temperature", "max_tokens"):
            value = getattr(req.api, field_name, None)
            if value is not None:
                api_payload[field_name] = value
        if api_payload:
            payload["api"] = api_payload
    return payload
