import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.org_context_extraction import chunk_text, extract_context_items


async def extract(client, **overrides):
    options = dict(text="Organization policy requires careful review.", audience=" board ", register=" formal ",
                   use_llm=True, extract_text_max_chars=5000, heuristic_max_lines=30, heuristic_max_items=15,
                   user_config={"org_brain": {"enabled": True}}, user_id="u1")
    return await extract_context_items(client, **{**options, **overrides})


def test_chunking_keeps_document_order_and_limits():
    text = "a" * 510 + "\n" + "b" * 700
    chunks = chunk_text(text, chunk_chars=600, max_chunks=2)
    assert chunks[0] == "a" * 510
    assert chunks[1] == "b" * 599
    assert chunk_text("  ", chunk_chars=600, max_chunks=2) == []


@pytest.mark.asyncio
async def test_model_extraction_uses_current_client_and_has_no_publication_state():
    client = SimpleNamespace(call_llm=AsyncMock(return_value={"content": json.dumps({"items": [
        {"concept": " Review ", "expression": " Review   all changes ", "confidence": 0.8},
        {"concept": "", "expression": "discard"},
    ]})}))
    rows = await extract(client)
    assert rows == [{"concept": "Review", "expression": "Review all changes", "knowledge_kind": "fact",
                     "audience": "board", "register": "formal", "terms_locked": [], "confidence": 0.8}]
    assert client.call_llm.await_args.kwargs["user_id"] == "u1"
    assert "revision_id" not in rows[0] and "status" not in rows[0]


@pytest.mark.asyncio
async def test_failure_and_disabled_llm_preserve_bounded_heuristic_behavior():
    client = SimpleNamespace(call_llm=AsyncMock(side_effect=RuntimeError("offline")))
    failed = await extract(client, text="First policy sentence.\nSecond policy sentence.", heuristic_max_items=1)
    assert len(failed) == 1 and failed[0]["confidence"] == 0.45
    client.call_llm.reset_mock()
    disabled = await extract(client, text="First policy sentence.", use_llm=False)
    assert disabled == failed
    client.call_llm.assert_not_called()
