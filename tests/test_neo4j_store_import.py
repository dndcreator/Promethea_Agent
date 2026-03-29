from memory.backends.neo4j_store import Neo4jMemoryStore


class _DummyHotLayer:
    def __init__(self):
        self.session_id = ""
        self.user_id = ""
        self.rows = []

    def process_message(self, role, content, ctx, metadata=None):
        self.rows.append({"role": role, "content": content, "ctx": ctx, "metadata": metadata or {}})


class _DummyAdapter:
    def __init__(self):
        self.hot_layer = _DummyHotLayer()

    def _get_context(self, scoped_sid):
        return {"scoped_session": scoped_sid}

    def _update_cache(self, scoped_sid, role, content):
        _ = (scoped_sid, role, content)


def test_import_mef_imports_memory_items_with_append_semantics():
    adapter = _DummyAdapter()
    store = Neo4jMemoryStore(adapter=adapter, connector=None, recall_engine=None)
    payload = {
        "memory_items": [
            {"user_id": "u1", "session_id": "s1", "role": "user", "content": "hello"},
            {"user_id": "u1", "session_id": "s1", "role": "assistant", "content": ""},
        ]
    }

    out = store.import_mef(payload, merge=True)
    assert out["ok"] is True
    assert out["imported"]["memory_items"] == 1
    assert out["skipped"]["memory_items"] == 1
    assert len(adapter.hot_layer.rows) == 1
    assert adapter.hot_layer.rows[0]["content"] == "hello"


def test_import_mef_merge_false_keeps_append_mode_and_reports_note():
    adapter = _DummyAdapter()
    store = Neo4jMemoryStore(adapter=adapter, connector=None, recall_engine=None)
    payload = {"memory_items": [{"user_id": "u1", "session_id": "s1", "role": "user", "content": "x"}]}

    out = store.import_mef(payload, merge=False)
    assert out["merge"] is False
    assert out["imported"]["memory_items"] == 1
    assert any("append-only" in msg for msg in out["errors"])
