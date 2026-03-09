from __future__ import annotations

import pytest

from agentkit.tools.runtime_tools.runtime_tools import RuntimeToolsService


@pytest.mark.asyncio
async def test_sessions_action_list_returns_shape():
    svc = RuntimeToolsService()
    out = await svc.sessions_action(action="list", user_id="default_user")
    assert "ok" in out
    assert "sessions" in out


@pytest.mark.asyncio
async def test_agents_action_list_returns_shape():
    svc = RuntimeToolsService()
    out = await svc.agents_action(action="list")
    assert out["ok"] is True
    assert "agents" in out


@pytest.mark.asyncio
async def test_plugins_action_list_returns_shape():
    svc = RuntimeToolsService()
    out = await svc.plugins_action(action="list")
    assert out["ok"] is True
    assert "plugins" in out
