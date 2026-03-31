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


def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def normalize_config_update_params(raw_params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(raw_params or {})

    config_payload: Dict[str, Any] = {}
    legacy = params.get("config_data")
    canonical = params.get("config")
    compat_updates = params.get("updates")
    if isinstance(legacy, dict):
        config_payload = _deep_merge(config_payload, dict(legacy))
    if isinstance(canonical, dict):
        config_payload = _deep_merge(config_payload, dict(canonical))
    if isinstance(compat_updates, dict):
        config_payload = _deep_merge(config_payload, dict(compat_updates))

    hot_apply: Optional[bool] = None
    options = params.get("options")
    if isinstance(options, dict) and "hot_apply" in options:
        hot_apply = to_bool(options.get("hot_apply"), default=False)
    if hot_apply is None and params.get("hot_apply") is not None:
        hot_apply = to_bool(params.get("hot_apply"), default=False)
    if hot_apply is None and "hot_reload" in params:
        hot_apply = to_bool(params.get("hot_reload"), default=False)

    validate: Optional[bool] = None
    if params.get("validate") is not None:
        validate = to_bool(params.get("validate"), default=True)
    elif params.get("validate_config") is not None:
        validate = to_bool(params.get("validate_config"), default=True)

    return {
        "config": config_payload,
        "hot_apply": bool(hot_apply),
        "validate": True if validate is None else validate,
    }
