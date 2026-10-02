from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from memory.hippocampus import HippocampusReplayPolicy, HippocampusReplayService


def _policy(tmp_path: Path, **overrides) -> HippocampusReplayPolicy:
    values = {
        "state_path": str(tmp_path / "replay_state.json"),
        "new_memory_threshold": 2,
        "min_interval_s": 0,
        "max_interval_s": 3600,
        "revisit_interval_s": 7 * 24 * 3600,
        "idle_delay_s": 0,
        "poll_interval_s": 3600,
        "batch_size": 4,
        "max_insights_per_cycle": 2,
        "retry_delay_s": 10,
    }
    values.update(overrides)
    return HippocampusReplayPolicy(**values)


@pytest.mark.asyncio
async def test_replay_runs_due_batch_and_persists_checkpointed_state(tmp_path: Path):
    committed = []
    events = []
    memories = [
        {"memory_id": "m1", "content": "Prefers concise answers", "memory_type": "preference"},
        {"memory_id": "m2", "content": "Requests direct explanations", "memory_type": "preference"},
    ]

    async def reflect(_user_id, selected, _limit, hints):
        assert selected == memories
        assert hints == []
        return [{"content": "Prefers direct, concise answers", "fingerprint": "f1"}]

    async def publish(event_type, payload):
        events.append((event_type, payload))

    service = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=lambda _user_id, _limit, _hints: memories,
        reflect=reflect,
        commit_insight=lambda user_id, insight, cycle: committed.append((user_id, insight, cycle)),
        publish_event=publish,
    )
    state = service._user_state("u1")
    state["pending_memories"] = 2

    result = await service.run_once()

    assert result["ran"][0]["committed_count"] == 1
    assert committed[0][0] == "u1"
    assert [event[0] for event in events] == [
        "memory.replay.started",
        "memory.replay.checkpointed",
        "memory.replay.completed",
    ]
    persisted = json.loads((tmp_path / "replay_state.json").read_text(encoding="utf-8"))
    assert persisted["users"]["u1"]["status"] == "idle"
    assert persisted["users"]["u1"]["checkpoint"] is None


@pytest.mark.asyncio
async def test_cognition_hint_is_checkpointed_used_and_consumed(tmp_path: Path):
    memories = [
        {"memory_id": "m1", "content": "Prefers concise answers"},
        {"memory_id": "m2", "content": "Requests direct explanations"},
    ]
    observed = {}

    async def select(_user_id, _limit, hints):
        observed["selected_hints"] = hints
        return memories

    async def reflect(_user_id, selected, _limit, hints):
        observed["reflected_hints"] = hints
        assert selected == memories
        return []

    service = HippocampusReplayService(
        policy=_policy(tmp_path, cognition_hint_threshold=2),
        select_memories=select,
        reflect=reflect,
        commit_insight=lambda *_args: True,
    )

    accepted = await service.offer_cognition_hint(
        "u1",
        {"content": "The user likely values concise and direct answers", "basis_memory_ids": ["m1", "m2"]},
    )
    assert accepted is True
    queued = service.get_status(user_id="u1")["users"]["u1"]["cognition_hints"]
    assert len(queued) == 1

    result = await service.run_once(user_id="u1", force=True)

    assert result["ran"][0]["status"] == "completed"
    assert observed["selected_hints"] == observed["reflected_hints"]
    assert observed["reflected_hints"][0]["basis_memory_ids"] == ["m1", "m2"]
    assert service.get_status(user_id="u1")["users"]["u1"]["cognition_hints"] == []


@pytest.mark.asyncio
async def test_replay_waits_while_foreground_resources_are_busy(tmp_path: Path):
    selected = 0

    def select(_user_id, _limit):
        nonlocal selected
        selected += 1
        return []

    service = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=select,
        reflect=lambda *_args: [],
        commit_insight=lambda *_args: True,
        idle_probe=lambda: False,
    )
    service._user_state("u1")["pending_memories"] = 2

    result = await service.run_once()

    assert result["reason"] == "resources_busy"
    assert selected == 0


@pytest.mark.asyncio
async def test_below_threshold_does_not_start_background_worker(tmp_path: Path):
    service = HippocampusReplayService(
        policy=_policy(tmp_path, new_memory_threshold=3),
        select_memories=lambda *_args: [],
        reflect=lambda *_args: [],
        commit_insight=lambda *_args: True,
    )

    await service.notify_memory_saved("u1", 2)

    assert service.get_status()["running"] is False
    assert service.get_status(user_id="u1")["users"]["u1"]["pending_memories"] == 2


@pytest.mark.asyncio
async def test_pending_memory_runs_after_maximum_wait_without_reaching_threshold(tmp_path: Path):
    selected = []
    memories = [{"memory_id": "m1"}, {"memory_id": "m2"}]
    service = HippocampusReplayService(
        policy=_policy(tmp_path, new_memory_threshold=10, max_interval_s=60),
        select_memories=lambda *_args: selected.append(True) or memories,
        reflect=lambda *_args: [],
        commit_insight=lambda *_args: True,
    )
    state = service._user_state("u1")
    state.update({"pending_memories": 1, "last_activity_at": time.time() - 61})

    result = await service.run_once()

    assert result["ran"][0]["status"] == "completed"
    assert selected == [True]


@pytest.mark.asyncio
async def test_completed_memory_is_revisited_on_low_frequency_schedule(tmp_path: Path):
    selected = []
    memories = [{"memory_id": "m1"}, {"memory_id": "m2"}]
    service = HippocampusReplayService(
        policy=_policy(tmp_path, new_memory_threshold=10, revisit_interval_s=60),
        select_memories=lambda *_args: selected.append(True) or memories,
        reflect=lambda *_args: [],
        commit_insight=lambda *_args: True,
    )
    state = service._user_state("u1")
    state.update(
        {
            "pending_memories": 0,
            "last_activity_at": time.time() - 120,
            "last_run_at": time.time() - 61,
            "cycle": 1,
        }
    )

    result = await service.run_once()

    assert result["ran"][0]["status"] == "completed"
    assert selected == [True]


def test_corrupt_replay_state_fails_loudly(tmp_path: Path):
    (tmp_path / "replay_state.json").write_text("not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="could not be loaded"):
        HippocampusReplayService(
            policy=_policy(tmp_path),
            select_memories=lambda *_args: [],
            reflect=lambda *_args: [],
            commit_insight=lambda *_args: True,
        )


@pytest.mark.asyncio
async def test_replay_resumes_from_persisted_commit_index_without_duplicate_work(tmp_path: Path):
    state_path = tmp_path / "replay_state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "users": {
                    "u1": {
                        "status": "committing",
                        "pending_memories": 2,
                        "last_activity_at": 0,
                        "last_run_at": 0,
                        "cycle": 0,
                        "checkpoint": {
                            "phase": "committing",
                            "selected_count": 2,
                            "insights": [{"content": "first"}, {"content": "second"}],
                            "next_index": 1,
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    committed = []
    service = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=lambda *_args: pytest.fail("selection must not repeat after checkpoint"),
        reflect=lambda *_args: pytest.fail("reflection must not repeat after checkpoint"),
        commit_insight=lambda _user_id, insight, _cycle: committed.append(insight["content"]),
    )

    result = await service.run_once(force=True)

    assert result["ran"][0]["committed_count"] == 2
    assert committed == ["second"]


@pytest.mark.asyncio
async def test_shutdown_interrupts_reflection_and_restart_can_retry(tmp_path: Path):
    reflection_started = asyncio.Event()

    async def blocking_reflect(*_args):
        reflection_started.set()
        await asyncio.Event().wait()

    memories = [{"memory_id": "m1"}, {"memory_id": "m2"}]
    service = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=lambda *_args: memories,
        reflect=blocking_reflect,
        commit_insight=lambda *_args: True,
    )
    service._user_state("u1")["pending_memories"] = 2
    await service.start()
    await asyncio.wait_for(reflection_started.wait(), timeout=1)

    await service.stop()

    persisted = json.loads((tmp_path / "replay_state.json").read_text(encoding="utf-8"))
    assert persisted["users"]["u1"]["status"] == "interrupted"

    committed = []
    restored = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=lambda *_args: memories,
        reflect=lambda *_args: [{"content": "recovered"}],
        commit_insight=lambda _user_id, insight, _cycle: committed.append(insight["content"]),
    )
    result = await restored.run_once(force=True)

    assert result["ran"][0]["status"] == "completed"
    assert committed == ["recovered"]


@pytest.mark.asyncio
async def test_foreground_run_interrupts_active_replay_and_restarts_supervisor(tmp_path: Path):
    reflection_started = asyncio.Event()

    async def blocking_reflect(*_args):
        reflection_started.set()
        await asyncio.Event().wait()

    memories = [{"memory_id": "m1"}, {"memory_id": "m2"}]
    service = HippocampusReplayService(
        policy=_policy(tmp_path),
        select_memories=lambda *_args: memories,
        reflect=blocking_reflect,
        commit_insight=lambda *_args: True,
    )
    service._user_state("u1")["pending_memories"] = 2
    await service.start()
    await asyncio.wait_for(reflection_started.wait(), timeout=1)

    await service.foreground_started("run-1")

    assert service.get_status(user_id="u1")["users"]["u1"]["status"] == "interrupted"
    assert service.get_status()["running"] is False

    await service.foreground_finished("run-1")
    assert service.get_status()["running"] is True
    await service.stop()
