from types import SimpleNamespace
from unittest.mock import MagicMock
import threading

import pytest


def test_hot_layer_factory_uses_extractor_factory(monkeypatch):
    import memory as memory_pkg

    cfg = SimpleNamespace(
        memory=SimpleNamespace(
            enabled=True,
            neo4j=SimpleNamespace(enabled=True),
        )
    )
    connector = object()
    extractor = object()
    hot_layer = object()

    monkeypatch.setattr(memory_pkg, "load_config", lambda: cfg)
    monkeypatch.setattr(
        memory_pkg.Neo4jConnectionPool,
        "get_connector",
        lambda neo4j_cfg: connector,
    )
    monkeypatch.setattr(
        memory_pkg,
        "create_extractor_from_config",
        lambda config: extractor,
    )
    monkeypatch.setattr(
        memory_pkg,
        "HotLayerManager",
        lambda ext, conn, session_id, user_id: (
            hot_layer
            if (ext is extractor and conn is connector and session_id == "s1" and user_id == "u1")
            else None
        ),
    )

    assert memory_pkg.create_hot_layer_manager("s1", "u1") is hot_layer


def test_should_write_candidate_has_no_side_effect(monkeypatch):
    from gateway.memory_service import MemoryService

    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = False
    svc = MemoryService(memory_adapter=memory_adapter)

    monkeypatch.setattr(svc, "_refresh_thresholds", lambda user_id=None: None)
    svc._dedupe_min_candidate_chars = 1

    assert svc._should_write_candidate("u1", "goal", "abc")
    key = svc._make_write_key("u1", "goal", "abc")
    assert key not in svc._recent_write_index
    assert svc._recent_write_keys == []


@pytest.mark.asyncio
async def test_interaction_completed_remembers_write_key_only_after_success(monkeypatch):
    from gateway.memory_service import MemoryService

    async def _fake_classify(*args, **kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "goal",
                    "content": "remember this long-term state",
                    "semantic_keys": ["remember"],
                }
            ],
        }

    event = SimpleNamespace(
        payload={
            "session_id": "s1",
            "user_id": "u1",
            "channel": "web",
            "user_input": "I want to build this feature next month.",
            "assistant_output": "Noted.",
        }
    )

    for add_ok, expected in [(True, True), (False, False)]:
        memory_adapter = MagicMock()
        memory_adapter.is_enabled.return_value = True
        memory_adapter.add_message.return_value = add_ok
        svc = MemoryService(memory_adapter=memory_adapter)

        monkeypatch.setattr(svc, "_classify_interaction", _fake_classify)
        monkeypatch.setattr(
            svc,
            "_graph_memory_state_changed",
            lambda **kwargs: True,
        )

        await svc._on_interaction_completed(event)

        key = svc._make_write_key("u1", "goal", "remember this long-term state")
        assert (key in svc._recent_write_index) is expected


@pytest.mark.asyncio
async def test_interaction_completed_passes_memory_metadata(monkeypatch):
    from gateway.memory_service import MemoryService

    async def _fake_classify(*args, **kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "preference",
                    "content": "I prefer concise answers.",
                    "semantic_keys": ["prefer", "concise"],
                }
            ],
        }

    event = SimpleNamespace(
        payload={
            "session_id": "s1",
            "user_id": "u1",
            "channel": "web",
            "user_input": "please keep answers short",
            "assistant_output": "ok",
        }
    )

    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.add_message.return_value = True
    svc = MemoryService(memory_adapter=memory_adapter)

    monkeypatch.setattr(svc, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(svc, "_graph_memory_state_changed", lambda **kwargs: True)

    await svc._on_interaction_completed(event)

    kwargs = memory_adapter.add_message.call_args.kwargs
    assert kwargs["metadata"]["memory_type"] == "preference"
    assert kwargs["metadata"]["semantic_keys"] == ["prefer", "concise"]
    assert kwargs["metadata"]["memory_source"] == "interaction.completed"


def test_on_message_saved_queues_maintenance_once(monkeypatch):
    import memory.adapter as adapter_module
    from memory.adapter import MemoryAdapter

    spawn_count = {"count": 0}

    class _FakeThread:
        def __init__(self, target=None, args=None, daemon=None):
            self.target = target
            self.args = args or ()
            self.daemon = daemon

        def start(self):
            spawn_count["count"] += 1

    monkeypatch.setattr(adapter_module.threading, "Thread", _FakeThread)

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled = True
    adapter.hot_layer = object()
    adapter._config = None
    adapter._warm_layer = None
    adapter._cold_layer = None
    adapter._forgetting = None
    adapter._maintenance_lock = threading.Lock()
    adapter._idle_timer_lock = threading.Lock()
    adapter._idle_timers = {}
    adapter._maintenance_state = {}
    adapter._maintenance_persist_keys = (
        "messages",
        "messages_since_cluster",
        "last_message_at",
        "last_cluster_at",
        "last_summary_at",
        "last_decay_at",
    )
    adapter._maintenance_defaults = {
        "cluster_every_messages": 12,
        "cluster_min_interval_s": 300,
        "idle_cluster_delay_s": 120,
        "idle_cluster_min_messages": 2,
        "idle_cluster_min_interval_s": 60,
        "summary_min_interval_s": 600,
        "decay_interval_s": 24 * 3600,
    }
    adapter._ensure_managers = lambda: None
    adapter._schedule_idle_cluster_check = lambda session_id: None

    adapter.on_message_saved("s1", "user", "u1")
    adapter.on_message_saved("s1", "user", "u1")

    assert spawn_count["count"] == 1


def test_idle_cluster_uses_idle_thresholds():
    from memory.adapter import MemoryAdapter

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter._maintenance_lock = threading.Lock()
    adapter._maintenance_defaults = {
        "cluster_every_messages": 12,
        "cluster_min_interval_s": 300,
        "idle_cluster_delay_s": 120,
        "idle_cluster_min_messages": 2,
        "idle_cluster_min_interval_s": 60,
        "summary_min_interval_s": 600,
        "decay_interval_s": 24 * 3600,
    }
    adapter._maintenance_persist_keys = (
        "messages",
        "messages_since_cluster",
        "last_message_at",
        "last_cluster_at",
        "last_summary_at",
        "last_decay_at",
    )
    adapter._config = SimpleNamespace(
        memory=SimpleNamespace(
            warm_layer=SimpleNamespace(enabled=True, min_cluster_size=3)
        )
    )
    adapter._warm_layer = MagicMock()
    adapter._warm_layer.cluster_entities.return_value = 1

    state = {
        "messages_since_cluster": 3,
        "last_cluster_at": 0.0,
        "cluster_running": False,
    }
    adapter._maybe_cluster("s1", state, now=1000.0, force_on_idle=True)

    adapter._warm_layer.cluster_entities.assert_called_once_with("s1")
