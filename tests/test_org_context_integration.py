from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.conversation_service import ConversationService


class _DummyCore:
    async def run_chat_loop(self, messages, user_config=None, session_id=None, user_id=None, tool_executor=None):
        _ = (messages, user_config, session_id, user_id, tool_executor)
        return {"status": "success", "content": "ok"}

    async def call_llm(self, messages, user_config=None, user_id=None):
        _ = (messages, user_config, user_id)
        return {"content": '{"recall": false}'}


class _ConfigSvc:
    def get_merged_config(self, user_id):
        _ = user_id
        return {
            "prompts": {"Promethea_system_prompt": "You are Promethea."},
            "org_brain": {"enabled": True, "org_id": "org_demo"},
        }

    def get_user_config(self, user_id):
        _ = user_id
        return {
            "agent_name": "Promethea",
            "org_brain": {"enabled": True, "org_id": "org_demo", "audience_default": "board"},
        }


class _OrgSvc:
    async def recall_for_turn(self, **kwargs):
        _ = kwargs
        return {
            "enabled": True,
            "recalled": True,
            "org_id": "org_demo",
            "audience": "board",
            "summary_text": (
                "Organization context hints:\n"
                "- [board/formal] three-pillar-strategy: emphasize long-term resilient growth"
            ),
            "recall_priority": "blend",
        }


@pytest.mark.asyncio
async def test_prepare_chat_turn_includes_org_context_in_system_prompt():
    svc = ConversationService(
        conversation_core=_DummyCore(),
        config_service=_ConfigSvc(),
        org_context_service=_OrgSvc(),
    )
    out = await svc.prepare_chat_turn(
        session_id="s1",
        user_id="u1",
        user_message="Please draft a strategy report.",
        channel="web",
        include_recent=False,
        run_context=SimpleNamespace(input_payload={"metadata": {"audience": "board"}}),
    )
    system_prompt = out.get("system_prompt") or ""
    assert "organization context hints" in system_prompt.lower()
    assert (out.get("org_context") or {}).get("recalled") is True
