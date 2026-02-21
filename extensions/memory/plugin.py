from memory.adapter import get_memory_adapter


def register(api):
    """
    Register memory adapter as a core service.
    """
    # Honor plugin enabled flag from loader config (if present)
    enabled = True
    try:
        enabled = bool(api.config.get("enabled", True))
    except Exception:
        enabled = True
    if not enabled:
        return

    adapter = get_memory_adapter()
    api.register_service("memory", adapter)

