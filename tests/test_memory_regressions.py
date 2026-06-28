from types import SimpleNamespace
from unittest.mock import MagicMock
import threading
import json
import os

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
        lambda config, user_id=None: extractor if user_id == "u1" else None,
    )
    monkeypatch.setattr(
        memory_pkg,
        "HotLayerManager",
        lambda ext, conn, session_id, user_id, config=None: (
            hot_layer
            if (ext is extractor and conn is connector and session_id == "s1" and user_id == "u1" and config is cfg)
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
        async def _passthrough_verify(**kwargs):
            return kwargs.get("candidates", [])
        monkeypatch.setattr(svc, "_verify_candidates_with_llm", _passthrough_verify)
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
    async def _passthrough_verify(**kwargs):
        return kwargs.get("candidates", [])
    monkeypatch.setattr(svc, "_verify_candidates_with_llm", _passthrough_verify)
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

@pytest.mark.asyncio
async def test_interaction_completed_rejects_assistant_attributed_candidate(monkeypatch):
    from gateway.memory_service import MemoryService

    async def _fake_classify(*args, **kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "preference",
                    "content": "user does not like calculator tools",
                    "semantic_keys": ["calculator", "preference"],
                }
            ],
        }

    async def _fake_verify_call(*args, **kwargs):
        return (
            '{"decisions":[{"index":0,"accept":true,"confidence":0.91,'
            '"reason":"derived mainly from assistant explanation",'
            '"evidence":"assistant said no tool needed",'
            '"attribution":"assistant"}]}'
        )

    event = SimpleNamespace(
        payload={
            "session_id": "s1",
            "user_id": "u1",
            "channel": "web",
            "user_input": "帮我算一下 12*13",
            "assistant_output": "这个我不用工具也能算",
        }
    )

    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.add_message.return_value = True
    svc = MemoryService(memory_adapter=memory_adapter)

    monkeypatch.setattr(svc, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(svc, "_call_memory_classifier_llm", _fake_verify_call)
    monkeypatch.setattr(svc, "_graph_memory_state_changed", lambda **kwargs: True)

    await svc._on_interaction_completed(event)

    memory_adapter.add_message.assert_not_called()


@pytest.mark.asyncio
async def test_interaction_completed_persists_verifier_metadata(monkeypatch):
    from gateway.memory_service import MemoryService

    async def _fake_classify(*args, **kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "preference",
                    "content": "prefer concise answers",
                    "semantic_keys": ["prefer", "concise"],
                }
            ],
        }

    async def _fake_verify_call(*args, **kwargs):
        return (
            '{"decisions":[{"index":0,"accept":true,"confidence":0.88,'
            '"reason":"explicit user preference",'
            '"evidence":"please keep it concise",'
            '"attribution":"user"}]}'
        )

    event = SimpleNamespace(
        payload={
            "session_id": "s1",
            "user_id": "u1",
            "channel": "web",
            "user_input": "please keep it concise",
            "assistant_output": "ok",
        }
    )

    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.add_message.return_value = True
    svc = MemoryService(memory_adapter=memory_adapter)

    monkeypatch.setattr(svc, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(svc, "_call_memory_classifier_llm", _fake_verify_call)
    monkeypatch.setattr(svc, "_graph_memory_state_changed", lambda **kwargs: True)

    await svc._on_interaction_completed(event)

    kwargs = memory_adapter.add_message.call_args.kwargs
    metadata = kwargs["metadata"]
    assert metadata["verify_confidence"] == 0.88
    assert metadata["verify_reason"] == "explicit user preference"
    assert metadata["verify_evidence"] == "please keep it concise"
    assert metadata["verify_attribution"] == "user"


def test_raw_log_replay_writes_store_and_updates_offset(tmp_path):
    from memory.adapter import MemoryAdapter

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled = True
    adapter.store_backend = "flat_memory"
    adapter.store = MagicMock()
    adapter.store.add_message.return_value = True
    adapter.hot_layer = None
    adapter._dual_write_store = None
    adapter._hot_layer_lock = threading.Lock()
    adapter._raw_log_enabled = True
    adapter._raw_log_defer_hot_write = True
    adapter._raw_log_flush_interval_s = 5.0
    adapter._raw_log_max_batch_size = 16
    adapter._raw_log_path = str(tmp_path / "raw_log.jsonl")
    adapter._raw_log_state_path = str(tmp_path / "raw_log.state.json")
    adapter._raw_log_lock = threading.Lock()
    adapter._raw_log_replay_lock = threading.Lock()
    adapter._raw_log_wakeup_event = threading.Event()
    adapter._raw_log_stop_event = threading.Event()
    adapter._raw_log_state = {"last_offset": 0, "last_entry_id": "", "updated_at": 0.0}
    adapter._on_message_saved_after_store = lambda *args, **kwargs: None

    ok = adapter._append_raw_log_event(
        session_id="s1",
        role="user",
        content="Remember my preference: concise answers.",
        user_id="u1",
        metadata={"memory_type": "preference"},
    )
    assert ok is True

    processed = adapter._replay_raw_log_once(max_records=8)
    assert processed == 1
    assert adapter.store.add_message.call_count == 1
    assert int(adapter._raw_log_state.get("last_offset", 0)) > 0
    with open(adapter._raw_log_state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    assert int(state.get("last_offset", 0)) > 0


def test_raw_log_state_persist_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    from memory.adapter import MemoryAdapter

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter._raw_log_state_path = str(tmp_path / "raw_log.state.json")
    adapter._raw_log_state = {"last_offset": 42, "last_entry_id": "entry-1", "updated_at": 0.0}

    original_replace = os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError("transient lock")
        return original_replace(src, dst)

    monkeypatch.setattr("memory.adapter.os.replace", flaky_replace)

    adapter._persist_raw_log_state()

    assert attempts["count"] == 2
    with open(adapter._raw_log_state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    assert state["last_offset"] == 42
    assert state["last_entry_id"] == "entry-1"
    assert not list(tmp_path.glob("*.tmp"))


def test_on_message_saved_skips_when_raw_log_deferred():
    from memory.adapter import MemoryAdapter

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled = True
    adapter.hot_layer = object()
    adapter._raw_log_enabled = True
    adapter._raw_log_defer_hot_write = True

    called = {"count": 0}
    adapter._on_message_saved_after_store = (
        lambda *args, **kwargs: called.__setitem__("count", called["count"] + 1)
    )
    adapter.on_message_saved("s1", "user", "u1")
    assert called["count"] == 0

def test_raw_log_replay_does_not_require_append_lock(tmp_path):
    from memory.adapter import MemoryAdapter

    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled = True
    adapter.store_backend = "flat_memory"
    adapter.store = MagicMock()
    adapter.store.add_message.return_value = True
    adapter.hot_layer = None
    adapter._dual_write_store = None
    adapter._hot_layer_lock = threading.Lock()
    adapter._raw_log_enabled = True
    adapter._raw_log_defer_hot_write = True
    adapter._raw_log_flush_interval_s = 5.0
    adapter._raw_log_max_batch_size = 16
    adapter._raw_log_path = str(tmp_path / "raw_log.jsonl")
    adapter._raw_log_state_path = str(tmp_path / "raw_log.state.json")
    adapter._raw_log_lock = threading.Lock()
    adapter._raw_log_replay_lock = threading.Lock()
    adapter._raw_log_wakeup_event = threading.Event()
    adapter._raw_log_stop_event = threading.Event()
    adapter._raw_log_state = {"last_offset": 0, "last_entry_id": "", "updated_at": 0.0}
    adapter._on_message_saved_after_store = lambda *args, **kwargs: None

    assert adapter._append_raw_log_event(
        session_id="s1",
        role="user",
        content="Queue-safe replay test",
        user_id="u1",
        metadata={},
    )

    adapter._raw_log_lock.acquire()
    try:
        processed = adapter._replay_raw_log_once(max_records=4)
    finally:
        adapter._raw_log_lock.release()

    assert processed == 1
    assert adapter.store.add_message.call_count == 1


def test_memory_visibility_hints_record_and_drain():
    from gateway.memory_service import MemoryService

    svc = MemoryService(memory_adapter=MagicMock())
    svc._record_visibility_hint(
        session_id="s1",
        user_id="u1",
        memory_type="preference",
        target_memory_layer="profile_memory",
        decision="allow",
        reason="durable_factual_state",
        persisted=True,
        requires_user_confirmation=False,
        content="prefer concise answers",
        conflict_candidates=[],
        proposal_id=None,
    )

    rows = svc.drain_visibility_hints(session_id="s1", user_id="u1", limit=3)
    assert len(rows) == 1
    assert rows[0]["type"] == "memory_saved"
    assert svc.drain_visibility_hints(session_id="s1", user_id="u1", limit=3) == []
