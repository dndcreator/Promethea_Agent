"""Materialized read model for the Agent Workbench."""
from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict, deque
from datetime import timezone
from typing import Any, Dict, List, Optional

from .protocol import EventType


ACTIVE_TASK_STATES = {"open", "running", "waiting_user", "paused"}
VISIBLE_ACTIVITY_KINDS = {"task", "workflow", "tool", "memory", "reasoning", "artifact", "environment"}
TERMINAL_ACTIVITY_STATES = {
    "complete", "completed", "finished", "success", "succeeded",
    "failed", "cancelled", "canceled", "stopped", "interrupted",
}
ATTENTION_ACTIVITY_STATES = {
    "waiting", "waiting_confirmation", "waiting_user", "waiting_human",
    "paused", "failed", "interrupted",
}


class WorkbenchProjection:
    """Project durable runtime facts into one user-scoped Workbench snapshot."""

    def __init__(
        self,
        *,
        task_service: Any,
        workflow_engine: Any,
        event_log: Any,
        memory_service: Optional[Any] = None,
        task_runtime: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
    ) -> None:
        self.task_service = task_service
        self.workflow_engine = workflow_engine
        self.event_log = event_log
        self.memory_service = memory_service
        self.task_runtime = task_runtime
        self._events: Dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
        self._hydrated_users: set[str] = set()
        self._subscribers: Dict[str, set[asyncio.Queue[None]]] = defaultdict(set)
        if event_emitter is not None:
            for event_type in EventType:
                event_emitter.on(event_type, self.on_event)

    def on_event(self, event: Any) -> None:
        payload = dict(getattr(event, "payload", {}) or {})
        user_id = str(payload.get("user_id") or "")
        if not user_id:
            return
        timestamp = getattr(event, "timestamp", None)
        occurred_at = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if timestamp else None
        row = {
            "event_id": getattr(event, "event_id", None),
            "event_type": getattr(getattr(event, "event", None), "value", str(getattr(event, "event", "runtime.event"))),
            "seq": int(getattr(event, "seq", 0) or 0),
            "occurred_at": occurred_at,
            "user_id": user_id,
            "session_id": payload.get("session_id"),
            "task_id": payload.get("task_id"),
            "run_id": payload.get("run_id") or payload.get("task_run_id") or payload.get("workflow_run_id") or payload.get("action_run_id"),
            "task_run_id": payload.get("task_run_id"),
            "workflow_run_id": payload.get("workflow_run_id"),
            "conversation_turn_id": payload.get("conversation_turn_id"),
            "action_loop_id": payload.get("action_loop_id") or payload.get("action_run_id"),
            "trace_id": payload.get("trace_id"),
            "payload": payload,
        }
        self._append_event(user_id, row)
        for queue in tuple(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def wait_for_change(
        self,
        *,
        user_id: str,
        after_seq: int,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout: float = 15.0,
    ) -> bool:
        """Wait for a user-scoped projection invalidation without storing another event copy."""
        def changed() -> bool:
            rows = self._query_events(
                user_id=user_id,
                after_seq=after_seq,
                task_id=task_id or "",
                session_id=session_id or "",
                run_id=run_id or "",
                limit=1,
            )
            return bool(rows)

        if changed():
            return True
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subscribers[user_id].add(queue)
        try:
            if changed():
                return True
            await asyncio.wait_for(queue.get(), timeout=max(0.1, float(timeout)))
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            subscribers = self._subscribers.get(user_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(user_id, None)

    def snapshot(
        self,
        *,
        user_id: str,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        after_seq: int = 0,
        limit: int = 120,
    ) -> Dict[str, Any]:
        tasks = self.task_service.list_tasks(user_id=user_id, limit=50)
        active_task = self._select_task(tasks, task_id=task_id, run_id=run_id, session_id=session_id)
        resolved_task_id = str((active_task or {}).get("task_id") or "")
        resolved_session_id = str(session_id or "")
        if not resolved_session_id and active_task:
            resolved_session_id = str(((active_task.get("session_ids") or [""])[-1]) or "")

        query_args: Dict[str, Any] = {
            "user_id": user_id,
            "after_seq": max(0, int(after_seq or 0)),
            "limit": max(1, min(int(limit or 120), 500)),
            "oldest_first": bool(after_seq),
        }
        if resolved_task_id:
            query_args["task_id"] = resolved_task_id
        elif resolved_session_id:
            query_args["session_id"] = resolved_session_id
        if run_id:
            query_args["run_id"] = str(run_id)
        rows = self._query_events(**query_args)
        if not any((task_id, run_id, resolved_session_id, resolved_task_id)):
            rows = []
        timeline = self._project_activities(rows)

        runs = list((active_task or {}).get("runs") or [])
        if run_id:
            runs = [run for run in runs if str(run.get("run_id") or "") == str(run_id)]
        workflow_runs = self.workflow_engine.list_runs(user_id=user_id, limit=50)
        if resolved_task_id:
            workflow_runs = [row for row in workflow_runs if str(row.get("task_id") or "") == resolved_task_id]
        elif resolved_session_id:
            workflow_runs = [row for row in workflow_runs if str(row.get("session_id") or "") == resolved_session_id]

        proposals: List[Dict[str, Any]] = []
        recalls: List[Dict[str, Any]] = []
        if self.memory_service is not None:
            proposals = self.memory_service.list_write_proposals(user_id=user_id, status="pending", limit=100)
            recalls = self.memory_service.list_recall_runs(
                user_id=user_id,
                session_id=resolved_session_id or None,
                limit=100,
            )

        recovery = [
            row for row in workflow_runs
            if str(row.get("status") or "") in {"paused", "failed", "waiting_human", "retry_wait"}
        ]
        waiting_actions = self._waiting_actions(active_task, proposals, recovery, timeline)
        artifacts = [activity for activity in timeline if activity["kind"] == "artifact"]
        current_activity = next(
            (activity for activity in reversed(timeline) if activity["status"] in {"running", "pending", "waiting", "waiting_user", "waiting_human"}),
            timeline[-1] if timeline else None,
        )
        cursor = max([int(row.get("seq") or 0) for row in rows] or [int(after_seq or 0)])

        return {
            "version": "workbench.v1",
            "scope": {
                "user_id": user_id,
                "session_id": resolved_session_id or None,
                "task_id": resolved_task_id or None,
                "run_id": run_id or None,
            },
            "task": active_task,
            "tasks": tasks,
            "runs": runs,
            "workflow_runs": workflow_runs,
            "timeline": timeline,
            "current_activity": current_activity,
            "artifacts": artifacts,
            "waiting_actions": waiting_actions,
            "memory_proposals": proposals,
            "recall_runs": recalls,
            "recovery_items": recovery,
            "active_runtime_runs": self.task_runtime.active_run_ids() if self.task_runtime else [],
            "cursor": cursor,
        }

    def _query_events(self, *, user_id: str, **filters: Any) -> List[Dict[str, Any]]:
        self._hydrate_user(user_id)
        after_seq = int(filters.get("after_seq") or 0)
        task_id = str(filters.get("task_id") or "")
        session_id = str(filters.get("session_id") or "")
        run_id = str(filters.get("run_id") or "")
        limit = max(1, int(filters.get("limit") or 120))
        rows = [row for row in self._events.get(user_id, ()) if int(row.get("seq") or 0) > after_seq]
        if task_id:
            rows = [row for row in rows if str(row.get("task_id") or "") == task_id]
        elif session_id:
            rows = [row for row in rows if str(row.get("session_id") or "") == session_id]
        if run_id:
            rows = [row for row in rows if run_id in self._event_run_ids(row)]
        if after_seq:
            return rows[:limit]
        return rows[-limit:]

    def _hydrate_user(self, user_id: str) -> None:
        if user_id in self._hydrated_users:
            return
        rows = list(self._events.get(user_id, ()))
        if self.event_log is not None:
            rows.extend(self.event_log.query(user_id=user_id, limit=2000))
        merged: Dict[str, Dict[str, Any]] = {}
        for index, row in enumerate(rows):
            key = str(row.get("event_id") or "") or f"seq:{int(row.get('seq') or 0)}:{index}"
            merged[key] = dict(row)
        ordered = sorted(merged.values(), key=lambda row: int(row.get("seq") or 0))
        self._events[user_id] = deque(ordered[-2000:], maxlen=2000)
        self._hydrated_users.add(user_id)

    def _append_event(self, user_id: str, row: Dict[str, Any]) -> None:
        bucket = self._events[user_id]
        event_id = str(row.get("event_id") or "")
        seq = int(row.get("seq") or 0)
        if bucket:
            latest = bucket[-1]
            if (event_id and str(latest.get("event_id") or "") == event_id) or (seq and int(latest.get("seq") or 0) == seq):
                return
        bucket.append(dict(row))

    @staticmethod
    def _select_task(
        tasks: List[Dict[str, Any]],
        *,
        task_id: Optional[str],
        run_id: Optional[str],
        session_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if task_id:
            return next((task for task in tasks if str(task.get("task_id") or "") == str(task_id)), None)
        if run_id:
            return next(
                (task for task in tasks if any(str(run.get("run_id") or "") == str(run_id) for run in task.get("runs", []))),
                None,
            )
        session_matches = [task for task in tasks if session_id and str(session_id) in (task.get("session_ids") or []) and task.get("source") not in {"subagent", "agent_inbox"}]
        if session_id:
            candidates = session_matches
        else:
            candidates = tasks
        active = next((task for task in candidates if str(task.get("status") or "") in ACTIVE_TASK_STATES), None)
        if session_id:
            return active or (candidates[0] if candidates else None)
        return active

    @staticmethod
    def _event_run_id(row: Dict[str, Any]) -> str:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        return str(
            row.get("task_run_id")
            or payload.get("task_run_id")
            or row.get("workflow_run_id")
            or payload.get("workflow_run_id")
            or row.get("run_id")
            or payload.get("run_id")
            or row.get("action_loop_id")
            or payload.get("action_loop_id")
            or ""
        )

    @staticmethod
    def _event_run_ids(row: Dict[str, Any]) -> set[str]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        values = (
            row.get("run_id"),
            row.get("task_run_id"),
            row.get("workflow_run_id"),
            row.get("action_loop_id"),
            payload.get("run_id"),
            payload.get("task_run_id"),
            payload.get("workflow_run_id"),
            payload.get("action_loop_id"),
            payload.get("action_run_id"),
            payload.get("parent_action_loop_id"),
            *(payload.get("ancestor_action_loop_ids") or []),
        )
        return {str(value) for value in values if value not in (None, "")}

    @classmethod
    def _activity(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        event_type = str(row.get("event_type") or "runtime.event")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        kind = cls._kind(event_type, payload)
        subject = cls._subject(event_type, payload)
        status = str(payload.get("status") or cls._status_from_event(event_type))
        occurred_at = row.get("occurred_at")
        activity = {
            "activity_id": cls._activity_id(row, kind=kind, subject=subject),
            "event_id": row.get("event_id"),
            "seq": int(row.get("seq") or 0),
            "occurred_at": row.get("occurred_at"),
            "event_type": event_type,
            "kind": kind,
            "subject": subject,
            "subject_i18n": cls._localized_text(payload, "title_i18n", subject=subject),
            "summary": cls._summary(payload, subject=subject),
            "summary_i18n": cls._localized_text(payload, "summary_i18n"),
            "status": status,
            "started_at": occurred_at if status in {"running", "pending"} else None,
            "updated_at": occurred_at,
            "completed_at": occurred_at if status in TERMINAL_ACTIVITY_STATES else None,
            "requires_attention": status in ATTENTION_ACTIVITY_STATES,
            "task_id": row.get("task_id"),
            "run_id": cls._event_run_id(row) or None,
            "conversation_turn_id": row.get("conversation_turn_id") or payload.get("conversation_turn_id"),
            "trace_id": row.get("trace_id"),
            "occurrence_count": 1,
            "detail": cls._detail(payload),
            "references": cls._references(payload, kind=kind),
        }
        presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}
        presented_title = str(presentation.get("title") or "").strip()
        execution_scope = str(
            activity.get("conversation_turn_id")
            or row.get("action_loop_id")
            or payload.get("action_loop_id")
            or ""
        )
        if kind == "tool" and presented_title and execution_scope:
            tool_identity = str(payload.get("tool_name") or payload.get("tool_id") or presented_title)
            activity["_group_key"] = f"{execution_scope}:{tool_identity}:{presented_title}"
            activity["_group_subject"] = presented_title
            activity["_group_subject_i18n"] = cls._localized_group_title(presentation)
        return activity

    @classmethod
    def _project_activities(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        activities: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        projected_tool_keys = {
            cls._tool_projection_key(row)
            for row in rows
            if str(row.get("event_type") or "").startswith("tool.")
        }
        for row in rows:
            if (
                str(row.get("event_type") or "") == EventType.ACTION_OBSERVATION_COMMITTED.value
                and cls._tool_projection_key(row) in projected_tool_keys
            ):
                continue
            activity = cls._activity(row)
            if not cls._is_visible_activity(activity):
                continue
            activity_id = activity["activity_id"]
            previous = activities.get(activity_id)
            if previous is None:
                activities[activity_id] = activity
                order.append(activity_id)
                continue
            terminal_previous = str(previous.get("status") or "") in TERMINAL_ACTIVITY_STATES
            terminal_current = str(activity.get("status") or "") in TERMINAL_ACTIVITY_STATES
            activities[activity_id] = {
                **previous,
                **activity,
                "status": previous.get("status") if terminal_previous and not terminal_current else activity.get("status"),
                "occurred_at": previous.get("occurred_at") or activity.get("occurred_at"),
                "started_at": previous.get("started_at") or activity.get("started_at"),
                "updated_at": activity.get("updated_at") or previous.get("updated_at"),
                "completed_at": activity.get("completed_at") or previous.get("completed_at"),
                "requires_attention": (
                    previous.get("requires_attention")
                    if terminal_previous and not terminal_current
                    else activity.get("requires_attention")
                ),
                "subject": activity.get("subject") or previous.get("subject"),
                "subject_i18n": {
                    **dict(previous.get("subject_i18n") or {}),
                    **dict(activity.get("subject_i18n") or {}),
                },
                "summary": activity.get("summary") or previous.get("summary"),
                "summary_i18n": {
                    **dict(previous.get("summary_i18n") or {}),
                    **dict(activity.get("summary_i18n") or {}),
                },
                "detail": {**dict(previous.get("detail") or {}), **dict(activity.get("detail") or {})},
                "references": cls._merge_references(
                    list(previous.get("references") or []),
                    list(activity.get("references") or []),
                ),
            }
        return cls._coalesce_presentation_groups([activities[key] for key in order])

    @classmethod
    def _coalesce_presentation_groups(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for row in rows:
            group_key = str(row.get("_group_key") or "")
            output_key = f"group:{group_key}" if group_key else f"activity:{row.get('activity_id')}"
            previous = grouped.get(output_key)
            if previous is None:
                initial = dict(row)
                if group_key:
                    initial["activity_id"] = f"tool-group:{hashlib.sha256(group_key.encode('utf-8')).hexdigest()[:20]}"
                grouped[output_key] = initial
                order.append(output_key)
                continue
            count = int(previous.get("occurrence_count") or 1) + int(row.get("occurrence_count") or 1)
            statuses = {str(previous.get("status") or ""), str(row.get("status") or "")}
            if statuses & {"running", "pending", "waiting", "waiting_user", "waiting_human"}:
                status = next(item for item in ("waiting_user", "waiting_human", "waiting", "running", "pending") if item in statuses)
            elif statuses & {"failed", "error", "interrupted"}:
                status = next(item for item in ("failed", "error", "interrupted") if item in statuses)
            else:
                status = str(row.get("status") or previous.get("status") or "observed")
            grouped[output_key] = {
                **previous,
                "activity_id": f"tool-group:{hashlib.sha256(group_key.encode('utf-8')).hexdigest()[:20]}",
                "seq": max(int(previous.get("seq") or 0), int(row.get("seq") or 0)),
                "status": status,
                "subject": previous.get("_group_subject") or previous.get("subject"),
                "subject_i18n": dict(previous.get("_group_subject_i18n") or previous.get("subject_i18n") or {}),
                "summary": row.get("summary") or previous.get("summary"),
                "summary_i18n": {**dict(previous.get("summary_i18n") or {}), **dict(row.get("summary_i18n") or {})},
                "updated_at": row.get("updated_at") or previous.get("updated_at"),
                "completed_at": row.get("completed_at") or previous.get("completed_at"),
                "requires_attention": bool(previous.get("requires_attention") or row.get("requires_attention")),
                "occurrence_count": count,
                "detail": {**dict(previous.get("detail") or {}), **dict(row.get("detail") or {}), "count": count},
                "references": cls._merge_references(
                    list(previous.get("references") or []),
                    list(row.get("references") or []),
                ),
            }
        output = []
        for key in order:
            item = dict(grouped[key])
            item.pop("_group_key", None)
            item.pop("_group_subject", None)
            item.pop("_group_subject_i18n", None)
            output.append(item)
        return output

    @classmethod
    def _localized_group_title(cls, presentation: Dict[str, Any]) -> Dict[str, str]:
        values = presentation.get("title_i18n") if isinstance(presentation.get("title_i18n"), dict) else {}
        return {
            str(language): cls._display_text(value)[:600]
            for language, value in values.items()
            if cls._display_text(value)
        }

    @classmethod
    def _tool_projection_key(cls, row: Dict[str, Any]) -> tuple[str, str]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        execution_scope = str(
            row.get("conversation_turn_id")
            or payload.get("conversation_turn_id")
            or row.get("action_loop_id")
            or payload.get("action_loop_id")
            or ""
        )
        subject = cls._subject(str(row.get("event_type") or ""), payload)
        return execution_scope, subject

    @staticmethod
    def _is_visible_activity(activity: Dict[str, Any]) -> bool:
        kind = str(activity.get("kind") or "")
        if kind not in VISIBLE_ACTIVITY_KINDS:
            return False
        parts = str(activity.get("event_type") or "").split(".")
        if parts[:2] == ["task", "execution"]:
            return False
        # Resource nodes are represented by the resource service's own lifecycle.
        # Keeping both would expose the reasoning implementation as duplicate UI work.
        if parts and parts[0] == "reasoning" and kind in {"tool", "memory"}:
            return False
        return True

    @classmethod
    def _activity_id(cls, row: Dict[str, Any], *, kind: str, subject: str) -> str:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        run_id = cls._event_run_id(row)
        candidates = (
            payload.get("activity_id"),
            payload.get("tool_call_id"),
            payload.get("node_id"),
            f"{run_id}:{payload.get('step_id')}" if run_id and payload.get("step_id") else None,
            payload.get("proposal_id"),
            payload.get("decision_id"),
            payload.get("artifact_id"),
            payload.get("tree_id"),
            payload.get("environment_id"),
            payload.get("request_id"),
            payload.get("path") if kind == "artifact" else None,
            run_id,
            row.get("task_id"),
            row.get("event_id"),
            f"seq:{row.get('seq')}",
        )
        identity = next((str(value) for value in candidates if value not in (None, "")), "unknown")
        return f"{kind}:{identity}"

    @staticmethod
    def _kind(event_type: str, payload: Optional[Dict[str, Any]] = None) -> str:
        parts = event_type.split(".")
        prefix = event_type.split(".", 1)[0]
        payload_kind = str((payload or {}).get("kind") or "").strip().lower()
        if payload_kind in VISIBLE_ACTIVITY_KINDS:
            return payload_kind
        if event_type == EventType.ACTION_OBSERVATION_COMMITTED.value:
            return "tool"
        if len(parts) > 1 and prefix == "reasoning" and parts[1] in {"tool", "memory"}:
            return parts[1]
        return {
            "task": "task",
            "workflow": "workflow",
            "tool": "tool",
            "memory": "memory",
            "reasoning": "reasoning",
            "environment": "environment",
            "workspace": "artifact" if "artifact" in event_type else "workspace",
            "request": "request",
            "gateway": "request",
            "interaction": "conversation",
            "conversation": "conversation",
        }.get(prefix, "runtime")

    @staticmethod
    def _subject(event_type: str, payload: Dict[str, Any]) -> str:
        declared_kind = str(payload.get("kind") or "").strip().lower()
        presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}
        presented_title = str(presentation.get("title") or "").strip()
        presented_subject = str(presentation.get("subject") or "").strip()
        if presented_title:
            return WorkbenchProjection._join_title(presented_title, presented_subject)
        tool_spec = payload.get("tool_spec") if isinstance(payload.get("tool_spec"), dict) else {}
        tool_metadata = tool_spec.get("metadata") if isinstance(tool_spec.get("metadata"), dict) else {}
        for value in (
            payload.get("title"),
            payload.get("name"),
            payload.get("step_name"),
            tool_metadata.get("display_name"),
            tool_metadata.get("title"),
            payload.get("tool_name"),
            payload.get("tool_id"),
            payload.get("service_name"),
            payload.get("query"),
            payload.get("workflow_id"),
            payload.get("path"),
            payload.get("action"),
            payload.get("goal"),
            payload.get("memory_type"),
        ):
            if value:
                return str(value)
        if declared_kind in VISIBLE_ACTIVITY_KINDS:
            return declared_kind
        return ""

    @classmethod
    def _summary(cls, payload: Dict[str, Any], *, subject: str) -> str:
        presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}
        presented = cls._display_text(presentation.get("summary"))
        if presented and presented != subject:
            return presented[:600]
        for key in (
            "observation",
            "summary",
            "result_summary",
            "structured_result",
            "query",
            "goal",
            "reason",
            "decision",
            "error_detail",
            "error",
        ):
            text = cls._display_text(payload.get(key))
            if text and text != subject:
                return text[:280]
        tool_spec = payload.get("tool_spec") if isinstance(payload.get("tool_spec"), dict) else {}
        description = cls._display_text(tool_spec.get("description"))
        if description and description != subject:
            return description[:280]
        return ""

    @classmethod
    def _localized_text(
        cls,
        payload: Dict[str, Any],
        field: str,
        *,
        subject: str = "",
    ) -> Dict[str, str]:
        presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}
        values = presentation.get(field) if isinstance(presentation.get(field), dict) else {}
        presented_subject = str(presentation.get("subject") or "").strip()
        output: Dict[str, str] = {}
        for language, value in values.items():
            text = cls._display_text(value)
            if not text:
                continue
            if field == "title_i18n":
                text = cls._join_title(text, presented_subject)
            if text != subject:
                output[str(language)] = text[:600]
        return output

    @staticmethod
    def _join_title(title: str, subject: str) -> str:
        if not subject or subject.casefold() in title.casefold():
            return title
        return f"{title} · {subject}"

    @classmethod
    def _display_text(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            for key in ("message", "summary", "text", "content", "result", "reason"):
                text = cls._display_text(value.get(key))
                if text:
                    return text
            return ""
        if isinstance(value, (list, tuple)):
            return " · ".join(filter(None, (cls._display_text(item) for item in value[:3])))
        return ""

    @staticmethod
    def _status_from_event(event_type: str) -> str:
        suffix = event_type.rsplit(".", 1)[-1]
        return {
            "started": "running",
            "start": "running",
            "finished": "completed",
            "complete": "completed",
            "completed": "completed",
            "failed": "failed",
            "error": "failed",
            "paused": "paused",
            "resumed": "running",
            "interrupted": "interrupted",
            "stopped": "stopped",
            "removed": "completed",
        }.get(suffix, "observed")

    @staticmethod
    def _detail(payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = (
            "tool_name", "tool_call_id", "observation_id", "error", "usage", "finish_reason", "max_tokens",
            "from_status", "to_status", "reason", "current_step_id", "operation",
            "path", "size", "decision", "persisted", "result_summary", "observation",
            "error_detail", "required_capability", "result_metadata",
            "environment_id", "workspace_id", "entrypoint", "port", "revision", "action",
            "selected", "dropped", "count", "attempt_count",
        )
        detail = {key: payload[key] for key in allowed if payload.get(key) not in (None, "")}
        arguments = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        if arguments:
            detail["arguments"] = arguments
        tool_spec = payload.get("tool_spec") if isinstance(payload.get("tool_spec"), dict) else {}
        description = str(tool_spec.get("description") or "").strip()
        if description:
            detail["description"] = description
        result_summary = payload.get("result_summary")
        if result_summary not in (None, ""):
            detail["result_summary"] = result_summary
        return detail

    @classmethod
    def _references(cls, payload: Dict[str, Any], *, kind: str) -> List[Dict[str, Any]]:
        references: List[Dict[str, Any]] = []

        def add(reference_kind: str, target: Any, label: Any = "", **metadata: Any) -> None:
            normalized_target = str(target or "").strip()
            if not normalized_target:
                return
            if reference_kind == "url" and not normalized_target.lower().startswith(("http://", "https://")):
                return
            normalized_label = str(label or normalized_target).strip() or normalized_target
            reference_id = f"{reference_kind}:{normalized_target}"
            references.append({
                "reference_id": reference_id,
                "kind": reference_kind,
                "label": normalized_label[:180],
                "target": normalized_target,
                "metadata": {key: value for key, value in metadata.items() if value not in (None, "")},
            })

        path = payload.get("path")
        if path and kind == "artifact":
            add("artifact", path, path, workspace_id=payload.get("workspace_id"))

        environment_id = payload.get("environment_id")
        if environment_id:
            add(
                "canvas",
                environment_id,
                payload.get("name") or payload.get("title") or environment_id,
                workspace_id=payload.get("workspace_id"),
            )

        proposal_id = payload.get("proposal_id")
        if proposal_id:
            add("memory_review", proposal_id, payload.get("title") or proposal_id)

        result_metadata = payload.get("result_metadata")
        if isinstance(result_metadata, dict):
            direct_url = result_metadata.get("url")
            if direct_url:
                add("url", direct_url, result_metadata.get("title") or direct_url)
            direct_path = result_metadata.get("path") or result_metadata.get("output_path")
            if direct_path:
                add("artifact", direct_path, result_metadata.get("title") or direct_path, workspace_id=result_metadata.get("workspace_id"))

            for source in result_metadata.get("sources") or []:
                if isinstance(source, dict) and source.get("url"):
                    add(
                        "url",
                        source.get("url"),
                        source.get("title") or source.get("source") or source.get("url"),
                        source=source.get("source"),
                    )
            for collection_name in ("artifacts", "files"):
                for item in result_metadata.get(collection_name) or []:
                    if isinstance(item, dict):
                        item_path = item.get("path") or item.get("output_path")
                        if item_path:
                            add("artifact", item_path, item.get("title") or item.get("name") or item_path, workspace_id=item.get("workspace_id"))

        presentation = payload.get("presentation")
        if isinstance(presentation, dict):
            for reference in presentation.get("references") or []:
                if not isinstance(reference, dict):
                    continue
                add(
                    str(reference.get("kind") or "reference"),
                    reference.get("target"),
                    reference.get("label"),
                    **dict(reference.get("metadata") or {}),
                )

        return cls._merge_references([], references)[:24]

    @staticmethod
    def _merge_references(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for group in groups:
            for reference in group:
                if not isinstance(reference, dict):
                    continue
                reference_id = str(reference.get("reference_id") or "").strip()
                if not reference_id:
                    continue
                if reference_id not in merged:
                    order.append(reference_id)
                merged[reference_id] = {**merged.get(reference_id, {}), **reference}
        return [merged[reference_id] for reference_id in order]

    @staticmethod
    def _waiting_actions(
        task: Optional[Dict[str, Any]],
        proposals: List[Dict[str, Any]],
        recovery: List[Dict[str, Any]],
        timeline: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows = [
            {"kind": "memory_confirmation", "id": row.get("proposal_id"), "task_id": (task or {}).get("task_id")}
            for row in proposals
        ]
        rows.extend(
            {
                "kind": "workflow_recovery",
                "id": row.get("workflow_run_id"),
                "task_id": row.get("task_id"),
                "status": row.get("status"),
            }
            for row in recovery
        )
        rows.extend(
            {
                "kind": "environment_recovery",
                "id": activity.get("detail", {}).get("environment_id"),
                "task_id": activity.get("task_id"),
                "status": activity.get("status"),
            }
            for activity in timeline
            if activity.get("kind") == "environment" and activity.get("status") == "interrupted"
        )
        return rows
