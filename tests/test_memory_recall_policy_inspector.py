from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.memory_recall_schema import MemoryRecallRequest, MemoryRecallResult
from gateway.memory_service import MemoryService
from gateway.protocol import RequestMessage, RequestType
from gateway.server import GatewayServer


class _DummyAdapter:
    def is_enabled(self):
        return True

    def get_context(self, query: str, session_id: str, user_id: str = "default_user") -> str:
        return f"ctx:{query}:{session_id}:{user_id}"


@pytest.mark.asyncio
async def test_memory_recall_request_model_create():
    req = MemoryRecallRequest(
        request_id="r1",
        trace_id="t1",
        session_id="s1",
        user_id="u1",
        query_text="remember my preference",
    )
    assert req.request_id == "r1"
    assert req.mode == "fast"


def test_memory_recall_result_serialization():
    out = MemoryRecallResult(
        request_id="r1",
        trace_id="t1",
        session_id="s1",
        user_id="u1",
    )
    dumped = out.model_dump()
    assert dumped["request_id"] == "r1"
    assert isinstance(dumped["memory_records"], list)


@pytest.mark.asyncio
async def test_fast_mode_top_k_limited():
    svc = MemoryService(memory_adapter=_DummyAdapter())

    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": f"m{i}",
            "source_layer": "summary",
            "content": f"project alpha detail {i}",
            "importance": 0.9,
            "owner_user_id": "u1",
        }
        for i in range(10)
    ]

    result = await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_fast",
            trace_id="t_fast",
            session_id="s1",
            user_id="u1",
            query_text="project alpha",
            mode="fast",
            top_k=3,
        )
    )

    assert len(result.memory_records) == 3
    assert any(x.reason == "budget_limit" for x in result.dropped_candidates)


@pytest.mark.asyncio
async def test_deep_mode_allows_more_layers():
    svc = MemoryService(memory_adapter=_DummyAdapter())
    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": "m_summary",
            "source_layer": "summary",
            "content": "project summary",
            "importance": 0.6,
            "owner_user_id": "u1",
        },
        {
            "memory_id": "m_concept",
            "source_layer": "concept",
            "content": "core concept memory",
            "importance": 0.7,
            "owner_user_id": "u1",
        },
    ]

    result = await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_deep",
            trace_id="t_deep",
            session_id="s1",
            user_id="u1",
            query_text="concept",
            mode="deep",
            top_k=8,
        )
    )

    layers = {x.source_layer for x in result.memory_records}
    assert "summary" in layers
    assert "concept" in layers


@pytest.mark.asyncio
async def test_workflow_mode_marks_active_workflow_reason():
    svc = MemoryService(memory_adapter=_DummyAdapter())
    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": "m_workflow",
            "source_layer": "direct",
            "content": "current workspace milestone",
            "importance": 0.8,
            "source_session": "s1",
            "owner_user_id": "u1",
        }
    ]

    result = await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_flow",
            trace_id="t_flow",
            session_id="s1",
            user_id="u1",
            query_text="workspace milestone",
            mode="workflow",
            top_k=5,
        )
    )

    assert result.memory_records
    assert result.memory_records[0].recall_reason == "active_workflow_context"


@pytest.mark.asyncio
async def test_recall_reason_non_empty_and_dropped_recorded():
    svc = MemoryService(memory_adapter=_DummyAdapter())
    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": "m1",
            "source_layer": "summary",
            "content": "same content",
            "importance": 0.5,
            "owner_user_id": "u1",
        },
        {
            "memory_id": "m2",
            "source_layer": "summary",
            "content": "same content",
            "importance": 0.4,
            "owner_user_id": "u1",
        },
    ]

    result = await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_dup",
            trace_id="t_dup",
            session_id="s1",
            user_id="u1",
            query_text="same",
            mode="fast",
            top_k=5,
        )
    )

    assert result.memory_records
    assert all(x.recall_reason for x in result.memory_records)
    assert any(x.reason == "duplicate_candidate" for x in result.dropped_candidates)


@pytest.mark.asyncio
async def test_namespace_and_stale_filters():
    svc = MemoryService(memory_adapter=_DummyAdapter())
    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": "m_other_user",
            "source_layer": "summary",
            "content": "other user profile",
            "importance": 0.7,
            "owner_user_id": "u_other",
        },
        {
            "memory_id": "m_stale",
            "source_layer": "summary",
            "content": "old project plan",
            "importance": 0.7,
            "created_at": "2000-01-01T00:00:00+00:00",
            "owner_user_id": "u1",
        },
    ]

    result = await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_ns",
            trace_id="t_ns",
            session_id="s1",
            user_id="u1",
            query_text="project",
            mode="fast",
            top_k=5,
        )
    )

    reasons = {x.reason for x in result.dropped_candidates}
    assert "namespace_mismatch" in reasons
    assert "stale_candidate" in reasons


@pytest.mark.asyncio
async def test_memory_recall_inspector_handlers():
    svc = MemoryService(memory_adapter=_DummyAdapter())
    svc._collect_recall_candidates = lambda request: [
        {
            "memory_id": "m1",
            "source_layer": "summary",
            "content": "project memory",
            "importance": 0.9,
            "owner_user_id": "u1",
        }
    ]

    await svc.recall_memory(
        MemoryRecallRequest(
            request_id="r_inspect",
            trace_id="t_inspect",
            session_id="s1",
            user_id="u1",
            query_text="project",
            mode="fast",
            top_k=5,
        )
    )

    server = GatewayServer()
    server.memory_service = svc
    conn = SimpleNamespace(connection_id="c1", identity=SimpleNamespace(device_id="u1"))

    list_res = await server._handle_memory_recall_runs(
        conn,
        RequestMessage(id="r1", method=RequestType.MEMORY_RECALL_RUNS, params={"limit": 10}),
    )
    inspect_res = await server._handle_memory_recall_inspect(
        conn,
        RequestMessage(
            id="r2",
            method=RequestType.MEMORY_RECALL_INSPECT,
            params={"target_request_id": "r_inspect"},
        ),
    )

    assert list_res.ok is True
    assert list_res.payload["total"] >= 1
    assert inspect_res.ok is True
    assert inspect_res.payload["run"]["request_id"] == "r_inspect"
