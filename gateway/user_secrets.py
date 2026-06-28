from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import dotenv_values

from config import ENV_FILE, PROJECT_ROOT

USER_SECRETS_FILENAME = "secrets.env"
USER_SECRETS_DIR = PROJECT_ROOT / "config" / "users"

SENSITIVE_ENV_KEYS: tuple[str, ...] = (
    "API__API_KEY",
    "API__BASE_URL",
    "API__MODEL",
    "API__FAILOVER_MODELS",
    "MEMORY__ENABLED",
    "MEMORY__STORE_BACKEND",
    "MEMORY__SQLITE_GRAPH_PATH",
    "MEMORY__FLAT_MEMORY_PATH",
    "MEMORY__API__USE_MAIN_API",
    "MEMORY__API__API_KEY",
    "MEMORY__API__BASE_URL",
    "MEMORY__API__MODEL",
    "MEMORY__NEO4J__ENABLED",
    "MEMORY__NEO4J__URI",
    "MEMORY__NEO4J__USERNAME",
    "MEMORY__NEO4J__PASSWORD",
    "MEMORY__NEO4J__DATABASE",
    "SEARCH__PROVIDER",
    "SEARCH__BRAVE_API_KEY",
    "SEARCH__TAVILY_API_KEY",
    "SEARCH__SERPAPI_API_KEY",
    "SEARCH__SEARXNG_URL",
)


def _safe_user_segment(user_id: str) -> str:
    raw = str(user_id or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in raw)
    return safe[:128] or "default_user"


def user_secrets_path(user_id: str) -> Path:
    return USER_SECRETS_DIR / _safe_user_segment(user_id) / USER_SECRETS_FILENAME


def _read_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data = dotenv_values(str(path))
    return {str(k): str(v or "") for k, v in data.items() if k}


def _default_secret_values() -> Dict[str, str]:
    values = {key: "" for key in SENSITIVE_ENV_KEYS}
    root_env = _read_env_file(ENV_FILE)
    for key in values:
        if key in root_env:
            values[key] = root_env[key]
        elif key in os.environ:
            values[key] = str(os.environ.get(key) or "")
    return values


def _quote_env_value(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(ch.isspace() for ch in text) or any(ch in text for ch in ['"', "'", "#"]):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _write_env_atomic(path: Path, values: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".secrets.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# User-scoped Promethea runtime secrets.\n")
            f.write("# This file is generated locally and must never be committed.\n")
            f.write("# Empty values fall back to the global .env/default runtime config.\n\n")
            for key in SENSITIVE_ENV_KEYS:
                f.write(f"{key}={_quote_env_value(values.get(key, ''))}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise


def ensure_user_secrets(user_id: str) -> Path:
    path = user_secrets_path(user_id)
    if not path.exists():
        _write_env_atomic(path, _default_secret_values())
    return path


def load_user_secrets(user_id: str, *, ensure: bool = True) -> Dict[str, str]:
    if ensure:
        ensure_user_secrets(user_id)
    values = _read_env_file(user_secrets_path(user_id))
    return {key: str(values.get(key) or "") for key in SENSITIVE_ENV_KEYS}


def update_user_secrets(user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    current = load_user_secrets(user_id, ensure=True)
    for key, value in (updates or {}).items():
        normalized = str(key or "").strip().upper()
        text = str(value or "")
        # Empty form fields mean "keep existing value"; do not wipe configured secrets.
        if normalized in SENSITIVE_ENV_KEYS and text.strip():
            current[normalized] = text
    _write_env_atomic(user_secrets_path(user_id), current)
    return get_user_secrets_status(user_id)


def _resolve_value(user_values: Dict[str, str], key: str) -> str:
    user_value = str(user_values.get(key) or "").strip()
    if user_value:
        return user_value
    root_env = _read_env_file(ENV_FILE)
    root_value = str(root_env.get(key) or "").strip()
    if root_value:
        return root_value
    return str(os.environ.get(key) or "").strip()


def _parse_failover_models(raw: str) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def resolve_llm_runtime_settings(
    user_id: Optional[str],
    *,
    behavior_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from config import config

    values = load_user_secrets(user_id, ensure=True) if user_id else {}
    behavior_api = (behavior_config or {}).get("api") if isinstance(behavior_config, dict) else {}
    behavior_api = behavior_api if isinstance(behavior_api, dict) else {}
    api_defaults = getattr(config, "api", None)
    return {
        "api_key": _resolve_value(values, "API__API_KEY") or getattr(api_defaults, "api_key", ""),
        "base_url": _resolve_value(values, "API__BASE_URL") or getattr(api_defaults, "base_url", ""),
        "model": _resolve_value(values, "API__MODEL") or getattr(api_defaults, "model", ""),
        "failover_models": _parse_failover_models(_resolve_value(values, "API__FAILOVER_MODELS")),
        "temperature": behavior_api.get("temperature", getattr(api_defaults, "temperature", 0.7)),
        "max_tokens": behavior_api.get("max_tokens", getattr(api_defaults, "max_tokens", 2000)),
    }


def resolve_memory_runtime_settings(
    user_id: Optional[str],
    *,
    behavior_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from config import config

    values = load_user_secrets(user_id, ensure=True) if user_id else {}
    behavior_memory = (behavior_config or {}).get("memory") if isinstance(behavior_config, dict) else {}
    behavior_memory = behavior_memory if isinstance(behavior_memory, dict) else {}
    behavior_memory_api = behavior_memory.get("api") if isinstance(behavior_memory.get("api"), dict) else {}
    use_main_api = str(_resolve_value(values, "MEMORY__API__USE_MAIN_API") or "").strip().lower()
    if use_main_api:
        use_main = use_main_api not in {"0", "false", "no", "off"}
    else:
        memory_defaults = getattr(config, "memory", None)
        memory_api_defaults = getattr(memory_defaults, "api", None)
        use_main = bool(behavior_memory_api.get("use_main_api", getattr(memory_api_defaults, "use_main_api", True)))

    main_api = resolve_llm_runtime_settings(user_id, behavior_config=behavior_config)
    if use_main:
        return {
            "api_key": main_api.get("api_key", ""),
            "base_url": main_api.get("base_url", ""),
            "model": main_api.get("model", ""),
        }

    return {
        "api_key": _resolve_value(values, "MEMORY__API__API_KEY") or main_api.get("api_key", ""),
        "base_url": _resolve_value(values, "MEMORY__API__BASE_URL") or main_api.get("base_url", ""),
        "model": _resolve_value(values, "MEMORY__API__MODEL") or main_api.get("model", ""),
    }


def resolve_search_runtime_settings(user_id: Optional[str]) -> Dict[str, str]:
    values = load_user_secrets(user_id, ensure=True) if user_id else {}
    provider = (_resolve_value(values, "SEARCH__PROVIDER") or "auto").strip().lower()
    return {
        "provider": provider or "auto",
        "brave_api_key": _resolve_value(values, "SEARCH__BRAVE_API_KEY"),
        "tavily_api_key": _resolve_value(values, "SEARCH__TAVILY_API_KEY"),
        "serpapi_api_key": _resolve_value(values, "SEARCH__SERPAPI_API_KEY"),
        "searxng_url": _resolve_value(values, "SEARCH__SEARXNG_URL"),
    }


def get_user_secrets_status(user_id: str) -> Dict[str, Any]:
    path = ensure_user_secrets(user_id)
    values = load_user_secrets(user_id, ensure=False)
    api_key = str(values.get("API__API_KEY") or "").strip()
    base_url = str(values.get("API__BASE_URL") or "").strip()
    model = str(values.get("API__MODEL") or "").strip()
    memory_api_key = str(values.get("MEMORY__API__API_KEY") or "").strip()
    neo4j_password = str(values.get("MEMORY__NEO4J__PASSWORD") or "").strip()
    search_provider = str(values.get("SEARCH__PROVIDER") or "auto").strip() or "auto"
    brave_api_key = str(values.get("SEARCH__BRAVE_API_KEY") or "").strip()
    tavily_api_key = str(values.get("SEARCH__TAVILY_API_KEY") or "").strip()
    serpapi_api_key = str(values.get("SEARCH__SERPAPI_API_KEY") or "").strip()
    searxng_url = str(values.get("SEARCH__SEARXNG_URL") or "").strip()
    return {
        "path": str(path),
        "exists": path.exists(),
        "api": {
            "api_key_configured": bool(api_key and api_key != "placeholder-key-not-set"),
            "base_url_configured": bool(base_url),
            "model_configured": bool(model),
            "base_url": base_url,
            "model": model,
        },
        "memory": {
            "api_key_configured": bool(memory_api_key),
            "neo4j_password_configured": bool(neo4j_password),
        },
        "search": {
            "provider": search_provider,
            "brave_configured": bool(brave_api_key),
            "tavily_configured": bool(tavily_api_key),
            "serpapi_configured": bool(serpapi_api_key),
            "searxng_configured": bool(searxng_url),
            "searxng_url": searxng_url,
        },
    }
