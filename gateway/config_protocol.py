from __future__ import annotations

from typing import Any, Dict, Optional


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
        return default
    return bool(value)


def normalize_config_update_params(raw_params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(raw_params or {})

    canonical = params.get("config")
    config_payload = dict(canonical) if isinstance(canonical, dict) else {}

    hot_apply: Optional[bool] = None
    options = params.get("options")
    if isinstance(options, dict) and "hot_apply" in options:
        hot_apply = to_bool(options.get("hot_apply"), default=False)

    validate: Optional[bool] = None
    if params.get("validate") is not None:
        validate = to_bool(params.get("validate"), default=True)

    return {
        "config": config_payload,
        "hot_apply": bool(hot_apply),
        "validate": True if validate is None else validate,
    }
