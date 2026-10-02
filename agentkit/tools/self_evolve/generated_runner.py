"""Child-process entrypoint for Agent-generated capabilities."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any


RESULT_PREFIX = "PROMETHEA_GENERATED_RESULT="
_MAX_CAPTURE_CHARS = 32_000
_MAX_RESULT_BYTES = 1_000_000


class _BoundedTextBuffer(io.TextIOBase):
    def __init__(self, limit: int):
        self.limit = limit
        self._parts: list[str] = []
        self._size = 0

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        text = str(value)
        remaining = max(0, self.limit - self._size)
        if remaining:
            piece = text[:remaining]
            self._parts.append(piece)
            self._size += len(piece)
        return len(text)


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)


def _install_audit_policy(script_path: Path, request_path: Path) -> None:
    runtime_root = request_path.parent.resolve()
    read_roots = tuple(
        dict.fromkeys(
            root.resolve()
            for root in (
                script_path.parent,
                runtime_root,
                Path(sys.prefix),
                Path(sys.base_prefix),
                Path(__file__).parent,
            )
        )
    )
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            raw_path = args[0]
            if isinstance(raw_path, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(raw_path))
                mode = args[1] if len(args) > 1 else "r"
                flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
                writing = bool(flags & write_flags) or (
                    isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "x", "+"))
                )
                allowed = (runtime_root,) if writing else read_roots
                if not _is_within(path, allowed):
                    raise PermissionError(f"generated capability file access denied: {path}")
        elif event in {"os.listdir", "os.scandir", "os.chdir"} and args:
            raw_path = args[0]
            if isinstance(raw_path, (str, bytes, os.PathLike)) and not _is_within(
                Path(os.fsdecode(raw_path)), read_roots
            ):
                raise PermissionError(f"generated capability directory access denied: {args[0]}")
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.replace"} and args:
            paths = [value for value in args[:2] if isinstance(value, (str, bytes, os.PathLike))]
            if any(not _is_within(Path(os.fsdecode(value)), (runtime_root,)) for value in paths):
                raise PermissionError("generated capability may write only inside its runtime directory")
        elif event.startswith("socket."):
            raise PermissionError("generated capability network access is disabled")
        elif event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
            raise PermissionError("generated capability process creation is disabled")
        elif event == "ctypes.dlopen":
            raise PermissionError("generated capability native library loading is disabled")

    sys.addaudithook(audit)


def _load_handler(script_path: Path):
    spec = importlib.util.spec_from_file_location("promethea_generated_capability", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load generated capability: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = getattr(module, "handle", None)
    if not callable(handler):
        raise RuntimeError("generated capability must export handle(command, args)")
    return handler


async def _invoke(script_path: Path, request_path: Path) -> Any:
    _install_audit_policy(script_path, request_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    command = str(request.get("command") or "")
    args = request.get("args") if isinstance(request.get("args"), dict) else {}
    handler = _load_handler(script_path)
    result = handler(command, args)
    if inspect.isawaitable(result):
        result = await result
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generated_runner.py <tool.py> <request.json>", file=sys.stderr)
        return 2
    try:
        captured = _BoundedTextBuffer(_MAX_CAPTURE_CHARS)
        with redirect_stdout(captured), redirect_stderr(captured):
            result = asyncio.run(_invoke(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
        encoded = json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
            raise ValueError("generated capability result exceeded the size limit")
        sys.__stdout__.write(RESULT_PREFIX + encoded + "\n")
        return 0
    except BaseException as exc:
        sys.__stdout__.write(
            RESULT_PREFIX
            + json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
            + "\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
