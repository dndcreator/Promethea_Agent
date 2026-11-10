"""Explicit, public GitHub read acceptance. No product credentials or model calls."""
import json
import os
from pathlib import Path
import time

import pytest

from agentkit.tools import github
from gateway.protocol import EventType
from gateway.public_contracts import AmbientSettings
from tests.test_continuous_observation import host_at


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("PROMETHEA_LIVE_GITHUB_REPO"), reason="explicit public GitHub read opt-in")
async def test_public_ci_enters_actual_ambient_without_model_request(tmp_path, monkeypatch):
    # Intentionally anonymous: do not borrow the operator's or a user's token.
    monkeypatch.setattr(github, "load_user_secrets", lambda *args, **kwargs: {})
    tasks, runtime, conversation, _, ambient, _, kernel, server = host_at(tmp_path)
    conversation.capability_service.register_tool(github.GitHubCIChangesTool())
    try:
        ambient.configure("alice", "chat", AmbientSettings(enabled=True, direction="Maintain repository reliability"))
        from gateway.capability_service import ToolInvocationContext
        created = await conversation.capability_service.call_tool("runtime.schedule", {
            "name": "Public CI acceptance", "service_name": "github", "tool_name": "observe_ci", "interval_seconds": 300,
            "observe": True, "args": {"repository": os.environ["PROMETHEA_LIVE_GITHUB_REPO"], "branch": "develop"}},
            ctx=ToolInvocationContext(user_id="alice", session_id="chat"))
        result = await kernel._cron.run_due_jobs_internal(now_ts=time.time() + 305)
        assert result["ran"][0]["ok"], result
        ambient.recover()
        task = tasks.execution_tasks(run_type="ambient")[0]
        refs = task["runs"][0]["metadata"]["events"]
        assert refs
        facts = ambient.self_model.working_context("alice", triggers=refs)["trigger_observations"]
        assert all(fact for fact in facts)
        assert conversation.conversation_core.requests == []
        assert server.event_emitter.event_log.query(event_type=EventType.ENVIRONMENT_STATE_CHANGED.value)
        output = Path(".tmp/github-autonomy-public-read")
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps({"repository": os.environ["PROMETHEA_LIVE_GITHUB_REPO"],
            "job_id": created["job"]["job_id"], "task_id": task["task_id"], "observations": facts,
            "model_calls": 0, "source_calls_ok": True, "status": "admitted_not_executed"}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await runtime.shutdown()
