from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.memory_service import MemoryService
from memory.adapter import MemoryAdapter


def test_layer_maintenance_cadence_is_not_owned_by_hippocampus_config():
    adapter = MemoryAdapter.__new__(MemoryAdapter)
    adapter._maintenance_defaults = {
        "cluster_every_messages": 12,
        "cluster_min_interval_s": 300,
        "idle_cluster_delay_s": 120,
        "idle_cluster_min_messages": 2,
        "idle_cluster_min_interval_s": 60,
        "summary_min_interval_s": 600,
        "decay_interval_s": 86400,
    }
    config = SimpleNamespace(
        memory=SimpleNamespace(
            warm_layer=SimpleNamespace(
                cluster_every_messages=8,
                cluster_min_interval_s=80,
                idle_cluster_delay_s=40,
                idle_cluster_min_messages=3,
                idle_cluster_min_interval_s=20,
            ),
            cold_layer=SimpleNamespace(summary_min_interval_s=700),
            forgetting=SimpleNamespace(decay_interval_s=90000),
            hippocampus=SimpleNamespace(
                cluster_every_messages=99,
                summary_min_interval_s=999,
                decay_interval_s=999,
            ),
        )
    )

    adapter._load_maintenance_defaults_from_config(config)

    assert adapter._maintenance_defaults == {
        "cluster_every_messages": 8,
        "cluster_min_interval_s": 80,
        "idle_cluster_delay_s": 40,
        "idle_cluster_min_messages": 3,
        "idle_cluster_min_interval_s": 20,
        "summary_min_interval_s": 700,
        "decay_interval_s": 90000,
    }


def test_foreground_run_key_prefers_request_id_when_trace_id_is_not_on_finish_event():
    started = SimpleNamespace(payload={"request_id": "request-1", "trace_id": "trace-1"})
    finished = SimpleNamespace(payload={"request_id": "request-1"})

    assert MemoryService._foreground_run_key(started) == "request-1"
    assert MemoryService._foreground_run_key(finished) == "request-1"


@pytest.mark.asyncio
async def test_replay_reflection_requires_non_replay_memory_and_only_updates_replay_entries():
    service = MemoryService.__new__(MemoryService)

    async def llm_call(*_args):
        return json.dumps(
            {
                "insights": [
                    {
                        "content": "Self-reinforcing claim",
                        "type": "preference",
                        "basis_memory_ids": ["r1"],
                        "target_memory_id": "r1",
                    },
                    {
                        "content": "New grounded understanding",
                        "type": "preference",
                        "basis_memory_ids": ["m1"],
                        "target_memory_id": "m1",
                    },
                    {
                        "content": "Revised grounded understanding",
                        "type": "preference",
                        "basis_memory_ids": ["m1", "r1"],
                        "target_memory_id": "r1",
                    },
                ]
            }
        )

    service._call_memory_classifier_llm = llm_call
    memories = [
        {"memory_id": "m1", "content": "Direct memory", "memory_type": "preference", "metadata": {}},
        {
            "memory_id": "r1",
            "content": "Earlier replay insight",
            "memory_type": "preference",
            "metadata": {"memory_source": "hippocampus.replay"},
        },
    ]

    insights = await service._reflect_replay_memories(
        "u1",
        memories,
        4,
        [{"content": "A temporary interpretation", "basis_memory_ids": ["m1"]}],
    )

    assert len(insights) == 2
    assert insights[0]["target_memory_id"] is None
    assert insights[1]["target_memory_id"] == "r1"
    assert all("m1" in item["basis_memory_ids"] for item in insights)


@pytest.mark.asyncio
async def test_only_grounded_non_degraded_cognition_is_offered_to_replay():
    offered = []

    class _Hippocampus:
        async def offer_cognition_hint(self, user_id, hint):
            offered.append((user_id, hint))
            return True

    service = MemoryService.__new__(MemoryService)
    service.hippocampus = _Hippocampus()
    accepted = await service.offer_cognition_snapshot(
        user_id="u1",
        snapshot={
            "synthesis": "A grounded temporary interpretation",
            "basis_memory_ids": ["m1", "m2"],
            "metrics": {"llm_calls": 2, "degraded": False},
        },
    )
    rejected = await service.offer_cognition_snapshot(
        user_id="u1",
        snapshot={
            "synthesis": "A deterministic fallback",
            "basis_memory_ids": ["m1"],
            "metrics": {"llm_calls": 0, "degraded": False},
        },
    )

    assert accepted is True
    assert rejected is False
    assert offered == [
        (
            "u1",
            {
                "content": "A grounded temporary interpretation",
                "basis_memory_ids": ["m1", "m2"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_replay_commit_upserts_existing_fingerprint_instead_of_appending():
    adapter = MagicMock()
    adapter.list_memory_entries.return_value = [
        {
            "memory_id": "existing",
            "content": "Earlier wording",
            "metadata": {
                "memory_source": "hippocampus.replay",
                "replay_fingerprint": "same-fingerprint",
            },
        }
    ]
    adapter.update_memory_entry.return_value = {"ok": True}
    service = MemoryService.__new__(MemoryService)
    service.memory_adapter = adapter

    saved = await service._commit_replay_insight(
        "u1",
        {
            "content": "Refined wording",
            "memory_type": "preference",
            "fingerprint": "same-fingerprint",
            "basis_memory_ids": ["m1"],
        },
        3,
    )

    assert saved is True
    adapter.update_memory_entry.assert_called_once()
    assert adapter.update_memory_entry.call_args.kwargs["memory_id"] == "existing"
    adapter.add_message.assert_not_called()
