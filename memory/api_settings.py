from __future__ import annotations

from typing import Dict, Any, Optional


def resolve_memory_api(config, model_fallback: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolve API settings used by memory subsystem.

    Priority:
    1) memory.api when use_main_api is false
    2) global api config
    """
    memory_api = getattr(config.memory, "api", None)
    use_main = True if memory_api is None else bool(getattr(memory_api, "use_main_api", True))

    if use_main:
        api_key = config.api.api_key
        base_url = config.api.base_url
        model = model_fallback or config.api.model
        return {"api_key": api_key, "base_url": base_url, "model": model}

    api_key = getattr(memory_api, "api_key", "") or config.api.api_key
    base_url = getattr(memory_api, "base_url", "") or config.api.base_url
    model = (
        getattr(memory_api, "model", "") or model_fallback or config.api.model
    )
    return {"api_key": api_key, "base_url": base_url, "model": model}
