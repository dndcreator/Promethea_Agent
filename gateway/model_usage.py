"""Provider-neutral usage arithmetic; missing cache usage is not a zero hit count."""


def cached_tokens(usage):
    if not isinstance(usage, dict):
        return None
    value = usage.get("prompt_cache_hit_tokens")
    if value is None:
        details = usage.get("prompt_tokens_details") or {}
        value = details.get("cached_tokens") if isinstance(details, dict) else None
    prompt = usage.get("prompt_tokens")
    return value if type(value) is int and type(prompt) is int and 0 <= value <= prompt else None


def merge_usage(total, usage):
    if not isinstance(usage, dict):
        total.update(usage_complete=False, cache_usage_complete=False, prompt_cache_hit_tokens=None)
        return
    cache = cached_tokens(usage)
    known = total.get("cache_usage_complete", True) and cache is not None and usage.get("cache_usage_complete", True)
    previous_cache = total.get("prompt_cache_hit_tokens") or 0
    complete = total.get("usage_complete", True) and usage.get("usage_complete", True)
    for key in ("prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        valid = type(value) is int and value >= 0
        complete = complete and valid
        total[key] = int(total.get(key) or 0) + (value if valid else 0)
    total["usage_complete"] = complete
    total["cache_usage_complete"] = known
    total["prompt_cache_hit_tokens"] = previous_cache + cache if known else None
