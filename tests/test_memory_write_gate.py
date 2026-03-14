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
    )

    decision = gate.evaluate(request)

    assert decision.decision == "allow"
    assert decision.target_memory_layer == "profile_memory"
    assert decision.reason == "durable_factual_state"


def test_memory_write_gate_denies_speculative_memory():
    gate = MemoryWriteGate()
    request = MemoryWriteRequest(
        source_text="maybe I will switch jobs soon",
        proposed_memory_type="goal",
        extracted_content="User might change job soon",
        confidence=0.88,
    )

    decision = gate.evaluate(request)

    assert decision.decision == "deny"
    assert decision.reason == "speculative_content"


def test_memory_write_gate_defers_short_lived_context():
    gate = MemoryWriteGate()
    request = MemoryWriteRequest(
        source_text="for now, use this temporary endpoint today",
        proposed_memory_type="project_state",
        extracted_content="temporary endpoint for today",
        confidence=0.9,
    )

    decision = gate.evaluate(request)

    assert decision.decision == "defer"
    assert decision.target_memory_layer == "working_memory"
    assert decision.reason == "short_lived_context"


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
