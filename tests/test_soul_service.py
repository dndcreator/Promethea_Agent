from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.soul_service import (
    DEFAULT_SOUL_CONTENT,
    build_soul_response_payload,
    get_soul_profile,
    schedule_soul_evolution,
)


def test_get_soul_profile_defaults():
    profile = get_soul_profile({})
    assert profile["enabled"] is True
    assert profile["auto_evolve"] is True
    assert profile["read_only_in_ui"] is True
    assert profile["content"] == DEFAULT_SOUL_CONTENT


def test_build_soul_response_payload_uses_user_config():
    payload = build_soul_response_payload(
        {
            "persona": {
                "soul": {
                    "enabled": True,
                    "auto_evolve": False,
                    "read_only_in_ui": True,
                    "content": "my soul",
                    "version": 3,
                    "updated_at": "2026-04-08T00:00:00+00:00",
                }
            }
        }
    )
    assert payload["content"] == "my soul"
    assert payload["version"] == 3
    assert payload["auto_evolve"] is False


@pytest.mark.asyncio
async def test_schedule_soul_evolution_updates_config_when_due():
    class _ConfigService:
        def __init__(self):
            self.updates = []

        def get_merged_config(self, user_id):
            _ = user_id
            return {
                "persona": {
                    "soul": {
                        "enabled": True,
                        "auto_evolve": True,
                        "content": "old soul",
                        "version": 1,
                        "evolve_every_turns": 1,
                        "min_interval_seconds": 0,
                        "max_chars": 400,
                    }
                }
            }

        async def update_user_config(self, user_id, updates, validate=False):
            self.updates.append((user_id, updates, validate))
            return {"success": True}

    async def _call_llm(messages, user_config=None, user_id=None):
        _ = (messages, user_config, user_id)
        return {
            "content": '{"should_update": true, "next_soul": "new soul", "reason": "better fit"}'
        }

    cfg = _ConfigService()
    service = SimpleNamespace(
        config_service=cfg,
        call_llm=_call_llm,
    )

    await schedule_soul_evolution(
        service=service,
        user_id="u1",
        user_config=cfg.get_merged_config("u1"),
        user_message="I want a warmer tone.",
        assistant_message="Understood and done.",
    )
    task = service._soul_runtime_state["u1"]["task"]
    await task
    assert cfg.updates
    assert cfg.updates[0][1]["persona"]["soul"]["content"] == "new soul"

