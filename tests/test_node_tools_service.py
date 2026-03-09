from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentkit.tools.node_tools.node_tools import NodeToolsService


def _make_workspace() -> Path:
    base = Path(".pytest-node-tools")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


@pytest.mark.asyncio
async def test_node_crud_and_links():
    ws = _make_workspace()
    svc = NodeToolsService(workspace_root=str(ws))

    a = await svc.upsert_node(node_id="a", kind="task", data={"title": "A"}, tags=["todo"])
    b = await svc.upsert_node(node_id="b", kind="task", data={"title": "B"}, tags=["todo"])
    assert a["ok"] and b["ok"]

    link = await svc.link_nodes(source="a", target="b", relation="depends_on")
    assert link["ok"] is True

    listed = await svc.list_nodes(kind="task", tag="todo", limit=10)
    assert listed["total"] == 2

    edges = await svc.list_links(node_id="a")
    assert edges["total"] == 1

    deleted = await svc.delete_node("a")
    assert deleted["removed"] is True
