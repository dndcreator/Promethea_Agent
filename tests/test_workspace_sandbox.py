import asyncio
from pathlib import Path
from typing import Optional

import pytest

from gateway.events import EventEmitter
from gateway.protocol import EventType
from gateway.workspace_service import WorkspaceHandle, WorkspaceSandboxError, WorkspaceService


def _svc(tmp_path: Path, emitter: Optional[EventEmitter] = None) -> WorkspaceService:
    return WorkspaceService(event_emitter=emitter, base_dir=str(tmp_path / "ws"))


def test_workspace_root_restriction(tmp_path: Path):
    svc = _svc(tmp_path)
    handle = svc.resolve_workspace_handle(user_id="u1", workspace_id="p1")

    row = svc.create_document(
        handle=handle,
        relative_path="docs/a.md",
        content="hello",
    )

    root = Path(handle.root_path).resolve()
    written = (root / row["path"]).resolve()
    assert str(written).startswith(str(root))


def test_out_of_bounds_write_is_rejected(tmp_path: Path):
    svc = _svc(tmp_path)
    handle = svc.resolve_workspace_handle(user_id="u1", workspace_id="p1")

    with pytest.raises(WorkspaceSandboxError):
        svc.create_document(
            handle=handle,
            relative_path="../escape.txt",
            content="x",
        )


def test_artifact_create(tmp_path: Path):
    svc = _svc(tmp_path)
    handle = svc.resolve_workspace_handle(user_id="u1", workspace_id="p1")

    row = svc.create_document(
        handle=handle,
        relative_path="artifacts/out.txt",
        content="result",
        trace_id="t1",
        request_id="r1",
        session_id="s1",
    )

    assert row["operation"] == "create"
    assert row["path"] == "artifacts/out.txt"
    assert row["trace_id"] == "t1"


def test_snapshot_create(tmp_path: Path):
    svc = _svc(tmp_path)
    handle = svc.resolve_workspace_handle(user_id="u1", workspace_id="p1")
    svc.create_document(handle=handle, relative_path="artifacts/out.txt", content="result")

    snap = svc.snapshot_artifact(
        handle=handle,
        relative_path="artifacts/out.txt",
    )

    assert snap["operation"] == "snapshot"
    assert snap["snapshot_path"].startswith(".snapshots/")


@pytest.mark.asyncio
async def test_trace_info_attached_on_write(tmp_path: Path):
    emitter = EventEmitter()
    svc = _svc(tmp_path, emitter=emitter)
    handle = svc.resolve_workspace_handle(user_id="u1", workspace_id="p1")

    svc.create_document(
        handle=handle,
        relative_path="artifacts/trace.md",
        content="trace",
        trace_id="trace_123",
        request_id="req_123",
        session_id="s1",
    )
    await asyncio.sleep(0)

    traces = emitter.get_trace_history(trace_id="trace_123")
    assert traces
    latest = traces[-1]
    assert latest.event_type == EventType.WORKSPACE_ARTIFACT_WRITTEN.value
    assert latest.request_id == "req_123"


