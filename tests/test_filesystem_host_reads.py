"""Host user locations are readable without granting host mutations."""

import os

import pytest

from agentkit.security.sandbox import SandboxPolicy
from computer.filesystem import FileSystemController


@pytest.fixture
def filesystem(tmp_path):
    workspace = tmp_path / "workspace"
    desktop = tmp_path / "desktop"
    other = tmp_path / "other"
    for path in (workspace, desktop, other):
        path.mkdir()
    controller = FileSystemController(workspace_root=str(workspace))
    controller.sandbox = SandboxPolicy()
    controller.is_initialized = True
    controller.locations.register("desktop", lambda: desktop, host_readable=True)
    return controller, workspace, desktop, other


@pytest.mark.asyncio
async def test_desktop_read_and_discovery_without_host_write(filesystem):
    fs, workspace, desktop, other = filesystem
    note = desktop / "note.txt"
    note.write_text("private note", encoding="utf-8")

    for params in ({"path": str(note)}, {"location": "desktop", "path": "note.txt"}):
        result = await fs.execute("read", params)
        assert result.success and result.result == "private note"

    for action, params in (
        ("list", {"location": "desktop"}),
        ("search", {"location": "desktop", "pattern": "*.txt"}),
        ("stat", {"path": str(note)}),
        ("exists", {"path": str(note)}),
    ):
        assert (await fs.execute(action, params)).success

    for action, params in (
        ("write", {"path": str(note), "content": "changed"}),
        ("append", {"location": "desktop", "path": "note.txt", "content": "changed"}),
        ("delete", {"path": str(note)}),
        ("move", {"src": str(note), "dst": str(workspace / "moved.txt")}),
        ("mkdir", {"location": "desktop", "path": "created"}),
        ("copy", {"src": str(workspace / "source.txt"), "dst": str(note)}),
    ):
        result = await fs.execute(action, params)
        assert not result.success, action
    assert note.read_text(encoding="utf-8") == "private note"
    assert not (desktop / "created").exists()

    assert not (await fs.execute("read", {"path": str(other / "secret.txt")})).success


@pytest.mark.asyncio
async def test_host_file_copy_is_read_only_but_directory_copy_is_rejected(filesystem):
    fs, workspace, desktop, other = filesystem
    (desktop / "note.txt").write_text("note", encoding="utf-8")

    file_copy = await fs.execute("copy", {"src": str(desktop / "note.txt"), "dst": str(workspace / "copy.txt")})
    assert file_copy.success
    assert (workspace / "copy.txt").read_text(encoding="utf-8") == "note"

    directory_copy = await fs.execute("copy", {"src": str(desktop), "dst": str(workspace / "desktop-copy")})
    assert not directory_copy.success
    assert not (workspace / "desktop-copy").exists()


@pytest.mark.asyncio
async def test_desktop_symlink_cannot_escape_read_scope(filesystem):
    fs, workspace, desktop, other = filesystem
    secret = other / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    link = desktop / "shortcut.txt"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    assert not (await fs.execute("read", {"path": str(link)})).success
    assert not (await fs.execute("copy", {"src": str(link), "dst": str(workspace / "copy.txt")})).success
    listing = await fs.execute("list", {"location": "desktop"})
    assert listing.success
    assert not any(item["name"] == "shortcut.txt" for item in listing.result)
    search = await fs.execute("search", {"location": "desktop", "pattern": "*.txt"})
    assert search.success
    assert not any(item["name"] == "shortcut.txt" for item in search.result)


def test_read_roots_do_not_change_other_tool_policies(filesystem):
    _, workspace, desktop, other = filesystem
    policy = SandboxPolicy()
    assert policy.check_path(desktop / "note.txt", workspace_root=workspace, read_roots=[desktop]).allowed
    assert not policy.check_path(desktop / "note.txt", intent="write", workspace_root=workspace, read_roots=[desktop]).allowed
    assert not policy.check_path(desktop / "note.txt", workspace_root=workspace).allowed
    assert not policy.check_path(other / "secret.txt", workspace_root=workspace, read_roots=[desktop]).allowed
