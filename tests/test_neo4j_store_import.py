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


class _FakeConnector:
    def __init__(self):
        self.calls = []

    def query(self, q, params):
        self.calls.append((q, params))
        query = " ".join(str(q).split())
        if "RETURN properties(m) AS props, s.id AS session_id" in query:
            return [
                {
                    "props": {
                        "id": "m1",
                        "user_id": "u1",
                        "role": "user",
                        "content": "hello",
                        "memory_type": "episodic",
                        "target_memory_layer": "direct",
                        "importance": 0.8,
                        "created_at": "2026-01-01T00:00:00Z",
                        "metadata_json": "{}",
                    },
                    "session_id": "session_u1::s1",
                }
            ]
        if "RETURN elementId(x) AS element_id, labels(x) AS labels, properties(x) AS props" in query:
            return [
                {"element_id": "1", "labels": ["User"], "props": {"id": "user_u1", "user_id": "u1"}},
                {"element_id": "2", "labels": ["Session"], "props": {"id": "session_u1::s1", "user_id": "u1"}},
                {"element_id": "3", "labels": ["Message"], "props": {"id": "m1", "user_id": "u1", "content": "hello"}},
            ]
        if "RETURN elementId(a) AS src_id" in query:
            return [
                {"src_id": "2", "dst_id": "1", "rel_type": "OWNED_BY", "rel_props": {"id": "r1"}},
                {"src_id": "3", "dst_id": "2", "rel_type": "PART_OF_SESSION", "rel_props": {"id": "r2"}},
            ]
        return []


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


def test_export_mef_includes_graph_nodes_and_edges():
    connector = _FakeConnector()
    store = Neo4jMemoryStore(adapter=None, connector=connector, recall_engine=None)

    out = store.export_mef(user_id="u1")
    assert out["source_backend"] == "neo4j"
    assert out["metadata"]["mode"] == "graph_snapshot"
    assert len(out["memory_items"]) == 1
    assert len(out["nodes"]) >= 3
    assert len(out["edges"]) >= 2
    assert out["memory_items"][0]["session_id"] == "u1::s1"


def test_import_mef_with_connector_preserves_nodes_edges_and_messages():
    connector = _FakeConnector()
    store = Neo4jMemoryStore(adapter=None, connector=connector, recall_engine=None)
    payload = {
        "nodes": [
            {"id": "user_u1", "user_id": "u1", "node_type": "user", "metadata_json": "{}"},
            {"id": "session_u1::s1", "user_id": "u1", "node_type": "session", "metadata_json": "{}"},
        ],
        "edges": [
            {"id": "r1", "user_id": "u1", "src_node_id": "session_u1::s1", "dst_node_id": "user_u1", "edge_type": "owned_by"},
        ],
        "memory_items": [
            {"id": "m1", "user_id": "u1", "session_id": "s1", "role": "user", "content": "hello"},
        ],
    }

    out = store.import_mef(payload, merge=True)
    assert out["ok"] is True
    assert out["imported"]["nodes"] >= 2
    assert out["imported"]["edges"] >= 1
    assert out["imported"]["memory_items"] >= 1
    assert out["errors"] == []
