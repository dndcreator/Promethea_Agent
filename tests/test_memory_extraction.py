import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from gateway.memory_extraction import classify_interaction, verify_candidates
from gateway.memory_service import MemoryService


@pytest.mark.asyncio
async def test_classification_only_returns_normalized_candidates():
    call = AsyncMock(return_value=json.dumps({"has_long_term_state": True, "candidates": [
        {"type": "preference", "content": "Keep answers short", "modality": "actual", "persistence": "durable"},
        {"type": "unsupported", "content": "discard"},
    ]}))
    out = await classify_interaction(call, "Keep answers short", "Understood", "u1", interaction_context=[])
    assert out["has_long_term_state"] is True and len(out["candidates"]) == 1
    assert out["candidates"][0]["persistence"] == "durable"
    assert call.await_args.args[0] == "u1"


@pytest.mark.asyncio
async def test_verification_preserves_semantic_scope_without_writing_or_mutating():
    candidates = [{"type": "goal", "content": "Visit Shanghai", "related_memories": [{"id": "old"}]}]
    original = deepcopy(candidates)
    call = AsyncMock(return_value=json.dumps({"decisions": [{"index": 0, "accept": True, "confidence": 0.9,
        "attribution": "user", "modality": "hypothetical", "persistence": "ephemeral", "relationship": "compatible",
        "related_indexes": [0, 0, 99]}]}))
    out = await verify_candidates(call, "u1", "I might visit Shanghai", "Maybe", candidates)
    assert candidates == original
    assert out[0]["modality"] == "hypothetical" and out[0]["persistence"] == "ephemeral"
    assert out[0]["relationship_indexes"] == [0]


@pytest.mark.asyncio
async def test_malformed_verifier_response_uses_existing_overlap_fallback():
    call = AsyncMock(return_value="not json")
    out = await verify_candidates(call, "u1", "I prefer short answers", "Understood", [{"content": "short answers"}])
    assert out[0]["verify_reason"] == "fallback_overlap"


@pytest.mark.asyncio
async def test_service_keeps_pre_extraction_gate(monkeypatch):
    monkeypatch.setattr(MemoryService, "_create_hippocampus_service", lambda self: None)
    service = MemoryService(memory_adapter=object())
    monkeypatch.setattr(service, "_should_run_memory_llm", lambda *_args, **_kwargs: False)
    service._call_memory_classifier_llm = AsyncMock()
    assert await service._classify_interaction("hello", "hello", "u1") == {"has_long_term_state": False, "candidates": []}
    service._call_memory_classifier_llm.assert_not_called()
