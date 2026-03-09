import shutil
from pathlib import Path

import pytest

from agentkit.mcp.tool_call import parse_tool_calls
from agentkit.tools.self_evolve.self_evolve import SelfEvolveService


def test_parse_tool_calls_supports_nested_args_and_service_name():
    content = '{"tool_name":"evolve_apply_patch","service_name":"self_evolve","args":{"task_id":"se_1","path":"a.txt","old":"x","new":"y"}}'
    calls = parse_tool_calls(content)
    assert len(calls) == 1
    call = calls[0]
    assert call["name"] == "evolve_apply_patch"
    assert call["args"]["service_name"] == "self_evolve"
    assert call["args"]["task_id"] == "se_1"


def _make_workspace() -> Path:
    base = Path(".pytest-self-evolve-work")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


@pytest.mark.asyncio
async def test_self_evolve_task_patch_and_validate(monkeypatch):
    ws = _make_workspace()
    try:
        svc = SelfEvolveService(workspace_root=str(ws))
        target = ws / "demo.txt"
        target.write_text("hello world", encoding="utf-8")

        created = await svc.evolve_create_task(
            goal="replace world",
            target_files=["demo.txt"],
            acceptance_criteria=["text updated"],
        )
        task_id = created["task"]["task_id"]

        ctx = await svc.evolve_collect_context(task_id=task_id)
        assert ctx["ok"] is True
        assert ctx["context"][0]["exists"] is True

        patch = await svc.evolve_apply_patch(
            task_id=task_id,
            path="demo.txt",
            old="world",
            new="agent",
            count=1,
        )
        assert patch["ok"] is True

        updated = target.read_text(encoding="utf-8")
        assert updated == "hello agent"

        class _DummyProc:
            returncode = 0

            async def communicate(self):
                return (b"ok\n", b"")

        async def _fake_subprocess(*args, **kwargs):
            return _DummyProc()

        monkeypatch.setattr(
            "agentkit.tools.self_evolve.self_evolve.asyncio.create_subprocess_shell",
            _fake_subprocess,
        )

        validated = await svc.evolve_validate(
            task_id=task_id,
            command="python -m pytest -q tests/test_self_evolve_service.py",
            timeout=30,
        )
        assert validated["ok"] is True

        task = await svc.evolve_get_task(task_id=task_id)
        assert task["ok"] is True
        assert task["task"]["changes"]
        assert task["task"]["validations"]
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.mark.asyncio
async def test_self_evolve_rejects_undeclared_target_file():
    ws = _make_workspace()
    try:
        svc = SelfEvolveService(workspace_root=str(ws))
        (ws / "a.txt").write_text("a", encoding="utf-8")
        (ws / "b.txt").write_text("b", encoding="utf-8")

        created = await svc.evolve_create_task(goal="edit a", target_files=["a.txt"])
        task_id = created["task"]["task_id"]

        with pytest.raises(PermissionError):
            await svc.evolve_apply_patch(
                task_id=task_id,
                path="b.txt",
                old="b",
                new="x",
            )
    finally:
        shutil.rmtree(ws, ignore_errors=True)

@pytest.mark.asyncio
async def test_self_evolve_validate_blocked_by_sandbox(monkeypatch):
    ws = _make_workspace()
    try:
        svc = SelfEvolveService(workspace_root=str(ws))
        created = await svc.evolve_create_task(goal="validate", target_files=["a.txt"])
        task_id = created["task"]["task_id"]

        class _Policy:
            def check_command(self, command, cwd=".", workspace_root=None):
                class _D:
                    allowed = False
                    reason = "blocked by policy"
                return _D()

        svc._sandbox = _Policy()

        with pytest.raises(PermissionError):
            await svc.evolve_validate(task_id=task_id, command="python -V")
    finally:
        shutil.rmtree(ws, ignore_errors=True)
