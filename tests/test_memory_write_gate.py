from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.events import EventEmitter
from gateway.memory_gate import MemoryWriteDecision, MemoryWriteGate, MemoryWriteRequest
from gateway.memory_service import MemoryService
from gateway.protocol import EventType


def test_memory_write_gate_allows_factual_memory():
    gate = MemoryWriteGate()
    request = MemoryWriteRequest(
        source_text="I prefer concise answers.",
        proposed_memory_type="preference",
        extracted_content="User prefers concise answers.",
        confidence=0.92,
        modality="actual",
        persistence="durable",
    )

    decision = gate.evaluate(request)

    assert decision.decision == "allow"
    assert decision.target_memory_layer == "profile_memory"
    assert decision.reason == "durable_factual_state"


def test_memory_write_gate_denies_hypothetical_memory_without_language_rules():
    gate = MemoryWriteGate()
    request = MemoryWriteRequest(
        source_text="如果我以后换工作会怎么样",
        proposed_memory_type="goal",
        extracted_content="用户假设自己以后换工作",
        confidence=0.88,
        modality="hypothetical",
        persistence="bounded",
    )

    decision = gate.evaluate(request)

    assert decision.decision == "deny"
    assert decision.reason == "hypothetical_state"


def test_memory_write_gate_defers_extractor_classified_ephemeral_state():
    gate = MemoryWriteGate()
    request = MemoryWriteRequest(
        source_text="这一次先使用测试地址",
        proposed_memory_type="project_state",
        extracted_content="本次操作使用测试地址",
        confidence=0.9,
        modality="actual",
        persistence="ephemeral",
    )

    decision = gate.evaluate(request)

    assert decision.decision == "defer"
    assert decision.target_memory_layer == "working_memory"
    assert decision.reason == "ephemeral_state"


def test_memory_write_gate_routes_bounded_state_to_episodic_memory():
    decision = MemoryWriteGate().evaluate(
        MemoryWriteRequest(
            proposed_memory_type="preference",
            extracted_content="本项目使用简短回答",
            confidence=0.9,
            modality="actual",
            persistence="bounded",
        )
    )

    assert decision.decision == "allow"
    assert decision.target_memory_layer == "episodic_memory"


def test_memory_write_gate_defers_unclassified_semantic_scope():
    decision = MemoryWriteGate().evaluate(
        MemoryWriteRequest(
            proposed_memory_type="identity",
            extracted_content="用户拥有一个长期项目",
            confidence=0.9,
        )
    )

    assert decision.decision == "defer"
    assert decision.target_memory_layer == "working_memory"
    assert decision.reason == "semantic_scope_unclear"


def test_relationship_confirmation_policy_is_type_aware():
    gate = MemoryWriteGate()

    assert gate.relationship_requires_confirmation("preference", "updates") is True
    assert gate.relationship_requires_confirmation("project_state", "updates") is False
    assert gate.relationship_requires_confirmation("project_state", "contradicts") is True
    assert gate.relationship_requires_confirmation("identity", "compatible") is False


@pytest.mark.asyncio
async def test_verifier_parses_memory_relationship_and_bounded_related_indexes():
    service = MemoryService.__new__(MemoryService)

    async def _fake_llm(*_args, **_kwargs):
        return (
            '{"decisions":[{"index":0,"accept":true,"confidence":0.8,'
            '"reason":"supported","evidence":"user said it","attribution":"project",'
            '"modality":"actual","persistence":"bounded",'
            '"relationship":"updates","related_indexes":[1,99,"bad"]}]}'
        )

    service._call_memory_classifier_llm = _fake_llm
    result = await service._verify_candidates_with_llm(
        user_id="u1",
        user_input="The SDK now supports streaming.",
        assistant_output="Understood.",
        candidates=[
            {
                "type": "project_state",
                "content": "The SDK supports streaming.",
                "semantic_keys": ["typescript sdk"],
                "modality": "actual",
                "persistence": "bounded",
                "related_memories": ["The SDK exists.", "The SDK supports HTTP calls."],
            }
        ],
    )

    assert result[0]["memory_relationship"] == "updates"
    assert result[0]["relationship_indexes"] == [1]
    assert result[0]["modality"] == "actual"
    assert result[0]["persistence"] == "bounded"


@pytest.mark.asyncio
async def test_memory_service_marks_conflicting_write(monkeypatch):
    emitter = EventEmitter()
    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.add_message.return_value = True

    connector = MagicMock()
    connector.query.return_value = [{"content": "I prefer concise answers."}]
    memory_adapter.hot_layer = SimpleNamespace(connector=connector)

    service = MemoryService(event_emitter=emitter, memory_adapter=memory_adapter)

    async def _fake_classify(*args, **kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "preference",
                    "content": "I prefer detailed answers.",
                    "semantic_keys": ["prefer", "answers"],
                    "modality": "actual",
                    "persistence": "durable",
                }
            ],
        }

    async def _passthrough_verify(**kwargs):
        return kwargs.get("candidates", [])

    monkeypatch.setattr(service, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(service, "_verify_candidates_with_llm", _passthrough_verify)

    event = SimpleNamespace(
        payload={
            "session_id": "s1",
            "user_id": "u1",
            "channel": "web",
            "user_input": "remember this preference",
            "assistant_output": "ok",
        }
    )
    await service._on_interaction_completed(event)

    memory_adapter.add_message.assert_not_called()
    decisions = emitter.get_history(event=EventType.MEMORY_WRITE_DECIDED)
    assert decisions
    payload = decisions[-1].payload
    assert payload["decision"] == "defer"
    assert payload["reason"] == "conflict_detected"
    assert payload["requires_user_confirmation"] is True


@pytest.mark.asyncio
async def test_equivalent_related_memory_is_deduped_without_confirmation(monkeypatch):
    emitter = EventEmitter()
    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    connector = MagicMock()
    connector.query.return_value = [
        {"content": "User is enhancing the assistant by adding a TypeScript SDK."},
        {"content": "User is enhancing the assistant by adding a TypeScript SDK."},
    ]
    memory_adapter.hot_layer = SimpleNamespace(connector=connector)
    service = MemoryService(event_emitter=emitter, memory_adapter=memory_adapter)

    async def _fake_classify(*_args, **_kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "project_state",
                    "content": "User is working on adding a TypeScript SDK to the assistant.",
                    "semantic_keys": ["typescript sdk", "assistant development"],
                    "modality": "actual",
                    "persistence": "bounded",
                }
            ],
        }

    async def _fake_verify(**kwargs):
        row = dict(kwargs["candidates"][0])
        row.update(
            {
                "verify_confidence": 0.9,
                "verify_attribution": "project",
                "memory_relationship": "equivalent",
                "relationship_indexes": [0],
                "modality": "actual",
                "persistence": "bounded",
            }
        )
        return [row]

    monkeypatch.setattr(service, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(service, "_verify_candidates_with_llm", _fake_verify)
    await service._process_interaction_completed(
        {
            "session_id": "s1",
            "user_id": "u1",
            "user_input": "I added the TypeScript SDK.",
            "assistant_output": "Understood.",
        }
    )

    memory_adapter.add_message.assert_not_called()
    decision = emitter.get_history(event=EventType.MEMORY_WRITE_DECIDED)[-1].payload
    assert decision["decision"] == "deny"
    assert decision["reason"] == "semantic_duplicate"
    assert decision["relationship"] == "equivalent"
    assert decision["requires_user_confirmation"] is False


@pytest.mark.asyncio
async def test_compatible_related_memory_is_written_without_confirmation(monkeypatch):
    emitter = EventEmitter()
    memory_adapter = MagicMock()
    memory_adapter.is_enabled.return_value = True
    memory_adapter.add_message.return_value = True
    memory_adapter.hot_layer = SimpleNamespace(
        connector=MagicMock(query=MagicMock(return_value=[{"content": "User prefers concise answers."}]))
    )
    service = MemoryService(event_emitter=emitter, memory_adapter=memory_adapter)

    async def _fake_classify(*_args, **_kwargs):
        return {
            "has_long_term_state": True,
            "candidates": [
                {
                    "type": "preference",
                    "content": "User prefers technically rigorous answers.",
                    "semantic_keys": ["answer style"],
                    "modality": "actual",
                    "persistence": "durable",
                }
            ],
        }

    async def _fake_verify(**kwargs):
        row = dict(kwargs["candidates"][0])
        row.update(
            {
                "verify_confidence": 0.9,
                "verify_attribution": "user",
                "memory_relationship": "compatible",
                "relationship_indexes": [0],
                "modality": "actual",
                "persistence": "durable",
            }
        )
        return [row]

    monkeypatch.setattr(service, "_classify_interaction", _fake_classify)
    monkeypatch.setattr(service, "_verify_candidates_with_llm", _fake_verify)
    monkeypatch.setattr(service, "_graph_memory_state_changed", lambda **_kwargs: True)
    await service._process_interaction_completed(
        {
            "session_id": "s1",
            "user_id": "u1",
            "user_input": "I prefer technically rigorous answers too.",
            "assistant_output": "Understood.",
        }
    )

    memory_adapter.add_message.assert_called_once()
    assert memory_adapter.add_message.call_args.kwargs["metadata"]["memory_relationship"] == "compatible"
    decision = emitter.get_history(event=EventType.MEMORY_WRITE_DECIDED)[-1].payload
    assert decision["decision"] == "allow"
    assert decision["relationship"] == "compatible"
    assert decision["modality"] == "actual"
    assert decision["persistence"] == "durable"


def test_memory_write_decision_reason_serialization():
    decision = MemoryWriteDecision(
        decision="deny",
        target_memory_layer="semantic_memory",
        reason="speculative_content",
        reasons=["speculative_content"],
    )

    dumped = decision.model_dump()
    assert dumped["decision"] == "deny"
    assert dumped["reason"] == "speculative_content"
    assert dumped["reasons"] == ["speculative_content"]


@pytest.mark.asyncio
async def test_memory_write_proposal_can_confirm_without_superseding_conflicts():
    emitter = EventEmitter()
    memory_adapter = MagicMock()
    memory_adapter.add_message.return_value = True

    service = MemoryService(event_emitter=emitter, memory_adapter=memory_adapter)
    proposal_id = service._create_write_proposal(
        session_id="s1",
        user_id="u1",
        memory_type="preference",
        target_memory_layer="profile_memory",
        content="User prefers short direct answers.",
        semantic_keys=["answers"],
        conflict_candidates=["User prefers detailed answers."],
    )

    result = await service.resolve_write_proposal(
        proposal_id=proposal_id,
        user_id="u1",
        action="confirm_write_keep_existing",
    )

    assert result["ok"] is True
    proposal = result["proposal"]
    assert proposal["status"] == "confirmed"
    assert proposal["resolved_action"] == "confirm_write_keep_existing"
    memory_adapter.add_message.assert_called_once()
    memory_adapter.list_memory_entries.assert_not_called()
    memory_adapter.update_memory_entry.assert_not_called()
    payload = emitter.get_history(event=EventType.MEMORY_WRITE_DECIDED)[-1].payload
    assert payload["reason"] == "user_confirmed_write_keep_existing"
    assert payload["persisted"] is True
