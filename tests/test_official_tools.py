from pathlib import Path

import pytest

from gateway.events import EventEmitter
from gateway.official_tools import register_official_tools
from gateway.tool_service import ToolInvocationContext, ToolService
from gateway.workflow_engine import WorkflowEngine
from gateway.workspace_service import WorkspaceService


def _build_services(tmp_path: Path) -> tuple[ToolService, WorkspaceService]:
    workspace_service = WorkspaceService(base_dir=str(tmp_path / "ws"))
    tool_service = ToolService(event_emitter=EventEmitter())
    register_official_tools(tool_service=tool_service, workspace_service=workspace_service)
    return tool_service, workspace_service


class _DummyMessageManager:
    def get_recent_messages(self, session_id, count=None, user_id=None):
        _ = count
        return [{"role": "user", "content": f"hello:{session_id}:{user_id}"}]

    def get_session_info(self, session_id, user_id=None):
        return {"session_id": session_id, "user_id": user_id, "title": "demo"}

    def get_all_sessions_info(self, user_id=None):
        return {
            f"{user_id}::s1": {"session_id": "s1", "user_id": user_id, "last_activity": 2},
            f"{user_id}::s2": {"session_id": "s2", "user_id": user_id, "last_activity": 1},
        }


class _DummyMemoryService:
    async def get_context(self, query, session_id, user_id=None, run_context=None):
        _ = run_context
        return f"ctx:{user_id}:{session_id}:{query}"

    def list_entries(self, **kwargs):
        return {"ok": True, "entries": [{"memory_id": "m1", "content": "x"}], "args": kwargs}

    def create_entry(self, **kwargs):
        return {"ok": True, "args": kwargs}

    async def summarize_session(self, session_id, user_id=None, incremental=False):
        return {"session_id": session_id, "user_id": user_id, "incremental": bool(incremental)}

    def list_recall_runs(self, **kwargs):
        return [{"request_id": "r1", "kwargs": kwargs}]


class _DummyConversationService:
    def get_processing_stats(self):
        return {"sessions_with_queue": 0, "queued_messages": 0}


class _DummyGatewayServer:
    def __init__(self, *, workflow_engine=None, tool_service=None):
        self.conversation_service = _DummyConversationService()
        self.workflow_engine = workflow_engine
        self.tool_service = tool_service

    def get_services_health(self):
        return {"tool_service": True, "memory_service": True, "conversation_service": True}


@pytest.mark.asyncio
async def test_official_tools_registered(tmp_path: Path):
    tool_service, _ = _build_services(tmp_path)
    catalog = await tool_service.get_tool_catalog()
    assert any(row.get("tool_name") == "data.csv_to_json" for row in catalog)
    assert any(row.get("tool_name") == "data.json_to_csv" for row in catalog)
    assert any(row.get("tool_name") == "math.calculate" for row in catalog)
    assert not any(row.get("tool_name") == "memory.get_context" for row in catalog)
    assert any(row.get("tool_name") == "web.fetch_text" for row in catalog)
    assert any(row.get("tool_name") == "web.extract_links" for row in catalog)
    assert any(row.get("tool_name") == "workspace.copy_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.move_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.delete_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.list_files" for row in catalog)
    assert any(row.get("tool_name") == "workspace.read_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.write_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.search_text" for row in catalog)
    assert any(row.get("tool_name") == "workspace.ensure_dir" for row in catalog)
    assert any(row.get("tool_name") == "workspace.read_files" for row in catalog)
    assert any(row.get("tool_name") == "workspace.file_info" for row in catalog)
    assert any(row.get("tool_name") == "workspace.tail_file" for row in catalog)
    assert any(row.get("tool_name") == "workspace.replace_text" for row in catalog)
    assert any(row.get("tool_name") == "workspace.glob_files" for row in catalog)
    assert any(row.get("tool_name") == "text.word_stats" for row in catalog)
    assert any(row.get("tool_name") == "text.find_matches" for row in catalog)
    assert any(row.get("tool_name") == "text.normalize_json" for row in catalog)
    assert any(row.get("tool_name") == "utils.now" for row in catalog)
    assert any(row.get("tool_name") == "utils.uuid" for row in catalog)
    assert any(row.get("tool_name") == "utils.hash_text" for row in catalog)
    assert any(row.get("tool_name") == "web.fetch_json" for row in catalog)
    assert any(row.get("tool_name") == "web.search" for row in catalog)
    assert any(row.get("tool_name") == "web.download_to_workspace" for row in catalog)
    assert any(row.get("tool_name") == "runtime.exec_command" for row in catalog)
    assert any(row.get("tool_name") == "runtime.read_env" for row in catalog)


@pytest.mark.asyncio
async def test_official_tools_workspace_roundtrip(tmp_path: Path):
    tool_service, _ = _build_services(tmp_path)
    ctx = ToolInvocationContext(session_id="s1", user_id="u1")

    write_res = await tool_service.call_tool(
        "workspace.write_file",
        {"path": "notes/today.txt", "content": "alpha\nbeta\ngamma"},
        ctx=ctx,
    )
    assert write_res["operation"] in {"create", "update"}

    read_res = await tool_service.call_tool(
        "workspace.read_file",
        {"path": "notes/today.txt"},
        ctx=ctx,
    )
    assert "alpha" in read_res["content"]

    search_res = await tool_service.call_tool(
        "workspace.search_text",
        {"query": "beta"},
        ctx=ctx,
    )
    assert search_res["count"] >= 1
    assert search_res["hits"][0]["path"] == "notes/today.txt"

    list_res = await tool_service.call_tool(
        "workspace.list_files",
        {},
        ctx=ctx,
    )
    assert any(item.get("path") == "notes/today.txt" for item in list_res["files"])

    copy_res = await tool_service.call_tool(
        "workspace.copy_file",
        {"src_path": "notes/today.txt", "dst_path": "notes/today_copy.txt"},
        ctx=ctx,
    )
    assert copy_res["path"] == "notes/today_copy.txt"

    move_res = await tool_service.call_tool(
        "workspace.move_file",
        {"src_path": "notes/today_copy.txt", "dst_path": "notes/today_moved.txt"},
        ctx=ctx,
    )
    assert move_res["path"] == "notes/today_moved.txt"

    del_res = await tool_service.call_tool(
        "workspace.delete_file",
        {"path": "notes/today_moved.txt"},
        ctx=ctx,
    )
    assert del_res["deleted"] is True

    await tool_service.call_tool("workspace.ensure_dir", {"path": "logs/archive"}, ctx=ctx)
    await tool_service.call_tool(
        "workspace.write_file",
        {"path": "logs/archive/run.log", "content": "l1\nl2\nl3"},
        ctx=ctx,
    )
    tail = await tool_service.call_tool(
        "workspace.tail_file",
        {"path": "logs/archive/run.log", "lines": 2},
        ctx=ctx,
    )
    assert tail["lines"] == 2
    repl = await tool_service.call_tool(
        "workspace.replace_text",
        {"path": "logs/archive/run.log", "pattern": "l2", "replacement": "L2"},
        ctx=ctx,
    )
    assert repl["replacements"] >= 1
    info = await tool_service.call_tool("workspace.file_info", {"path": "logs/archive/run.log"}, ctx=ctx)
    assert info["size"] > 0
    reads = await tool_service.call_tool(
        "workspace.read_files",
        {"paths": ["logs/archive/run.log", "missing.txt"]},
        ctx=ctx,
    )
    assert reads["count"] == 2
    globs = await tool_service.call_tool("workspace.glob_files", {"pattern": "logs/**/*.log"}, ctx=ctx)
    assert globs["count"] >= 1


@pytest.mark.asyncio
async def test_official_tools_text_and_utils(tmp_path: Path):
    tool_service, _ = _build_services(tmp_path)

    stats = await tool_service.call_tool(
        "text.word_stats",
        {"text": "alpha beta\ngamma"},
    )
    assert stats["words"] == 3
    assert stats["lines"] == 2

    matches = await tool_service.call_tool(
        "text.find_matches",
        {"text": "a b a b a", "query": "a", "max_results": 2},
    )
    assert matches["count"] == 2

    normalized = await tool_service.call_tool(
        "text.normalize_json",
        {"text": "{\"b\":2,\"a\":1}", "sort_keys": True},
    )
    assert normalized["valid"] is True
    assert "\"a\": 1" in normalized["normalized"]

    now = await tool_service.call_tool("utils.now", {})
    assert "utc_iso" in now
    assert now["epoch_ms"] > 0

    uuids = await tool_service.call_tool("utils.uuid", {"count": 2})
    assert uuids["count"] == 2
    assert len(uuids["uuids"]) == 2

    digest = await tool_service.call_tool(
        "utils.hash_text",
        {"text": "hello", "algo": "sha256"},
    )
    assert digest["algo"] == "sha256"
    assert len(digest["digest"]) == 64

    calc = await tool_service.call_tool(
        "math.calculate",
        {"expression": "(2 + 3) * 4 - 1"},
    )
    assert calc["value"] == 19.0

    csv_to_json = await tool_service.call_tool(
        "data.csv_to_json",
        {"text": "a,b\n1,2\n3,4\n"},
    )
    assert csv_to_json["count"] == 2
    assert csv_to_json["rows"][0]["a"] == "1"

    json_to_csv = await tool_service.call_tool(
        "data.json_to_csv",
        {"rows": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]},
    )
    assert "a,b" in json_to_csv["csv"]
    assert json_to_csv["count"] == 2

    links = await tool_service.call_tool(
        "web.extract_links",
        {"html": '<a href="https://example.com">x</a><a href="/docs">y</a>'},
    )
    assert links["count"] == 2


@pytest.mark.asyncio
async def test_official_tools_register_without_workspace_service():
    tool_service = ToolService(event_emitter=EventEmitter())
    register_official_tools(tool_service=tool_service, workspace_service=None)

    catalog = await tool_service.get_tool_catalog()
    names = {str(row.get("tool_name") or "") for row in catalog}
    assert "text.word_stats" in names
    assert "utils.now" in names
    assert "math.calculate" in names
    assert "data.csv_to_json" in names
    assert "web.extract_links" in names
    assert "workspace.read_file" not in names


@pytest.mark.asyncio
async def test_official_tools_register_memory_session_runtime():
    tool_service = ToolService(event_emitter=EventEmitter())
    workflow_engine = WorkflowEngine(tool_service=tool_service)
    register_official_tools(
        tool_service=tool_service,
        workspace_service=None,
        memory_service=_DummyMemoryService(),
        message_manager=_DummyMessageManager(),
        gateway_server=_DummyGatewayServer(workflow_engine=workflow_engine, tool_service=tool_service),
    )
    catalog = await tool_service.get_tool_catalog()
    names = {str(row.get("tool_name") or "") for row in catalog}
    assert "memory.get_context" in names
    assert "memory.list_entries" in names
    assert "session.recent_messages" in names
    assert "runtime.services" in names
    assert "runtime.list_tools" in names
    assert "workflow.define" in names
    assert "workflow.start" in names
    assert "workflow.status" in names

    ctx = ToolInvocationContext(session_id="s1", user_id="u1")
    recall = await tool_service.call_tool("memory.get_context", {"query": "q"}, ctx=ctx)
    assert "ctx:u1:s1:q" in recall["context"]
    recent = await tool_service.call_tool("session.recent_messages", {}, ctx=ctx)
    assert recent["count"] == 1
    runtime = await tool_service.call_tool("runtime.services", {})
    assert runtime["status"] == "healthy"
    listed = await tool_service.call_tool("runtime.list_tools", {"official_only": True})
    assert listed["ok"] is True


@pytest.mark.asyncio
async def test_official_tools_runtime_exec_and_workflow_tools(tmp_path: Path):
    workspace_service = WorkspaceService(base_dir=str(tmp_path / "ws"))
    tool_service = ToolService(event_emitter=EventEmitter())
    workflow_engine = WorkflowEngine(tool_service=tool_service, workspace_service=workspace_service)
    gateway = _DummyGatewayServer(workflow_engine=workflow_engine, tool_service=tool_service)
    register_official_tools(
        tool_service=tool_service,
        workspace_service=workspace_service,
        gateway_server=gateway,
    )
    ctx = ToolInvocationContext(session_id="s1", user_id="u1")
    cmd = await tool_service.call_tool(
        "runtime.exec_command",
        {"command": "cmd /c echo hello"},
        ctx=ctx,
    )
    assert cmd["returncode"] == 0
    assert "hello" in (cmd["stdout"] or "").lower()

    define = await tool_service.call_tool(
        "workflow.define",
        {
            "workflow_id": "wf_demo",
            "name": "wf_demo",
            "steps": [{"step_id": "s1", "step_type": "summary_step", "name": "s1", "inputs": {"summary": "ok"}}],
        },
        ctx=ctx,
    )
    assert define["workflow"]["workflow_id"] == "wf_demo"
    started = await tool_service.call_tool("workflow.start", {"workflow_id": "wf_demo"}, ctx=ctx)
    run_id = started["run"]["workflow_run_id"]
    status = await tool_service.call_tool("workflow.status", {"workflow_run_id": run_id}, ctx=ctx)
    assert status["run"]["workflow_run_id"] == run_id


@pytest.mark.asyncio
async def test_web_fetch_text_rejects_non_http_scheme(tmp_path: Path):
    tool_service, _ = _build_services(tmp_path)
    with pytest.raises(ValueError, match="only http/https URLs are supported"):
        await tool_service.call_tool(
            "web.fetch_text",
            {"url": "file:///tmp/a.txt"},
        )
