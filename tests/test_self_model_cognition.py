from types import SimpleNamespace
import json

import pytest

from gateway.self_model_service import SelfModelService


class _MemoryService:
    def list_entries(self, **_kwargs):
        return {
            "ok": True,
            "entries": [
                {
                    "memory_id": "m1",
                    "content": "The user prefers concise answers.",
                    "memory_type": "preference",
                    "source_layer": "warm",
                    "importance": 0.9,
                    "status": "active",
                    "updated_at": "2026-09-16T08:00:00Z",
                    "metadata": {"semantic_keys": ["response-style"]},
                },
                {
                    "memory_id": "m2",
                    "content": "The user may move to Shanghai.",
                    "memory_type": "plan",
                    "status": "active",
                    "metadata": {"memory_modality": "plan", "memory_persistence": "bounded"},
                },
                {
                    "memory_id": "m3",
                    "content": "The user previously lived in Beijing.",
                    "memory_type": "identity",
                    "status": "archived",
                },
            ],
        }

    def list_write_proposals(self, **_kwargs):
        return [
            {
                "proposal_id": "p1",
                "content": "The user now lives in Shanghai.",
                "memory_type": "identity",
                "confidence": 0.8,
            }
        ]


class _CandidateMemoryService(_MemoryService):
    def __init__(self):
        self.queries = []
        self.offered_snapshots = []

    def retrieve_candidates(self, **kwargs):
        self.queries.append(kwargs["query"])
        return {
            "ok": True,
            "candidates": [
                {
                    "memory_id": "candidate-1",
                    "content": "The current project uses Neo4j.",
                    "memory_type": "project_state",
                    "source_layer": "warm",
                    "importance": 0.9,
                    "relevance_score": 0.95,
                    "metadata": {"community_id": "project-db"},
                }
            ],
        }

    async def offer_cognition_snapshot(self, **kwargs):
        metrics = kwargs.get("snapshot", {}).get("metrics", {})
        if int(metrics.get("llm_calls") or 0) <= 0 or metrics.get("degraded"):
            return False
        self.offered_snapshots.append(kwargs)
        return True


class _FakeLLM:
    def __init__(self):
        self.calls = []

    async def call_llm(self, messages, **_kwargs):
        self.calls.append(messages)
        question = messages[-1]["content"].split("Question:\n", 1)[-1].split("\n", 1)[0]
        return {
            "status": "success",
            "content": json.dumps(
                {
                    "summary": f"summary for {question}",
                    "relevant_ids": ["memory:candidate-1"],
                    "critical_ids": [],
                    "uncertainties": [],
                }
            ),
        }


def test_cognition_bundle_projects_memory_into_self_model_sections(tmp_path):
    service = SelfModelService(workspace_root=str(tmp_path))
    bundle = service.project_cognition(
        user_id="u1",
        entries=_MemoryService().list_entries()["entries"],
        proposals=_MemoryService().list_write_proposals(),
    )

    assert bundle["model_scope"] == "self_model.cognition"
    assert bundle["stats"]["total"] == 4
    by_id = {item["cognition_id"]: item for item in bundle["items"]}
    assert by_id["memory:m1"]["domain"] == "user"
    assert by_id["memory:m1"]["state"] == "current"
    assert by_id["memory:m2"]["state"] == "evolving"
    assert by_id["memory:m3"]["state"] == "historical"
    assert by_id["proposal:p1"]["state"] == "uncertain"
    assert by_id["proposal:p1"]["action_required"] is True


def test_self_model_service_composes_cognition_from_memory(tmp_path):
    service = SelfModelService(memory_service=_MemoryService(), workspace_root=str(tmp_path))

    result = service.build_cognition_bundle(user_id="u1")

    assert result["ok"] is True
    assert result["cognition"]["user_id"] == "u1"
    assert result["cognition"]["stats"]["states"]["uncertain"] == 1


@pytest.mark.asyncio
async def test_self_model_context_is_bounded_and_marks_uncertainty(tmp_path):
    service = SelfModelService(memory_service=_MemoryService(), workspace_root=str(tmp_path))

    context = await service.build_context(
        user_id="u1",
        query="What do you know?",
        run_context=SimpleNamespace(task_id="task-1", run_id="run-1", session_id="session-1"),
        budget_chars=900,
    )

    assert context["version"] == "self_model.context.v1"
    assert context["active"]["task_id"] == "task-1"
    assert "Uncertainties" in context["prompt_text"]
    assert "not established fact" in context["prompt_text"]
    assert len(context["prompt_text"]) <= 900


@pytest.mark.asyncio
async def test_passive_self_model_projection_uses_query_candidate_pool(tmp_path):
    memory = _CandidateMemoryService()
    service = SelfModelService(memory_service=memory, workspace_root=str(tmp_path))

    context = await service.build_context(
        user_id="u1",
        query="Which database does the project use?",
        run_context=SimpleNamespace(session_id="s1"),
    )

    assert memory.queries == ["Which database does the project use?"]
    assert "Neo4j" in context["prompt_text"]


@pytest.mark.asyncio
async def test_active_cognition_recall_uses_shared_pool_and_supplied_facets(tmp_path):
    memory = _CandidateMemoryService()
    llm = _FakeLLM()
    run_context = SimpleNamespace(
        request_id="req-1",
        trace_id="trace-1",
        task_id="task-1",
        run_id="run-1",
        session_id="s1",
    )
    service = SelfModelService(
        memory_service=memory,
        llm_client=llm,
        workspace_root=str(tmp_path),
    )

    result = await service.recall_cognition(
        user_id="u1",
        session_id="s1",
        query="Compare the project database and its current constraints.",
        facets=["database", "constraints"],
        mode="adaptive",
        run_context=run_context,
        user_config={"self_model": {"recall": {"skip_score_threshold": 1.0}}},
    )

    assert result["ok"] is True
    assert memory.queries == ["Compare the project database and its current constraints."]
    assert len(result["snapshot"]["channels"]) == 2
    assert result["snapshot"]["metrics"]["llm_calls"] == 2
    assert result["snapshot"]["basis_memory_ids"] == ["candidate-1"]
    assert memory.offered_snapshots[0]["snapshot"] is result["snapshot"]
    assert run_context.cognition_snapshot["version"] == "self_model.cognition_snapshot.v1"


@pytest.mark.asyncio
async def test_fast_cognition_keeps_uncertain_proposal_in_skip_buffer(tmp_path):
    memory = _CandidateMemoryService()
    service = SelfModelService(memory_service=memory, workspace_root=str(tmp_path))

    result = await service.recall_cognition(
        user_id="u1",
        session_id="s1",
        query="Where does the user live?",
        mode="fast",
    )

    assert result["ok"] is True
    assert result["snapshot"]["mode"] == "fast"
    assert memory.offered_snapshots == []
    assert any(item.get("proposal_id") == "p1" for item in result["snapshot"]["critical_items"])
