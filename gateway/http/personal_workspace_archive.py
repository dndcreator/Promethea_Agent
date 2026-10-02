"""Portable, user-scoped workspace archives.

The archive is deliberately limited to durable personal records. Deployment
credentials, browser profiles, and process state never enter this boundary.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


ARCHIVE_VERSION = "promethea-workspace.v2"
MANIFEST_NAME = "manifest.json"
PAYLOAD_NAME = "workspace.json"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_archive(*, user_id: str, payload: Dict[str, Any]) -> bytes:
    """Build a self-validating archive with a stable internal layout."""
    payload_bytes = _json_bytes(payload)
    manifest = {
        "format": ARCHIVE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_user_id": str(user_id),
        "contents": {PAYLOAD_NAME: {"sha256": _digest(payload_bytes), "bytes": len(payload_bytes)}},
        "excludes": ["api_keys", "passwords", "tokens", "browser_profiles", "process_state", "service_logs"],
    }
    manifest_bytes = _json_bytes(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in ((MANIFEST_NAME, manifest_bytes), (PAYLOAD_NAME, payload_bytes)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


def read_archive(raw: bytes) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validate and decode an archive before any caller mutates local state."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            names = set(archive.namelist())
            if names != {MANIFEST_NAME, PAYLOAD_NAME}:
                raise ValueError("invalid workspace archive layout")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            payload_bytes = archive.read(PAYLOAD_NAME)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("invalid workspace archive") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_VERSION:
        raise ValueError("unsupported workspace archive version")
    expected = ((manifest.get("contents") or {}).get(PAYLOAD_NAME) or {}).get("sha256")
    if not isinstance(expected, str) or _digest(payload_bytes) != expected:
        raise ValueError("workspace archive checksum mismatch")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid workspace payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid workspace payload")
    return manifest, payload


def rebind_user_scope(value: Any, *, source_user_id: str, target_user_id: str) -> Any:
    """Rewrite durable record ownership while leaving ordinary text untouched."""
    source = str(source_user_id or "")
    target = str(target_user_id or "")
    source_aliases = {source, f"user_{source}" if source and not source.startswith("user_") else source}
    target_value = target
    if isinstance(value, list):
        return [rebind_user_scope(item, source_user_id=source, target_user_id=target) for item in value]
    if not isinstance(value, dict):
        return value
    out: Dict[str, Any] = {}
    for key, item in value.items():
        if key == "user_id" and str(item or "") in source_aliases:
            out[key] = target_value
        elif key == "id" and str(item or "") in source_aliases and str(value.get("node_type") or "") == "user":
            out[key] = f"user_{target_value}" if str(item).startswith("user_") else target_value
        else:
            out[key] = rebind_user_scope(item, source_user_id=source, target_user_id=target)
    return out
