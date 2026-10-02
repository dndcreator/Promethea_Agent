from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


MemorySelector = Callable[[str, int, List[Dict[str, Any]]], Any]
MemoryReflector = Callable[[str, List[Dict[str, Any]], int, List[Dict[str, Any]]], Any]
InsightCommitter = Callable[[str, Dict[str, Any], int], Any]
IdleProbe = Callable[[], Any]
EventPublisher = Callable[[str, Dict[str, Any]], Any]


@dataclass(frozen=True)
class HippocampusReplayPolicy:
    enabled: bool = True
    state_path: str = "memory/hippocampus/replay_state.json"
    new_memory_threshold: int = 24
    min_interval_s: float = 6 * 3600
    max_interval_s: float = 24 * 3600
    revisit_interval_s: float = 7 * 24 * 3600
    idle_delay_s: float = 300
    poll_interval_s: float = 30
    batch_size: int = 24
    max_insights_per_cycle: int = 4
    cognition_hint_threshold: int = 4
    max_pending_cognition_hints: int = 24
    max_cognition_hint_chars: int = 2000
    retry_delay_s: float = 300

    @classmethod
    def from_config(cls, config: Any) -> "HippocampusReplayPolicy":
        hippocampus = getattr(getattr(config, "memory", None), "hippocampus", None)
        if hippocampus is None:
            return cls(enabled=False)
        return cls(
            enabled=bool(getattr(hippocampus, "enabled", True)),
            state_path=str(getattr(hippocampus, "state_path", cls.state_path) or cls.state_path),
            new_memory_threshold=max(1, int(getattr(hippocampus, "new_memory_threshold", 24))),
            min_interval_s=max(0.0, float(getattr(hippocampus, "min_interval_s", 6 * 3600))),
            max_interval_s=max(60.0, float(getattr(hippocampus, "max_interval_s", 24 * 3600))),
            revisit_interval_s=max(
                60.0,
                float(getattr(hippocampus, "revisit_interval_s", 7 * 24 * 3600)),
            ),
            idle_delay_s=max(10.0, float(getattr(hippocampus, "idle_delay_s", 300))),
            poll_interval_s=max(1.0, float(getattr(hippocampus, "poll_interval_s", 30))),
            batch_size=max(2, min(200, int(getattr(hippocampus, "batch_size", 24)))),
            max_insights_per_cycle=max(
                1,
                min(20, int(getattr(hippocampus, "max_insights_per_cycle", 4))),
            ),
            cognition_hint_threshold=max(
                1,
                min(50, int(getattr(hippocampus, "cognition_hint_threshold", 4))),
            ),
            max_pending_cognition_hints=max(
                1,
                min(200, int(getattr(hippocampus, "max_pending_cognition_hints", 24))),
            ),
            max_cognition_hint_chars=max(
                200,
                min(10000, int(getattr(hippocampus, "max_cognition_hint_chars", 2000))),
            ),
            retry_delay_s=max(10.0, float(getattr(hippocampus, "retry_delay_s", 300))),
        )


class HippocampusReplayService:
    """Durable, resource-aware memory replay independent of storage layers."""

    def __init__(
        self,
        *,
        policy: HippocampusReplayPolicy,
        select_memories: MemorySelector,
        reflect: MemoryReflector,
        commit_insight: InsightCommitter,
        idle_probe: Optional[IdleProbe] = None,
        publish_event: Optional[EventPublisher] = None,
    ) -> None:
        self.policy = policy
        self._select_memories = select_memories
        self._reflect = reflect
        self._commit_insight = commit_insight
        self._idle_probe = idle_probe
        self._publish_event = publish_event
        self._path = Path(policy.state_path)
        self._states = self._load_state()
        self._wake = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self._worker: Optional[asyncio.Task] = None
        self._stopping = False
        self._foreground_runs: set[str] = set()
        self._active_user_id: Optional[str] = None
        self._repair_interrupted_state()

    async def start(self) -> bool:
        if not self.policy.enabled or self._worker and not self._worker.done():
            return bool(self.policy.enabled)
        self._stopping = False
        self._worker = asyncio.create_task(self._worker_loop(), name="hippocampus_replay")
        self._wake.set()
        return True

    async def stop(self) -> None:
        self._stopping = True
        task = self._worker
        self._worker = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._states:
            self._save_state()

    async def interrupt(self) -> bool:
        task = self._worker
        if not task or task.done() or not self._active_user_id:
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._worker = None
        return True

    async def notify_activity(self, user_id: str) -> None:
        if not self.policy.enabled or not str(user_id or "").strip():
            return
        state = self._user_state(user_id)
        state["last_activity_at"] = time.time()
        self._save_state()
        await self.start()

    async def notify_memory_saved(self, user_id: str, count: int = 1) -> None:
        if not self.policy.enabled or count <= 0 or not str(user_id or "").strip():
            return
        state = self._user_state(user_id)
        state["pending_memories"] = int(state.get("pending_memories") or 0) + int(count)
        state["last_activity_at"] = time.time()
        if state["pending_memories"] >= self.policy.new_memory_threshold:
            state["status"] = "queued"
            self._save_state()
            await self.start()
            self._wake.set()
            return
        self._save_state()

    async def offer_cognition_hint(self, user_id: str, hint: Dict[str, Any]) -> bool:
        """Queue an untrusted replay hint without promoting it to memory evidence."""
        if not self.policy.enabled or not str(user_id or "").strip() or not isinstance(hint, dict):
            return False
        content = " ".join(str(hint.get("content") or "").split()).strip()
        basis_ids = list(dict.fromkeys(
            str(value).strip()
            for value in hint.get("basis_memory_ids") or []
            if str(value).strip()
        ))[: self.policy.batch_size]
        if not content or not basis_ids:
            return False
        content = content[: self.policy.max_cognition_hint_chars]
        hint_id = hashlib.sha256(
            json.dumps(
                {"content": content, "basis_memory_ids": basis_ids},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        state = self._user_state(user_id)
        pending = [row for row in state.get("cognition_hints") or [] if isinstance(row, dict)]
        if any(str(row.get("hint_id") or "") == hint_id for row in pending):
            return False
        pending.append(
            {
                "hint_id": hint_id,
                "content": content,
                "basis_memory_ids": basis_ids,
                "created_at": time.time(),
            }
        )
        state["cognition_hints"] = pending[-self.policy.max_pending_cognition_hints :]
        state["last_activity_at"] = time.time()
        if len(state["cognition_hints"]) >= self.policy.cognition_hint_threshold:
            state["status"] = "queued"
            await self.start()
            self._wake.set()
        self._save_state()
        return True

    async def foreground_started(self, run_id: str) -> None:
        if run_id:
            self._foreground_runs.add(str(run_id))
        if self._active_user_id:
            await self.interrupt()

    async def foreground_finished(self, run_id: str) -> None:
        if run_id:
            self._foreground_runs.discard(str(run_id))
        await self.start()
        self._wake.set()

    async def run_once(self, *, user_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        if not self.policy.enabled:
            return {"ok": False, "reason": "disabled", "ran": []}
        async with self._run_lock:
            if not force and not await self._resources_idle():
                return {"ok": True, "reason": "resources_busy", "ran": []}
            candidates = [str(user_id)] if user_id else sorted(self._states)
            ran: List[Dict[str, Any]] = []
            for candidate in candidates:
                if self._eligible(candidate, force=force):
                    ran.append(await self._run_user(candidate))
                    break
            return {"ok": True, "reason": "completed" if ran else "not_due", "ran": ran}

    def get_status(self, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        states = {user_id: dict(self._states.get(str(user_id), {}))} if user_id else {
            key: dict(value) for key, value in self._states.items()
        }
        return {
            "enabled": self.policy.enabled,
            "running": bool(self._worker and not self._worker.done()),
            "active_user_id": self._active_user_id,
            "foreground_busy": bool(self._foreground_runs),
            "policy": asdict(self.policy),
            "users": states,
        }

    async def _worker_loop(self) -> None:
        try:
            while not self._stopping:
                self._wake.clear()
                await self.run_once()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.policy.poll_interval_s)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Hippocampus replay worker stopped: {}", exc)
        finally:
            if self._worker is asyncio.current_task():
                self._worker = None

    async def _run_user(self, user_id: str) -> Dict[str, Any]:
        state = self._user_state(user_id)
        self._active_user_id = user_id
        cycle = int(state.get("cycle") or 0) + 1
        try:
            checkpoint = state.get("checkpoint") if isinstance(state.get("checkpoint"), dict) else {}
            insights = checkpoint.get("insights") if isinstance(checkpoint.get("insights"), list) else []
            cognition_hints = (
                checkpoint.get("cognition_hints")
                if isinstance(checkpoint.get("cognition_hints"), list)
                else [row for row in state.get("cognition_hints") or [] if isinstance(row, dict)]
            )
            selected_count = int(checkpoint.get("selected_count") or 0)
            if not insights:
                state.update({"status": "selecting", "error": "", "retry_at": 0.0})
                self._save_state()
                await self._emit("memory.replay.started", user_id, cycle, status="running")
                memories = list(
                    await _resolve(self._select_memories(user_id, self.policy.batch_size, cognition_hints)) or []
                )
                selected_count = len(memories)
                if selected_count < 2:
                    return await self._complete(
                        user_id,
                        cycle,
                        selected_count,
                        0,
                        cognition_hints=cognition_hints,
                        reason="insufficient_memories",
                    )
                state["status"] = "reflecting"
                state["checkpoint"] = {
                    "phase": "reflecting",
                    "selected_memory_ids": [str(item.get("memory_id") or "") for item in memories],
                    "selected_count": selected_count,
                    "cognition_hints": cognition_hints,
                    "insights": [],
                    "next_index": 0,
                }
                self._save_state()
                insights = list(
                    await _resolve(
                        self._reflect(
                            user_id,
                            memories,
                            self.policy.max_insights_per_cycle,
                            cognition_hints,
                        )
                    )
                    or []
                )[: self.policy.max_insights_per_cycle]
                state["checkpoint"].update({"phase": "committing", "insights": insights, "next_index": 0})
                state["status"] = "committing"
                self._save_state()
                await self._emit(
                    "memory.replay.checkpointed",
                    user_id,
                    cycle,
                    status="running",
                    selected_count=selected_count,
                    insight_count=len(insights),
                )

            checkpoint = state.get("checkpoint") or {}
            next_index = max(0, int(checkpoint.get("next_index") or 0))
            committed = next_index
            for index in range(next_index, len(insights)):
                await _resolve(self._commit_insight(user_id, dict(insights[index]), cycle))
                committed = index + 1
                checkpoint["next_index"] = committed
                self._save_state()
            return await self._complete(
                user_id,
                cycle,
                selected_count,
                committed,
                cognition_hints=cognition_hints,
            )
        except asyncio.CancelledError:
            state["status"] = "interrupted"
            state["updated_at"] = time.time()
            self._save_state()
            await self._emit("memory.replay.interrupted", user_id, cycle, status="interrupted")
            raise
        except Exception as exc:
            state.update(
                {
                    "status": "failed",
                    "error": str(exc),
                    "retry_at": time.time() + self.policy.retry_delay_s,
                    "updated_at": time.time(),
                }
            )
            self._save_state()
            await self._emit("memory.replay.failed", user_id, cycle, status="failed", error=str(exc))
            return {"user_id": user_id, "cycle": cycle, "status": "failed", "error": str(exc)}
        finally:
            self._active_user_id = None

    async def _complete(
        self,
        user_id: str,
        cycle: int,
        selected_count: int,
        committed: int,
        *,
        cognition_hints: Optional[List[Dict[str, Any]]] = None,
        reason: str = "completed",
    ) -> Dict[str, Any]:
        state = self._user_state(user_id)
        consumed_hint_ids = {
            str(row.get("hint_id") or "")
            for row in cognition_hints or []
            if isinstance(row, dict) and row.get("hint_id")
        }
        if consumed_hint_ids:
            state["cognition_hints"] = [
                row
                for row in state.get("cognition_hints") or []
                if isinstance(row, dict) and str(row.get("hint_id") or "") not in consumed_hint_ids
            ]
        state.update(
            {
                "status": "idle",
                "pending_memories": max(0, int(state.get("pending_memories") or 0) - selected_count),
                "last_run_at": time.time(),
                "cycle": cycle,
                "checkpoint": None,
                "error": "",
                "retry_at": 0.0,
                "updated_at": time.time(),
            }
        )
        self._save_state()
        await self._emit(
            "memory.replay.completed",
            user_id,
            cycle,
            status="completed",
            selected_count=selected_count,
            committed_count=committed,
            reason=reason,
        )
        return {
            "user_id": user_id,
            "cycle": cycle,
            "status": "completed",
            "selected_count": selected_count,
            "committed_count": committed,
            "reason": reason,
        }

    def _eligible(self, user_id: str, *, force: bool) -> bool:
        state = self._user_state(user_id)
        now = time.time()
        if force:
            return True
        if state.get("status") == "failed" and now < float(state.get("retry_at") or 0.0):
            return False
        resumable = state.get("status") in {"interrupted", "failed"} and bool(state.get("checkpoint"))
        pending = int(state.get("pending_memories") or 0)
        pending_hints = len([row for row in state.get("cognition_hints") or [] if isinstance(row, dict)])
        last_run_at = float(state.get("last_run_at") or 0.0)
        last_activity_at = float(state.get("last_activity_at") or 0.0)
        baseline = last_run_at or last_activity_at
        threshold_due = pending >= self.policy.new_memory_threshold
        hint_threshold_due = pending_hints >= self.policy.cognition_hint_threshold
        pending_due = pending > 0 and baseline > 0 and now - baseline >= self.policy.max_interval_s
        hint_due = pending_hints > 0 and baseline > 0 and now - baseline >= self.policy.max_interval_s
        revisit_due = (
            int(state.get("cycle") or 0) > 0
            and last_run_at > 0
            and now - last_run_at >= self.policy.revisit_interval_s
        )
        if not resumable and not (threshold_due or hint_threshold_due or pending_due or hint_due or revisit_due):
            return False
        if now - float(state.get("last_activity_at") or 0.0) < self.policy.idle_delay_s:
            return False
        if not resumable and now - float(state.get("last_run_at") or 0.0) < self.policy.min_interval_s:
            return False
        return True

    async def _resources_idle(self) -> bool:
        if self._foreground_runs:
            return False
        if self._idle_probe is None:
            return True
        try:
            return bool(await _resolve(self._idle_probe()))
        except Exception as exc:
            logger.debug("Hippocampus idle probe failed: {}", exc)
            return False

    def _user_state(self, user_id: str) -> Dict[str, Any]:
        key = str(user_id or "default_user")
        return self._states.setdefault(
            key,
            {
                "status": "idle",
                "pending_memories": 0,
                "last_activity_at": 0.0,
                "last_run_at": 0.0,
                "cycle": 0,
                "cognition_hints": [],
                "checkpoint": None,
                "error": "",
                "retry_at": 0.0,
                "updated_at": time.time(),
            },
        )

    async def _emit(self, event_type: str, user_id: str, cycle: int, **payload: Any) -> None:
        if self._publish_event is None:
            return
        await _resolve(
            self._publish_event(
                event_type,
                {
                    "user_id": user_id,
                    "kind": "memory",
                    "title": "Memory replay",
                    "cycle": cycle,
                    **payload,
                },
            )
        )

    def _repair_interrupted_state(self) -> None:
        changed = False
        for state in self._states.values():
            if state.get("status") in {"selecting", "reflecting", "committing", "running"}:
                state["status"] = "interrupted"
                state["updated_at"] = time.time()
                changed = True
        if changed:
            self._save_state()

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            users = payload.get("users") if isinstance(payload, dict) else {}
            return {str(key): dict(value) for key, value in (users or {}).items() if isinstance(value, dict)}
        except Exception as exc:
            raise RuntimeError(f"hippocampus replay state could not be loaded: {exc}") from exc

    def _save_state(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        payload = {"version": 1, "updated_at": time.time(), "users": self._states}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    return await value if inspect.isawaitable(value) else value
