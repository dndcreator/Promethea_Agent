from types import SimpleNamespace

from memory.api_settings import resolve_memory_api


def _make_config(use_main_api=True, memory_api_key="", memory_base_url="", memory_model=""):
    return SimpleNamespace(
        api=SimpleNamespace(
            api_key="main-key",
            base_url="https://main.example/v1",
            model="main-model",
        ),
        memory=SimpleNamespace(
            api=SimpleNamespace(
                use_main_api=use_main_api,
                api_key=memory_api_key,
                base_url=memory_base_url,
                model=memory_model,
            )
        ),
    )


def test_resolve_memory_api_use_main():
    cfg = _make_config(use_main_api=True)
    api = resolve_memory_api(cfg)
    assert api["api_key"] == "main-key"
    assert api["base_url"] == "https://main.example/v1"
    assert api["model"] == "main-model"


def test_resolve_memory_api_dedicated():
    cfg = _make_config(
        use_main_api=False,
        memory_api_key="mem-key",
        memory_base_url="https://mem.example/v1",
        memory_model="mem-model",
    )
    api = resolve_memory_api(cfg)
    assert api["api_key"] == "mem-key"
    assert api["base_url"] == "https://mem.example/v1"
    assert api["model"] == "mem-model"


def test_resolve_memory_api_dedicated_fallback():
    cfg = _make_config(
        use_main_api=False,
        memory_api_key="",
        memory_base_url="",
        memory_model="",
    )
    api = resolve_memory_api(cfg)
    assert api["api_key"] == "main-key"
    assert api["base_url"] == "https://main.example/v1"
    assert api["model"] == "main-model"
