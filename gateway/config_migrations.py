from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List, Tuple

CURRENT_CONFIG_VERSION = "1"


MigrationFn = Callable[[Dict[str, Any]], Tuple[Dict[str, Any], List[str]]]


def _deep_get(data: Dict[str, Any], path: List[str]) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _deep_set(data: Dict[str, Any], path: List[str], value: Any) -> None:
    cur = data
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def _normalize_version(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "0"
    if text.startswith("v"):
        text = text[1:]
    if text.count(".") >= 1:
        return text.split(".", 1)[0]
    return text


def detect_config_version(config: Dict[str, Any]) -> str:
    if not isinstance(config, dict):
        return "0"
    direct = config.get("config_version")
    if direct is not None:
        return _normalize_version(direct)
    # Treat missing config_version as v0. system.version is legacy metadata
    # and should not short-circuit schema migration.
    return "0"


def _migrate_v0_to_v1(config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    out = deepcopy(config) if isinstance(config, dict) else {}
    warnings: List[str] = []

    if _deep_get(out, ["system", "version"]) is not None:
        warnings.append("deprecated field: system.version (use config_version)")

    out["config_version"] = CURRENT_CONFIG_VERSION

    # Initialize boundary sections without breaking legacy keys.
    runtime_defaults = {
        "default_mode": str(_deep_get(out, ["reasoning", "mode"]) or "fast"),
        "stream_mode": bool(_deep_get(out, ["system", "stream_mode"]) if _deep_get(out, ["system", "stream_mode"]) is not None else True),
    }
    user_preferences = out.get("user_preferences") if isinstance(out.get("user_preferences"), dict) else {}
    user_preferences.setdefault("default_mode", runtime_defaults["default_mode"])
    user_preferences.setdefault("preferred_skills", [])
    user_preferences.setdefault("prompt_toggles", {})
    user_preferences.setdefault("tool_visibility", {})
    out["user_preferences"] = user_preferences

    runtime_config = out.get("runtime_config") if isinstance(out.get("runtime_config"), dict) else {}
    runtime_config.setdefault("api", deepcopy(out.get("api") or {}))
    runtime_config.setdefault("memory", deepcopy(out.get("memory") or {}))
    runtime_config.setdefault("reasoning", deepcopy(out.get("reasoning") or {}))
    runtime_config.setdefault("system", deepcopy(out.get("system") or {}))
    runtime_config.setdefault("defaults", runtime_defaults)
    out["runtime_config"] = runtime_config

    security_config = out.get("security_config") if isinstance(out.get("security_config"), dict) else {}
    security_config.setdefault("sandbox", deepcopy(out.get("sandbox") or {}))
    out["security_config"] = security_config

    channel_config = out.get("channel_config")
    if not isinstance(channel_config, dict):
        out["channel_config"] = {}

    return out, warnings


_MIGRATIONS: Dict[str, Tuple[str, MigrationFn]] = {
    "0": ("1", _migrate_v0_to_v1),
}


def migrate_config(config: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    current = deepcopy(config) if isinstance(config, dict) else {}
    start = detect_config_version(current)
    warnings: List[str] = []
    steps: List[str] = []

    version = start
    guard = 0
    while version in _MIGRATIONS:
        guard += 1
        if guard > 10:
            warnings.append("migration aborted: too many steps")
            break
        next_version, fn = _MIGRATIONS[version]
        current, w = fn(current)
        warnings.extend(w)
        steps.append(f"{version}->{next_version}")
        version = next_version

    if detect_config_version(current) != CURRENT_CONFIG_VERSION:
        current["config_version"] = CURRENT_CONFIG_VERSION
        if not steps:
            steps.append(f"{start}->{CURRENT_CONFIG_VERSION}")

    report = {
        "from_version": start,
        "to_version": str(current.get("config_version") or CURRENT_CONFIG_VERSION),
        "applied_steps": steps,
        "warnings": warnings,
    }
    return current, report


def collect_deprecation_warnings(config: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    if not isinstance(config, dict):
        return warnings

    if _deep_get(config, ["system", "version"]) is not None:
        warnings.append("deprecated field in use: system.version")

    # Legacy direct prompt fields are still accepted but considered preference-level.
    if "system_prompt" in config:
        warnings.append("legacy preference field: system_prompt (prefer user_preferences.prompt_toggles/profile)")

    return warnings
