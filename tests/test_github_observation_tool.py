"""Provider fixtures test pagination/recovery, not the Agent's prioritization."""
from copy import deepcopy

import pytest

from agentkit.tools import github
from gateway.capability_service import ToolInvocationContext


def run(identifier, status="completed", conclusion="success", attempt=1):
    return {"id": identifier, "name": "CI", "head_branch": "develop", "head_sha": "sha-" + str(identifier),
            "run_attempt": attempt, "status": status, "conclusion": conclusion,
            "updated_at": "2026-11-03T00:00:00Z", "html_url": f"https://github.com/owner/repo/actions/runs/{identifier}"}


@pytest.mark.asyncio
async def test_initial_window_then_failure_recovery_and_old_active_completion(monkeypatch):
    rows = [run(10), run(9), run(8, "in_progress", None), run(7), run(6), run(5)]
    async def read(repository, resource, user, query=None):
        if resource.endswith("/8"):
            return run(8, conclusion="failure")
        return {"workflow_runs": deepcopy(rows)}
    monkeypatch.setattr(github, "read_api", read)
    tool, ctx = github.GitHubCIChangesTool(), ToolInvocationContext(user_id="alice")
    first = await tool.invoke({"repository": "owner/repo"}, ctx)
    assert len(first["observations"]) == 5 and first["cursor"]["active_run_ids"] == [8]
    rows = [run(11, conclusion="failure"), run(10)]
    second = await tool.invoke({"repository": "owner/repo", "cursor": first["cursor"]}, ctx)
    assert {row["data"]["id"] for row in second["observations"]} == {8, 10, 11}
    assert second["cursor"] == {"high_run_id": 11, "active_run_ids": []}
    rows = [run(11, attempt=2), run(10)]
    third = await tool.invoke({"repository": "owner/repo", "cursor": second["cursor"]}, ctx)
    changed = next(row for row in third["observations"] if row["data"]["id"] == 11)
    old = next(row for row in second["observations"] if row["data"]["id"] == 11)
    assert changed["version"] != old["version"] and changed["data"]["conclusion"] == "success"


@pytest.mark.asyncio
async def test_burst_catchup_advances_only_through_returned_new_runs(monkeypatch):
    rows = [run(number) for number in range(250, 0, -1)]
    queries = []
    async def read(repository, resource, user, query=None):
        queries.append(query)
        start = (query["page"] - 1) * 100
        return {"workflow_runs": deepcopy(rows[start:start + 100])}
    monkeypatch.setattr(github, "read_api", read)
    cursor, seen = {"high_run_id": 10}, set()
    while cursor["high_run_id"] < 250:
        value = await github.GitHubCIChangesTool().invoke({"repository": "owner/repo", "cursor": cursor}, ToolInvocationContext(user_id="alice"))
        seen.update(row["data"]["id"] for row in value["observations"] if row["data"]["id"] > 10)
        cursor = value["cursor"]
    assert set(range(11, 251)).issubset(seen)
    assert any(query["page"] == 3 for query in queries)


@pytest.mark.asyncio
async def test_incomplete_poll_and_credentials_never_advance_source_cursor(monkeypatch):
    calls = []
    async def read(repository, resource, user, query=None):
        calls.append(query)
        return {"workflow_runs": [run(number) for number in range(2000, 1900, -1)]}
    monkeypatch.setattr(github, "read_api", read)
    cursor = {"high_run_id": 1}
    with pytest.raises(RuntimeError, match="catch-up"):
        await github.GitHubCIChangesTool().invoke({"repository": "owner/repo", "cursor": cursor}, ToolInvocationContext(user_id="alice"))
    assert cursor == {"high_run_id": 1} and len(calls) == 10


@pytest.mark.asyncio
async def test_read_only_adapter_uses_owner_token_and_fixed_origin(monkeypatch):
    from types import SimpleNamespace
    sent = []
    monkeypatch.setattr(github, "load_user_secrets", lambda user, ensure: {"GITHUB__TOKEN": user + "-private"})
    async def request(url, **kwargs):
        sent.append((url, kwargs))
        return SimpleNamespace(status=200, body=b'{}')
    monkeypatch.setattr(github, "request_document", request)
    await github.read_api("owner/repo", "actions/runs", "alice")
    assert sent[0][1]["headers"]["Authorization"] == "Bearer alice-private"
    assert sent[0][1]["same_origin"] is True
    with pytest.raises(ValueError):
        await github.read_api("../secrets", "actions/runs", "bob")
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_signed_log_download_never_forwards_github_credentials(monkeypatch):
    from types import SimpleNamespace
    calls = []
    async def api(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        return SimpleNamespace(status=302, headers={"Location": "https://logs.example.test/signed"})
    async def download(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status=200, body=b"step failed\n" * 100)
    monkeypatch.setattr(github, "api_document", api)
    monkeypatch.setattr(github, "request_document", download)
    result = await github.GitHubReadCITool().invoke({"repository": "owner/repo", "kind": "job_log", "job_id": 9, "max_chars": 100}, ToolInvocationContext(user_id="alice"))
    assert "step failed" in result["content"] and result["next_offset"] == 100
    assert "headers" not in calls[0][1]
    assert "signed" not in str(result)
