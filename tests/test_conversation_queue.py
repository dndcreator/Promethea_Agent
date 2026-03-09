import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gateway.conversation_service import ConversationService


class _FakeConversationCore:
    def __init__(self, fail_once: bool = False):
        self.fail_once = fail_once
        self.run_calls = 0
        self.call_order = []
        self.user_messages = []

    async def run_chat_loop(self, messages, user_config=None, session_id=None):
        self.run_calls += 1
        self.call_order.append(session_id)
        if messages:
            self.user_messages.append(messages[-1].get("content"))
        if self.fail_once and self.run_calls == 1:
            raise RuntimeError("transient failure")
        await asyncio.sleep(0.01)
        return {"content": "ok", "status": "success"}

    async def call_llm(self, messages, user_config=None):
        return {"content": "{\"recall\": false}"}


def _build_message_manager():
    mgr = MagicMock()
    mgr.get_session.return_value = True
    mgr.get_recent_messages.return_value = [{"role": "user", "content": "hello"}]
    mgr.begin_turn.return_value = True
    mgr.commit_turn.return_value = True
    mgr.abort_turn.return_value = True
    return mgr


def _build_config_service():
    cfg = MagicMock()
    cfg.get_merged_config.return_value = {
        "prompts": {"Promethea_system_prompt": "system"},
        "conversation": {
            "processing": {
                "max_queue_size": 8,
                "max_retries": 2,
                "retry_base_delay_s": 0.01,
                "retry_max_delay_s": 0.05,
                "worker_idle_ttl_s": 0.05,
            }
        },
    }
    cfg.get_user_config.return_value = {}
    return cfg


@pytest.mark.asyncio
async def test_conversation_retries_on_failure():
    core = _FakeConversationCore(fail_once=True)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    event = SimpleNamespace(
        payload={"content": "hello", "sender": "u1", "channel": "web"}
    )
    await svc._on_channel_message(event)

    for _ in range(100):
        stats = svc.get_processing_stats()
        if stats["queued_messages"] == 0 and stats["active_workers"] == 0:
            break
        await asyncio.sleep(0.02)

    assert core.run_calls == 2


@pytest.mark.asyncio
async def test_conversation_queue_serial_per_session():
    core = _FakeConversationCore(fail_once=False)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    e1 = SimpleNamespace(payload={"content": "m1", "sender": "u1", "channel": "web"})
    e2 = SimpleNamespace(payload={"content": "m2", "sender": "u1", "channel": "web"})
    await svc._on_channel_message(e1)
    await svc._on_channel_message(e2)

    for _ in range(100):
        stats = svc.get_processing_stats()
        if stats["queued_messages"] == 0 and stats["active_workers"] == 0:
            break
        await asyncio.sleep(0.02)

    assert core.run_calls == 2
    assert core.call_order == ["web_u1", "web_u1"]


@pytest.mark.asyncio
async def test_conversation_queue_collect_coalesces_backlog():
    core = _FakeConversationCore(fail_once=False)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    e1 = SimpleNamespace(
        payload={"content": "m1", "sender": "u1", "channel": "web", "queue_mode": "collect"}
    )
    e2 = SimpleNamespace(
        payload={"content": "m2", "sender": "u1", "channel": "web", "queue_mode": "collect"}
    )
    await svc._on_channel_message(e1)
    await svc._on_channel_message(e2)

    for _ in range(100):
        stats = svc.get_processing_stats()
        if stats["queued_messages"] == 0 and stats["active_workers"] == 0:
            break
        await asyncio.sleep(0.02)

    assert core.run_calls == 1
    assert core.user_messages[-1] == "m2"


@pytest.mark.asyncio
async def test_conversation_queue_steer_backlog_marks_urgent_slot():
    core = _FakeConversationCore(fail_once=False)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    policy = svc._resolve_processing_policy("u1")
    ok = await svc._enqueue_message(
        session_id="web_u1",
        item={
            "session_id": "web_u1",
            "user_id": "u1",
            "content": "m3",
            "channel": "web",
            "turn_id": "t3",
            "attempt": 0,
            "enqueued_at": 0.0,
            "queue_mode": "steer_backlog",
        },
        policy=policy,
    )
    assert ok is True
    stats = svc.get_processing_stats()
    assert stats["urgent_sessions"] >= 1

@pytest.mark.asyncio
async def test_conversation_queue_command_sets_mode_and_trims_prefix():
    core = _FakeConversationCore(fail_once=False)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    e = SimpleNamespace(
        payload={"content": "/queue collect only latest", "sender": "u1", "channel": "web"}
    )
    await svc._on_channel_message(e)

    for _ in range(100):
        stats = svc.get_processing_stats()
        if stats["queued_messages"] == 0 and stats["active_workers"] == 0:
            break
        await asyncio.sleep(0.02)

    assert core.run_calls == 1
    assert core.user_messages[-1] == "only latest"


@pytest.mark.asyncio
async def test_conversation_queue_overflow_drop_oldest_keeps_new_message():
    core = _FakeConversationCore(fail_once=False)
    svc = ConversationService(
        event_emitter=None,
        conversation_core=core,
        memory_service=None,
        message_manager=_build_message_manager(),
        config_service=_build_config_service(),
    )

    policy = svc._resolve_processing_policy("u1")
    policy["max_queue_size"] = 1
    policy["queue_overflow_mode"] = "drop_oldest"

    ok1 = await svc._enqueue_message(
        session_id="web_u1",
        item={
            "session_id": "web_u1",
            "user_id": "u1",
            "content": "old",
            "channel": "web",
            "turn_id": "t1",
            "attempt": 0,
            "enqueued_at": 0.0,
            "queue_mode": "followup",
        },
        policy=policy,
    )
    ok2 = await svc._enqueue_message(
        session_id="web_u1",
        item={
            "session_id": "web_u1",
            "user_id": "u1",
            "content": "new",
            "channel": "web",
            "turn_id": "t2",
            "attempt": 0,
            "enqueued_at": 0.0,
            "queue_mode": "followup",
        },
        policy=policy,
    )

    assert ok1 is True
    assert ok2 is True

    for _ in range(100):
        stats = svc.get_processing_stats()
        if stats["queued_messages"] == 0 and stats["active_workers"] == 0:
            break
        await asyncio.sleep(0.02)

    assert "new" in core.user_messages
    assert svc.get_processing_stats()["queue_dropped"] >= 1
