from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.org_context_service import OrgContextService


class _FakeConnector:
    def __init__(self):
        self.writes = []

    def query(self, cypher, parameters=None):
        params = dict(parameters or {})
        if "RETURN c.id as concept_id" in cypher:
            return [
                {
                    "concept_id": "org_concept_1",
                    "concept": "three-pillar-strategy",
                    "expression_id": "org_expr_1",
                    "expression": "emphasize long-term resilient growth",
                    "audience": "board",
                    "register": "formal",
                    "source_doc_id": "doc_1",
                    "confidence": 0.9,
                }
            ]
        if "MATCH (c:OrgConcept" in cypher:
            return [
                {
                    "concept": "three-pillar-strategy",
                    "expression": "emphasize long-term resilient growth",
                    "audience": "board",
                    "register": "formal",
                    "terms_locked": ["three-pillar-strategy"],
                    "confidence": 0.9,
                    "audience_hit": 1,
                }
            ]
        self.writes.append((cypher, params))
        return []


def _build_memory_service_with_connector(connector):
    return SimpleNamespace(
        memory_adapter=SimpleNamespace(
            hot_layer=SimpleNamespace(connector=connector),
        )
    )


def test_org_profile_and_enable_switch():
    svc = OrgContextService()
    profile = svc.resolve_org_profile({"org_brain": {"enabled": True, "org_id": "acme"}})
    assert profile["enabled"] is True
    assert profile["org_id"] == "acme"
    assert svc.is_enabled({"org_brain": {"enabled": True, "org_id": "acme"}}) is True
    assert svc.is_enabled({"org_brain": {"enabled": True, "org_id": ""}}) is False


@pytest.mark.asyncio
async def test_ingest_and_recall_with_fallback():
    svc = OrgContextService()
    out = await svc.ingest_document(
        org_id="org_a",
        source_doc_id="doc_1",
        text="Three-pillar strategy: research, retirement finance, and equity investment.",
        audience="business",
        register="operational",
        use_llm=False,
    )
    assert out["success"] is True
    assert out["accepted"] >= 1
    assert out["core_capability"] == "graph_structure"
    assert "fallback mode" in str(out.get("notice") or "").lower()

    recalled = await svc.recall_org_context(
        org_id="org_a",
        topic="strategy",
        audience="business",
        context_type="writing",
        top_k=3,
        user_id="u1",
    )
    assert recalled["recalled"] is True
    assert recalled["backend"] == "in_memory_fallback"
    assert recalled["core_capability"] == "graph_structure"
    assert "fallback mode" in str(recalled.get("notice") or "").lower()
    assert "summary_text" in recalled


@pytest.mark.asyncio
async def test_recall_with_neo4j_connector():
    connector = _FakeConnector()
    svc = OrgContextService(memory_service=_build_memory_service_with_connector(connector))
    payload = await svc.recall_org_context(
        org_id="org_demo",
        topic="strategy",
        audience="board",
        context_type="writing",
        top_k=5,
        user_id="u1",
    )
    assert payload["recalled"] is True
    assert payload["backend"] == "neo4j"
    assert payload["core_capability"] == "graph_structure"
    assert not payload.get("notice")
    assert payload["items"][0]["concept"] == "three-pillar-strategy"


@pytest.mark.asyncio
async def test_visual_graph_with_neo4j_connector():
    connector = _FakeConnector()
    svc = OrgContextService(memory_service=_build_memory_service_with_connector(connector))
    payload = await svc.get_visual_graph(org_id="org_demo", topic="strategy", audience="board", limit_nodes=100, user_id="u1")
    assert payload["backend"] == "neo4j"
    assert payload["core_capability"] == "graph_structure"
    assert not payload.get("notice")
    assert payload["stats"]["nodes"] >= 2
    assert payload["stats"]["edges"] >= 1
    assert any(node.get("type") == "concept" for node in payload["nodes"])


@pytest.mark.asyncio
async def test_visual_graph_with_fallback():
    svc = OrgContextService()
    await svc.ingest_document(
        org_id="org_a",
        source_doc_id="doc_1",
        text="Three-pillar strategy: research, retirement finance, and equity investment.",
        audience="business",
        register="operational",
        use_llm=False,
    )
    payload = await svc.get_visual_graph(org_id="org_a", topic="strategy", audience="business", limit_nodes=100, user_id="u1")
    assert payload["backend"] == "in_memory_fallback"
    assert payload["core_capability"] == "graph_structure"
    assert "fallback mode" in str(payload.get("notice") or "").lower()
    assert payload["stats"]["nodes"] >= 2
    assert payload["stats"]["edges"] >= 1
