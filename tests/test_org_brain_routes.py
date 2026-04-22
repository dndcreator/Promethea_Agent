from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from gateway.http.routes import org_brain


class _CfgSvc:
    def __init__(self, merged):
        self._merged = merged

    def get_merged_config(self, _user_id):
        return dict(self._merged)


class _Svc:
    def __init__(self, enabled: bool, org_id: str = "org_demo", connector_available: bool = False):
        self._enabled = enabled
        self._org_id = org_id
        self._connector_available = connector_available

    def resolve_org_profile(self, _merged):
        return {"enabled": self._enabled, "org_id": self._org_id}

    def _resolve_connector(self):
        return object() if self._connector_available else None

    async def get_visual_graph(self, **kwargs):
        _ = kwargs
        return {
            "enabled": True,
            "org_id": self._org_id,
            "backend": "neo4j",
            "nodes": [{"id": "concept:c1", "type": "concept", "label": "c1"}],
            "edges": [{"id": "edge:e1", "type": "EXPRESSED_AS", "source": "concept:c1", "target": "expression:e1"}],
            "stats": {"nodes": 1, "edges": 1},
        }


@pytest.mark.asyncio
async def test_org_brain_graph_requires_enabled_feature(monkeypatch):
    monkeypatch.setattr(
        org_brain,
        "_get_org_service",
        lambda: (_Svc(enabled=False), _CfgSvc({"org_brain": {"enabled": False, "org_id": "org_demo"}})),
    )
    with pytest.raises(HTTPException) as ei:
        await org_brain.org_brain_graph(org_brain.OrgGraphRequest(org_id="org_demo"), current_user_id="u1")
    assert ei.value.status_code == 400
    assert "disabled" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_org_brain_graph_returns_nodes_and_edges(monkeypatch):
    monkeypatch.setattr(
        org_brain,
        "_get_org_service",
        lambda: (_Svc(enabled=True), _CfgSvc({"org_brain": {"enabled": True, "org_id": "org_demo"}})),
    )
    out = await org_brain.org_brain_graph(
        org_brain.OrgGraphRequest(org_id="org_demo", topic="strategy", audience="board", limit_nodes=100),
        current_user_id="u1",
    )
    assert out["status"] == "success"
    assert out["backend"] == "neo4j"
    assert out["stats"]["nodes"] == 1
    assert out["stats"]["edges"] == 1


@pytest.mark.asyncio
async def test_org_brain_status_exposes_fallback_notice(monkeypatch):
    monkeypatch.setattr(
        org_brain,
        "_get_org_service",
        lambda: (_Svc(enabled=True, connector_available=False), _CfgSvc({"org_brain": {"enabled": True, "org_id": "org_demo"}})),
    )
    out = await org_brain.org_brain_status(current_user_id="u1")
    assert out["status"] == "success"
    assert out["org_brain"]["core_capability"] == "graph_structure"
    assert out["org_brain"]["backend"] == "in_memory_fallback"
    assert "fallback mode" in str(out["org_brain"]["notice"]).lower()
