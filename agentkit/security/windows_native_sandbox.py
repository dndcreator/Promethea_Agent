"""Native Windows write-restricted process launcher.

This is a write boundary, not read, network, or desktop isolation. The
restricting SID is stable for one workspace; the job closes with the runner.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

RUNNER_FAILURE = "promethea-windows-sandbox:"
WRITE_RESTRICTED = 0x8


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def _workspace_sid(path: Path):
    import win32security

    canonical = os.path.normcase(str(path.resolve(strict=True)))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    parts = [int.from_bytes(digest[i:i + 4], "little") for i in (0, 4, 8, 12)]
    return win32security.ConvertStringSidToSid("S-1-4-" + "-".join(map(str, parts)))


def _grant_workspace(root: Path, sid) -> None:
    import win32con
    import win32file
    import win32security

    descriptor = win32security.GetNamedSecurityInfo(
        str(root), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION,
    )
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        raise RuntimeError("workspace has a null DACL")
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        if ace[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE and ace[2] == sid:
            inherit = win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE
            if ace[1] & win32file.FILE_ALL_ACCESS == win32file.FILE_ALL_ACCESS and ace[0][1] & inherit == inherit:
                return
            raise RuntimeError("workspace has an incomplete sandbox ACL grant")
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION,
        win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE,
        win32file.FILE_ALL_ACCESS,
        sid,
    )
    win32security.SetNamedSecurityInfo(
        str(root), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION, None, None, dacl, None,
    )


def _restricted_token(workspace_sid, *, writable: bool):
    import pywintypes
    import win32api
    import win32security

    source = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32security.TOKEN_QUERY | win32security.TOKEN_DUPLICATE | win32security.TOKEN_ASSIGN_PRIMARY,
    )
    groups = win32security.GetTokenInformation(source, win32security.TokenGroups)
    logon = next((sid for sid, flags in groups if flags & 0xC0000000 == 0xC0000000), None)
    if logon is None:
        raise RuntimeError("current token has no logon SID")
    world = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
    sids = [logon, world]
    if writable:
        sids.append(workspace_sid)
    buffers = [ctypes.create_string_buffer(bytes(sid)) for sid in sids]
    entries = (_SidAndAttributes * len(buffers))(
        *(_SidAndAttributes(ctypes.addressof(buffer), 0) for buffer in buffers)
    )
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    create = api.CreateRestrictedToken
    create.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(_SidAndAttributes), ctypes.POINTER(wintypes.HANDLE)]
    create.restype = wintypes.BOOL
    handle = wintypes.HANDLE()
    flags = win32security.DISABLE_MAX_PRIVILEGE | 0x4 | WRITE_RESTRICTED
    if not create(int(source), flags, 0, None, 0, None, len(entries), entries, ctypes.byref(handle)):
        raise ctypes.WinError(ctypes.get_last_error())
    token = pywintypes.HANDLE(handle.value)
    if not win32security.IsTokenRestricted(token):
        token.Close()
        raise RuntimeError("restricted token creation did not restrict access")
    return token


def _launch(argv: list[str], root: Path, cwd: Path, mode: str) -> int:
    import msvcrt
    import win32api
    import win32con
    import win32event
    import win32job
    import win32process

    sid = _workspace_sid(root)
    if mode == "workspace-write":
        _grant_workspace(root, sid)
    token = _restricted_token(sid, writable=mode == "workspace-write")
    process = win32api.GetCurrentProcess()
    inherited = [win32api.DuplicateHandle(process, msvcrt.get_osfhandle(fd), process, 0,
                                          True, win32con.DUPLICATE_SAME_ACCESS) for fd in (0, 1, 2)]
    job = win32job.CreateJobObject(None, "")
    limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
    startup = win32process.STARTUPINFO()
    startup.dwFlags = win32process.STARTF_USESTDHANDLES
    startup.hStdInput, startup.hStdOutput, startup.hStdError = inherited
    child = thread = None
    temp_dir = root / ".runtime" / "sandbox-tmp" / uuid4().hex
    temp_dir.mkdir(parents=True)
    environment = dict(os.environ)
    environment["TEMP"] = environment["TMP"] = str(temp_dir)
    try:
        child, thread, _, _ = win32process.CreateProcessAsUser(
            token, None, subprocess.list2cmdline(argv), None, None, True,
            win32process.CREATE_SUSPENDED, environment, str(cwd), startup,
        )
        win32job.AssignProcessToJobObject(job, child)
        win32process.ResumeThread(thread)
        win32event.WaitForSingleObject(child, win32event.INFINITE)
        return win32process.GetExitCodeProcess(child)
    finally:
        job.Close()
        if thread is not None:
            thread.Close()
        if child is not None:
            child.Close()
        for handle in inherited:
            handle.Close()
        token.Close()
        if temp_dir.is_relative_to(root) and temp_dir.exists():
            shutil.rmtree(temp_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--cwd")
    parser.add_argument("--mode", choices=("read-only", "workspace-write"), required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command required")
    requested_root = Path(args.workspace).absolute()
    root = requested_root.resolve(strict=True)
    if root != requested_root:
        parser.error("workspace must not redirect through a link")
    if not root.is_dir():
        parser.error("workspace must be a directory")
    requested_cwd = Path(args.cwd or root).absolute()
    cwd = requested_cwd.resolve(strict=True)
    if cwd != requested_cwd:
        parser.error("cwd must not redirect through a link")
    if not cwd.is_dir() or not cwd.is_relative_to(root):
        parser.error("cwd must be a directory inside workspace")
    try:
        return _launch(command, root, cwd, args.mode)
    except BaseException as exc:
        print(f"{RUNNER_FAILURE} {type(exc).__name__}: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
