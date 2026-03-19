from gateway.memory_service import MemoryService


class _Adapter:
    def __init__(self):
        self.store_backend = "sqlite_graph"
        self._enabled = True
        self._rows = []
        self._add_ok = True
        self.last_add = None
        self.last_list = None

    def is_enabled(self):
        return self._enabled

    def get_capabilities(self):
        return {
            "backend": "sqlite_graph",
            "supports_graph": True,
            "supports_crud": True,
        }

    def list_memory_entries(self, **kwargs):
        self.last_list = dict(kwargs)
        return list(self._rows)

    def add_message(self, **kwargs):
        self.last_add = dict(kwargs)
        return self._add_ok

    def update_memory_entry(self, **kwargs):
        return {"ok": True, "updated": 1, **kwargs}

    def delete_memory_entry(self, **kwargs):
        return {"ok": True, "deleted": 1, **kwargs}

    def export_mef(self, **kwargs):
        return {"nodes": [], "edges": []}


class _Connector:
    pass


class _HotLayer:
    def __init__(self):
        self.connector = _Connector()


class _AdapterWithHot(_Adapter):
    def __init__(self):
        super().__init__()
        self.hot_layer = _HotLayer()


class _MessageManager:
    def __init__(self, sessions=None):
        self._sessions = sessions or {}

    def get_session(self, session_id, user_id=None):
        return self._sessions.get((session_id, user_id))


def test_capabilities_snapshot_shape():
    svc = MemoryService(memory_adapter=_Adapter())
    out = svc.get_capabilities_snapshot()
    assert out["ok"] is True
    assert out["enabled"] is True
    assert out["capabilities"]["backend"] == "sqlite_graph"
    assert out["capabilities"]["supports_graph"] is True
    assert out["capabilities"]["supports_crud"] is True
    assert out["capabilities"]["supports_recall_runs"] is True


def test_list_entries_scope_defaults_and_archive_filter():
    adapter = _Adapter()
    adapter._rows = [
        {"id": "1", "status": "active"},
        {"id": "2", "status": "archived"},
    ]
    svc = MemoryService(memory_adapter=adapter)

    out = svc.list_entries(user_id="u1", scope="project", include_archived=False)
    assert out["ok"] is True
    assert out["total"] == 1
    assert adapter.last_list["memory_types"] == ["project_state"]


def test_create_entry_parity():
    adapter = _Adapter()
    svc = MemoryService(memory_adapter=adapter)

    assert svc.create_entry(user_id="u1", content="   ") == {
        "ok": False,
        "reason": "content_required",
    }

    out = svc.create_entry(
        user_id="u1",
        content="remember this",
        memory_type="preference",
        session_id=None,
        source_layer=None,
    )
    assert out == {"ok": True}
    assert adapter.last_add["session_id"] == "manual"
    assert adapter.last_add["metadata"]["memory_type"] == "preference"
    assert adapter.last_add["metadata"]["source_layer"] == "direct"
    assert adapter.last_add["metadata"]["memory_source"] == "user.manual_entry"


def test_build_dev_dashboard_aggregates():
    svc = MemoryService(memory_adapter=_Adapter())
    svc._write_decisions = [
        {"user_id": "u1", "decision": "allow", "reason": "ok"},
        {"user_id": "u1", "decision": "deny", "reason": "conflict"},
    ]
    svc._recall_runs = [
        {
            "user_id": "u1",
            "metrics": {"total_candidates": 4, "selected": 2},
            "memory_records": [{"source_layer": "recent"}, {"source_layer": "concept"}],
        }
    ]
    out = svc.build_dev_dashboard(user_id="u1")
    assert out["write"]["candidates"] == 2
    assert out["write"]["allow_rate"] == 0.5
    assert out["recall"]["runs"] == 1
    assert out["recall"]["candidates"] == 4
    assert out["recall"]["selected"] == 2
    assert out["recall"]["layer_contribution"]["recent"] == 1


def test_get_session_concepts_and_summaries(monkeypatch):
    class _Warm:
        @staticmethod
        def get_concepts(_sid):
            return [{"id": "c1"}]

    class _Cold:
        @staticmethod
        def get_summaries(_sid):
            return [{"id": "s1"}]

    monkeypatch.setattr("memory.create_warm_layer_manager", lambda _connector: _Warm())
    monkeypatch.setattr("memory.create_cold_layer_manager", lambda _connector: _Cold())
    svc = MemoryService(memory_adapter=_AdapterWithHot())

    concepts = svc.get_session_concepts(memory_session_id="ms1")
    assert concepts["ok"] is True
    assert concepts["concepts"] == [{"id": "c1"}]

    summaries = svc.get_session_summaries(memory_session_id="ms1")
    assert summaries["ok"] is True
    assert summaries["total_summaries"] == 1


def test_get_summary_for_user_ownership(monkeypatch):
    class _Cold:
        @staticmethod
        def get_summary_by_id(_summary_id):
            return {"id": "sum1", "session_id": "sid1"}

    monkeypatch.setattr("memory.create_cold_layer_manager", lambda _connector: _Cold())
    monkeypatch.setattr("gateway.memory_service.ensure_session_owned", lambda *_args, **_kwargs: (False, ""))
    svc = MemoryService(memory_adapter=_AdapterWithHot())
    out = svc.get_summary_for_user(summary_id="sum1", user_id="u1")
    assert out["ok"] is False
    assert out["reason"] == "summary_not_found"


def test_get_graph_global_flat_memory():
    adapter = _Adapter()
    adapter.store_backend = "flat_memory"
    svc = MemoryService(memory_adapter=adapter)
    out = svc.get_graph_global_for_user(user_id="u1")
    assert out["ok"] is True
    assert out["graph_available"] is False
    assert out["graph_mode"] == "none"


def test_get_graph_session_sqlite_graph():
    adapter = _AdapterWithHot()
    adapter.store_backend = "sqlite_graph"
    adapter.export_mef = lambda **_kwargs: {
        "nodes": [{"id": "n1", "node_type": "token", "session_id": "u1::s1", "content": "x"}],
        "edges": [{"src_node_id": "n1", "dst_node_id": "n1", "edge_type": "rel", "weight": 1.0}],
    }
    svc = MemoryService(memory_adapter=adapter)
    out = svc.get_graph_for_session(session_id="s1", user_id="u1")
    assert out["ok"] is True
    assert out["handled"] is True
    assert out["graph_mode"] == "sqlite_graph"
    assert out["stats"]["total_nodes"] == 1


def test_ensure_session_access():
    svc = MemoryService(
        memory_adapter=_Adapter(),
        message_manager=_MessageManager({("s1", "u1"): {"id": "s1"}}),
    )
    assert svc.ensure_session_access(session_id="s1", user_id="u1") == {"ok": True}
    assert svc.ensure_session_access(session_id="s2", user_id="u1") == {
        "ok": False,
        "reason": "session_not_found",
    }


def test_resolve_owned_memory_session(monkeypatch):
    monkeypatch.setattr(
        "gateway.memory_service.ensure_session_owned",
        lambda _connector, session_id, user_id: (True, f"{user_id}:{session_id}"),
    )
    svc = MemoryService(memory_adapter=_AdapterWithHot())
    out = svc.resolve_owned_memory_session(session_id="s1", user_id="u1")
    assert out == {"ok": True, "memory_session_id": "u1:s1"}


