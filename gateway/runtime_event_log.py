"""Bounded append-only facts emitted by the Gateway runtime."""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional
from uuid import uuid4


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            is_secret = normalized in _SECRET_KEYS or normalized.endswith(
                ("_api_key", "_password", "_secret", "_token")
            )
            clean[str(key)] = "[REDACTED]" if is_secret else _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


class RuntimeEventLog:
    """Thread-safe JSONL store with stable sequence and bounded retention."""

    def __init__(
        self,
        *,
        storage_path: Optional[str] = None,
        max_bytes: int = 32 * 1024 * 1024,
        max_archives: int = 3,
    ) -> None:
        default = Path(__file__).resolve().parent / "runtime_events.jsonl"
        self.storage_path = Path(storage_path) if storage_path else default
        self.state_path = self.storage_path.with_suffix(self.storage_path.suffix + ".state.json")
        self.max_bytes = max(1024, int(max_bytes))
        self.max_archives = max(0, int(max_archives))
        self._lock = threading.RLock()
        self._next_seq = self._discover_next_seq()
        self._consumer_cursors = self._load_consumer_cursors()

    def append(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        seq: Optional[int] = None,
        durable: bool = True,
    ) -> Dict[str, Any]:
        with self._lock:
            event_seq = self._claim_seq(seq)
            body = dict(payload or {})
            stored_body = _redact(body)
            event = {
                "event_id": f"evt_{uuid4().hex}",
                "event_type": str(event_type),
                "seq": event_seq,
                "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user_id": body.get("user_id"),
                "session_id": body.get("session_id"),
                "task_id": body.get("task_id"),
                "run_id": body.get("run_id") or body.get("workflow_run_id") or body.get("action_run_id"),
                "trace_id": body.get("trace_id"),
                "request_id": body.get("request_id"),
                "source": body.get("source_module") or body.get("source") or "gateway",
                "payload": stored_body,
            }
            encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(encoded.encode("utf-8")))
            with self.storage_path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                if durable:
                    os.fsync(handle.fileno())
            return event

    def query(
        self,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        event_type: Optional[str] = None,
        after_seq: int = 0,
        limit: int = 200,
        oldest_first: bool = False,
    ) -> List[Dict[str, Any]]:
        resolved_limit = max(1, int(limit))
        rows: Deque[Dict[str, Any]] = deque(maxlen=resolved_limit)
        with self._lock:
            for path in self._ordered_paths():
                for row in self._iter_file(path):
                    if int(row.get("seq") or 0) <= int(after_seq or 0):
                        continue
                    if user_id and row.get("user_id") != user_id:
                        continue
                    if session_id and row.get("session_id") != session_id:
                        continue
                    if task_id and row.get("task_id") != task_id:
                        continue
                    if event_type and row.get("event_type") != event_type:
                        continue
                    rows.append(row)
                    if oldest_first and len(rows) >= resolved_limit:
                        return list(rows)
        return list(rows)

    def get_consumer_cursor(self, consumer: str) -> int:
        with self._lock:
            return int(self._consumer_cursors.get(str(consumer)) or 0)

    def ensure_consumer(self, consumer: str, *, start_at_tail: bool = True) -> int:
        name = str(consumer).strip()
        if not name:
            raise ValueError("consumer is required")
        with self._lock:
            if name not in self._consumer_cursors:
                self._consumer_cursors[name] = self._next_seq - 1 if start_at_tail else 0
                self._persist_consumer_cursors()
            return int(self._consumer_cursors[name])

    def commit_consumer_cursor(self, consumer: str, seq: int) -> int:
        name = str(consumer).strip()
        if not name:
            raise ValueError("consumer is required")
        with self._lock:
            current = int(self._consumer_cursors.get(name) or 0)
            committed = max(current, int(seq or 0))
            self._consumer_cursors[name] = committed
            self._persist_consumer_cursors()
            return committed

    @property
    def next_seq(self) -> int:
        with self._lock:
            return self._next_seq

    def _claim_seq(self, requested: Optional[int]) -> int:
        if requested is None:
            value = self._next_seq
        else:
            value = max(self._next_seq, int(requested))
        self._next_seq = value + 1
        return value

    def _discover_next_seq(self) -> int:
        highest = 0
        for path in self._ordered_paths():
            for row in self._iter_file(path):
                highest = max(highest, int(row.get("seq") or 0))
        return highest + 1

    def _ordered_paths(self) -> List[Path]:
        archives = [
            self.storage_path.with_name(f"{self.storage_path.name}.{index}")
            for index in range(self.max_archives, 0, -1)
        ]
        return [path for path in archives + [self.storage_path] if path.exists()]

    @staticmethod
    def _iter_file(path: Path) -> Iterable[Dict[str, Any]]:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        current = self.storage_path.stat().st_size if self.storage_path.exists() else 0
        if current == 0 or current + incoming_bytes <= self.max_bytes:
            return
        if self.max_archives <= 0:
            self.storage_path.unlink(missing_ok=True)
            return
        oldest = self.storage_path.with_name(f"{self.storage_path.name}.{self.max_archives}")
        oldest.unlink(missing_ok=True)
        for index in range(self.max_archives - 1, 0, -1):
            source = self.storage_path.with_name(f"{self.storage_path.name}.{index}")
            if source.exists():
                os.replace(source, self.storage_path.with_name(f"{self.storage_path.name}.{index + 1}"))
        os.replace(self.storage_path, self.storage_path.with_name(f"{self.storage_path.name}.1"))

    def _load_consumer_cursors(self) -> Dict[str, int]:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            source = raw.get("consumer_cursors") if isinstance(raw, dict) else {}
            return {str(key): int(value) for key, value in (source or {}).items()}
        except Exception:
            return {}

    def _persist_consumer_cursors(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(
            json.dumps({"version": 1, "consumer_cursors": self._consumer_cursors}, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.state_path)
