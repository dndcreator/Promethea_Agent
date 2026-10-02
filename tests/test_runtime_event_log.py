import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gateway.events import EventEmitter
from gateway.memory_service import MemoryService
from gateway.protocol import EventType
from gateway.runtime_event_log import RuntimeEventLog


def test_runtime_event_log_persists_before_delivery(tmp_path: Path):
    log = RuntimeEventLog(storage_path=str(tmp_path / "events.jsonl"))
    emitter = EventEmitter(event_log=log)
    observed = []

    async def listener(event):
        observed.extend(log.query(task_id="task_1"))

    emitter.on(EventType.INTERACTION_COMPLETED, listener)
    asyncio.run(emitter.emit(EventType.INTERACTION_COMPLETED, {"user_id": "u1", "session_id": "s1", "task_id": "task_1", "trace_id": "t1", "user_input": "remember this"}))
    assert observed and observed[0]["event_type"] == "interaction.completed"
    assert observed[0]["task_id"] == "task_1"


def test_runtime_event_log_restores_sequence_and_redacts_secrets(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    first = RuntimeEventLog(storage_path=str(path))
    first.append(
        event_type="config.changed",
        payload={
            "user_id": "u1",
            "config": {"api_key": "secret", "provider": {"access_token": "token"}},
        },
    )

    restored = RuntimeEventLog(storage_path=str(path))
    second = restored.append(event_type="health.update", payload={"user_id": "u1"})
    rows = restored.query(user_id="u1", limit=10, oldest_first=True)

    assert second["seq"] == 2
    assert rows[0]["payload"]["config"]["api_key"] == "[REDACTED]"
    assert rows[0]["payload"]["config"]["provider"]["access_token"] == "[REDACTED]"


def test_runtime_event_log_rotates_with_bounded_archives(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    log = RuntimeEventLog(storage_path=str(path), max_bytes=220, max_archives=2)
    for index in range(12):
        log.append(event_type="health.update", payload={"index": index, "value": "x" * 80})

    artifacts = list(tmp_path.glob("events.jsonl*"))
    data_files = [item for item in artifacts if ".state." not in item.name]
    assert len(data_files) <= 3
    assert log.query(event_type="health.update", limit=20)


@pytest.mark.asyncio
async def test_interaction_log_failure_prevents_memory_delivery_without_breaking_chat():
    failed_log = MagicMock()
    failed_log.next_seq = 1
    failed_log.append.side_effect = OSError("disk full")
    emitter = EventEmitter(event_log=failed_log)
    observed = []
    emitter.on(EventType.INTERACTION_COMPLETED, lambda event: observed.append(event))

    await emitter.emit(EventType.INTERACTION_COMPLETED, {"session_id": "s1"})

    assert observed == []


@pytest.mark.asyncio
async def test_memory_consumer_replays_only_uncommitted_interactions(tmp_path: Path, monkeypatch):
    path = tmp_path / "events.jsonl"
    log = RuntimeEventLog(storage_path=str(path))
    emitter = EventEmitter(event_log=log)
    adapter = MagicMock()
    adapter.is_enabled.return_value = True
    service = MemoryService(event_emitter=emitter, memory_adapter=adapter)
    processed = []

    async def process(payload):
        processed.append(payload["user_input"])

    monkeypatch.setattr(service, "_process_interaction_completed", process)
    await emitter.emit(
        EventType.INTERACTION_COMPLETED,
        {"user_id": "u1", "session_id": "s1", "user_input": "first", "assistant_output": "ok"},
    )
    assert await service.wait_until_idle(timeout_s=2)
    assert processed == ["first"]

    log.append(
        event_type=EventType.INTERACTION_COMPLETED.value,
        payload={"user_id": "u1", "session_id": "s1", "user_input": "second", "assistant_output": "ok"},
    )
    restored_emitter = EventEmitter(event_log=RuntimeEventLog(storage_path=str(path)))
    restored = MemoryService(event_emitter=restored_emitter, memory_adapter=adapter)
    replayed = []

    async def replay_process(payload):
        replayed.append(payload["user_input"])

    monkeypatch.setattr(restored, "_process_interaction_completed", replay_process)
    assert await restored.replay_pending_runtime_events() == 1
    assert await restored.wait_until_idle(timeout_s=2)
    assert replayed == ["second"]
