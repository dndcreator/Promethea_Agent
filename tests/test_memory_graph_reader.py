from copy import deepcopy
from types import SimpleNamespace

import pytest

from gateway.memory_service import MemoryService
from memory.graph_reader import read_session_graph, read_user_graph
from memory.session_scope import scoped_session_id, user_node_id


class GraphAdapter:
    store_backend = "sqlite_graph"

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.exports = []

    def is_enabled(self):
        return True

    def export_mef(self, *, user_id):
        self.exports.append(user_id)
        return self.snapshot


@pytest.fixture
def adapter():
    return GraphAdapter({
        "nodes": [
            {"id": "a", "node_type": "message", "content": "first", "session_id": scoped_session_id("s1", "u1")},
            {"id": "b", "node_type": "token", "content": "topic", "session_id": ""},
            {"id": "c", "node_type": "message", "content": "other", "session_id": scoped_session_id("s2", "u1")},
        ],
        "edges": [
            {"src_node_id": "a", "dst_node_id": "b", "edge_type": "MENTIONS", "weight": 0.8},
            {"source": "b", "target": "c", "type": "RELATED"},
        ],
    })


def test_sqlite_user_graph_projection_preserves_snapshot(adapter):
    original = deepcopy(adapter.snapshot)
    out = read_user_graph(adapter, user_id="u1")

    assert adapter.exports == ["u1"]
    assert adapter.snapshot == original
    assert out["user_id"] == "u1"
    assert out["graph_semantics"] == "lightweight"
    assert out["semantic_graph_available"] is False
    assert out["stats"] == {"total_nodes": 3, "total_edges": 2, "layers": {"hot": 2, "warm": 1, "cold": 0}}
    assert out["nodes"][1] == {
        "id": "b", "type": "token", "content": "topic", "layer": 1,
        "importance": 0.5, "access_count": 0, "created_at": None,
        "role": "", "memory_type": "", "memory_source": "sqlite_graph", "semantic_level": "lightweight",
    }
    assert out["edges"] == [
        {"source": "a", "target": "b", "type": "MENTIONS", "weight": 0.8},
        {"source": "b", "target": "c", "type": "RELATED", "weight": 1.0},
    ]


def test_sqlite_session_graph_filters_nodes_and_incident_edges(adapter):
    out = read_session_graph(adapter, session_id="s1", user_id="u1")

    assert adapter.exports == ["u1"]
    assert out["handled"] is True
    assert out["session_id"] == "s1"
    assert [node["id"] for node in out["nodes"]] == ["a", "b"]
    assert out["edges"] == [{"source": "a", "target": "b", "type": "MENTIONS", "weight": 0.8}]
    assert out["stats"]["total_edges"] == 1


def test_neo4j_graph_uses_owned_user_anchor_and_preserves_semantics():
    calls = []

    def query(cypher, params):
        calls.append((cypher, params))
        if "RETURN node.id" in cypher:
            return [{"id": "c1", "type": "Concept", "layer": 1, "content": "topic"}]
        return [{"source": "c1", "target": "c1", "type": "RELATED", "weight": 0.7}]

    adapter = SimpleNamespace(store_backend="neo4j", hot_layer=SimpleNamespace(connector=SimpleNamespace(query=query)))
    out = read_user_graph(adapter, user_id="u1")

    assert len(calls) == 2
    assert all(params == {"user_node_id": user_node_id("u1")} for _, params in calls)
    assert all("OWNED_BY" in cypher for cypher, _ in calls)
    assert "a.id IN node_ids AND b.id IN node_ids" in calls[1][0]
    assert out["graph_mode"] == "neo4j"
    assert out["semantic_graph_available"] is True
    assert out["nodes"][0]["type"] == "concept"
    assert out["stats"] == {"total_nodes": 1, "total_edges": 1, "layers": {"hot": 0, "warm": 1, "cold": 0}}
    assert read_session_graph(adapter, session_id="s1", user_id="u1") == {"ok": True, "handled": False}


@pytest.mark.parametrize("session", [False, True])
def test_flat_backend_has_no_fabricated_graph(session):
    adapter = SimpleNamespace(store_backend="flat_memory")
    out = read_session_graph(adapter, session_id="s1", user_id="u1") if session else read_user_graph(adapter, user_id="u1")
    assert out["ok"] is True
    assert out["graph_available"] is False
    assert out["nodes"] == [] and out["edges"] == []
    assert out["stats"]["total_nodes"] == 0


def test_reader_errors_preserve_facade_failure_shapes():
    def fail(**_kwargs):
        raise RuntimeError("store unavailable")

    adapter = SimpleNamespace(store_backend="sqlite_graph", export_mef=fail)
    assert read_user_graph(adapter, user_id="u1") == {"ok": False, "reason": "graph_global_failed:store unavailable"}
    assert read_session_graph(adapter, session_id="s1", user_id="u1") == {
        "ok": False, "reason": "graph_session_failed:store unavailable", "handled": False,
    }


def test_facade_keeps_enablement_and_current_adapter_authority(monkeypatch, adapter):
    monkeypatch.setattr(MemoryService, "_create_hippocampus_service", lambda self: None)
    service = MemoryService(memory_adapter=adapter)
    service.enabled = False
    assert service.get_graph_global_for_user(user_id="u1") == {"ok": False, "reason": "memory_not_enabled"}
    assert service.get_graph_for_session(session_id="s1", user_id="u1") == {
        "ok": False, "reason": "memory_not_enabled", "handled": False,
    }
    assert adapter.exports == []

    service.enabled = True
    service.memory_adapter = GraphAdapter({"nodes": [], "edges": []})
    assert service.get_graph_global_for_user(user_id="u1")["nodes"] == []
    assert service.memory_adapter.exports == ["u1"]
    assert adapter.exports == []
