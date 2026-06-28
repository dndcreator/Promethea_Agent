from types import SimpleNamespace

from config import ColdLayerConfig
from gateway.memory_service import MemoryService
from memory.cold_layer import ColdLayerManager
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


def test_memory_service_use_main_api_string_false_uses_dedicated(tmp_path, monkeypatch):
    from gateway import user_secrets

    class _CfgService:
        @staticmethod
        def get_merged_config(user_id):
            return {
                "api": {},
                "memory": {
                    "api": {
                        "use_main_api": "false",
                    }
                },
            }

    class _Adapter:
        @staticmethod
        def is_enabled():
            return False

    monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", tmp_path / "users")
    user_secrets.update_user_secrets(
        "u1",
        {
            "API__API_KEY": "main-key",
            "API__BASE_URL": "https://main.example/v1",
            "API__MODEL": "main-model",
            "MEMORY__API__USE_MAIN_API": "false",
            "MEMORY__API__API_KEY": "mem-key",
            "MEMORY__API__BASE_URL": "https://mem.example/v1",
            "MEMORY__API__MODEL": "mem-model",
        },
    )

    service = MemoryService(memory_adapter=_Adapter(), config_service=_CfgService())
    api = service._resolve_memory_api_for_user("u1")
    assert api["api_key"] == "mem-key"
    assert api["base_url"] == "https://mem.example/v1"
    assert api["model"] == "mem-model"


def test_cold_layer_default_summary_model_follows_main_api():
    cfg = SimpleNamespace(
        api=SimpleNamespace(
            api_key="main-key",
            base_url="https://main.example/v1",
            model="main-model",
        ),
        memory=SimpleNamespace(
            api=SimpleNamespace(use_main_api=True),
            cold_layer=ColdLayerConfig(),
        ),
    )

    manager = ColdLayerManager(connector=object(), config=cfg)

    assert manager.summary_model == "main-model"


def test_cold_layer_explicit_summary_model_overrides_main_api():
    cfg = SimpleNamespace(
        api=SimpleNamespace(
            api_key="main-key",
            base_url="https://main.example/v1",
            model="main-model",
        ),
        memory=SimpleNamespace(
            api=SimpleNamespace(use_main_api=True),
            cold_layer=ColdLayerConfig(summary_model="summary-model"),
        ),
    )

    manager = ColdLayerManager(connector=object(), config=cfg)

    assert manager.summary_model == "summary-model"