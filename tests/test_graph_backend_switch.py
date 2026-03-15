from types import SimpleNamespace

from memory.adapter import MemoryAdapter
from memory.backends.sqlite_graph import SqliteGraphMemoryStore


def test_backend_switch_sqlite_to_flat_with_mef(tmp_path):
    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter.enabled = True
    adapter.hot_layer = None
    adapter.recall_engine = None
    adapter._warm_layer = None
    adapter._cold_layer = None
    adapter._forgetting = None
    adapter._session_cache = {}
    adapter._hot_layer_lock = None
    adapter._maintenance_lock = None
    adapter._idle_timer_lock = None
    adapter._idle_timers = {}
    adapter._maintenance_state = {}
    adapter._migration_state = {"mode": "off", "source_backend": None, "target_backend": None, "checkpoint": None, "updated_at": None}
    adapter._dual_write_store = None
    adapter.store_backend = "sqlite_graph"
    adapter._config = SimpleNamespace(
        memory=SimpleNamespace(
            sqlite_graph_path=str(tmp_path / "graph.db"),
            flat_memory_path=str(tmp_path / "flat.jsonl"),
        )
    )
    adapter.store = SqliteGraphMemoryStore(str(tmp_path / "graph.db"))

    ok = adapter.add_message(
        session_id="s1",
        role="user",
        content="I prefer Rust services with tokio runtime.",
        user_id="u1",
        metadata={"memory_type": "preference", "source_layer": "direct"},
    )
    assert ok is True

    out = adapter.migrate_backend("flat_memory", mode="cutover")
    assert out.get("ok") is True
    assert adapter.store_backend == "flat_memory"

    context = adapter.get_context(query="tokio", session_id="s2", user_id="u1")
    assert "tokio" in context.lower()

