"""Continuous, opt-in agency over existing cognition and execution services."""
from __future__ import annotations

import asyncio
import json
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from loguru import logger

from config import config
from .ambient_state import AmbientExecution, AmbientStore, bind_ambient, current_ambient
from .delegation import DelegationScope, _Budget, bind_delegation
from .models.run_context import RunContext
from .models.session_state import SessionState
from .protocol import EventType
from .public_contracts import AmbientSettings, AmbientState
from .task_service import TaskExecutionConflict


RUN_TYPE = "ambient"
ACTIVE = {"pending", "running", "paused", "waiting_human", "waiting_user"}


class AmbientService:
    """Own proactive admission and delivery, never cognition or domain truth."""

    def __init__(self, *, conversation, task_runtime, task_service, storage_path=None):
        self.conversation, self.runtime, self.tasks = conversation, task_runtime, task_service
        self.self_model = conversation.self_model_service
        if self.self_model is None:
            raise ValueError("Ambient requires the existing SelfModelService")
        self.store = AmbientStore(storage_path or Path(__file__).resolve().parents[1] / ".runtime" / "ambient" / "state.json", cognition_store=self.self_model.state)
        emitter = conversation.event_emitter
        self.event_log = getattr(emitter, "event_log", None)
        if self.event_log:
            self.event_log.ensure_consumer("ambient.v1", start_at_tail=True)
        if emitter:
            for event in (EventType.INTERACTION_COMPLETED, EventType.MEMORY_REPLAY_COMPLETED, EventType.GOAL_GAPS_UPDATED, EventType.TASK_EXECUTION_SETTLED, EventType.ENVIRONMENT_STATE_CHANGED, EventType.SEMANTIC_UI_INTERACTED, EventType.UI_CONTEXT_CHANGED):
                emitter.on(event, self._observe)

    def _config(self, user):
        service = self.conversation.config_service
        return service.get_merged_config(user) if service is not None else config.model_dump()

    def _session(self, user, session):
        manager = self.conversation.message_manager
        result = manager.get_session(session, user_id=user) if manager else None
        if result is None:
            raise KeyError("conversation not found")
        return result

    def _enabled(self, scene):
        return bool(config.ambient.enabled and scene.settings.enabled and self._config(scene.user_id).get("ambient", {}).get("enabled", True))

    def configure(self, user, session, settings):
        if session:
            self._session(user, session)
        scene = self.store.get(user)
        if settings.enabled and not scene.session_id:
            manager = self.conversation.message_manager
            recent = manager.list_sessions(user_id=user, limit=1)
            scene.session_id = session or (recent[0]["session_id"] if recent else manager.create_session(user_id=user))
        changed = scene.settings.direction != settings.direction
        previous_task = self.tasks.get_task(scene.task_id, user_id=user) if scene.task_id else None
        related = [item for item in self.tasks.list_tasks(user_id=user, limit=10000) if previous_task and item["task_id"] != previous_task["task_id"] and (self.root_for(item) or {}).get("task_id") == previous_task["task_id"]]
        if changed:
            scene.generation += 1
            scene.task_id, scene.admission = None, None
        scene.settings = settings
        scene.revision += 1
        scene.dirty = True
        scene.next_check_at = time.time()
        self.store.put(scene)
        for previous_task in ([previous_task] if previous_task else []) + related:
            if changed:
                self.runtime.cancel_task(task_id=previous_task["task_id"], user_id=user, reason="ambient_direction_changed")
            elif not settings.enabled and previous_task["status"] not in {"paused", "cancelled"}:
                self.runtime.pause_task(task_id=previous_task["task_id"], user_id=user)
            elif settings.enabled and previous_task["status"] == "paused":
                self.runtime.resume_task(task_id=previous_task["task_id"], user_id=user)
        return self.view(user, session)

    def root_for(self, task):
        """Use existing Task lineage, not a second descendant registry."""
        seen = set()
        while task and task["task_id"] not in seen:
            seen.add(task["task_id"])
            if task.get("source") == RUN_TYPE:
                return task
            parent = task.get("metadata", {}).get("delegation", {}).get("parent_task_id")
            task = self.tasks.get_task(parent, user_id=task["user_id"]) if parent else None
        return None

    def descendant_authority(self, task):
        root = self.root_for(task)
        if root is None:
            return None
        scene = self.store.get(root["user_id"], root["metadata"]["ambient_session"])
        if not self._enabled(scene) or scene.task_id != root["task_id"] or scene.generation != root["metadata"]["generation"]:
            raise PermissionError("ambient ancestor authority has been revoked")
        return scene

    def validate_scheduled_scope(self, user, authority):
        scene = self.store.get(user)
        if not self._enabled(scene) or scene.task_id != authority.get("task_id") or scene.generation != authority.get("generation"):
            raise PermissionError("scheduled autonomous authority has been revoked")

    def wake_for_reports(self, task, message_ids):
        scene = self.descendant_authority(task)
        if scene is None or scene.last_trigger.get("message_ids") == message_ids:
            return
        scene.last_trigger = {"event_type": "agent.reports", "message_ids": message_ids}
        scene.dirty = True
        scene.next_check_at = min(scene.next_check_at, time.time() + config.ambient.cooldown_s)
        scene.revision += 1
        self.store.put(scene)

    def view(self, user, session):
        if session:
            self._session(user, session)
        scene = self.store.get(user)
        task = self.tasks.get_task(scene.task_id, user_id=user) if scene.task_id else None
        run = (task or {}).get("runs", [])[-1:] or [{}]
        pending = run[0].get("metadata", {}).get("pending_action")
        status = "disabled" if not self._enabled(scene) else (task or {}).get("status", "idle")
        if self._enabled(scene) and pending and run[0].get("status") == "waiting_human":
            status = "waiting_confirmation"
        elif status == "waiting_user":
            status = "idle"
        usage = self.store.usage.get(user, {})
        cognition = self.self_model.state.get(user)
        if status == "idle" and usage.get("day") == datetime.now(timezone.utc).date().isoformat() and usage.get("cycles", 0) >= config.ambient.daily_cycles:
            status = "budget_exhausted"
        return AmbientState(
            session_id=scene.session_id or None, user_id=user, available=config.ambient.enabled, settings=scene.settings,
            revision=scene.revision, status=status, task_id=scene.task_id,
            attention=cognition.attention, questions=cognition.questions, reflection=cognition.interpretation,
            next_check_at=scene.next_check_at or None,
            pending={"run_id": run[0]["run_id"], "tool_call_id": pending["tool_call_id"], "tool_name": pending["tool_name"], "args": pending.get("args") or {}} if pending and status == "waiting_confirmation" else None,
        ).model_dump()

    def _observe(self, event):
        payload = event.payload
        user, session = payload.get("user_id"), payload.get("session_id")
        if not user:
            return
        task = self.tasks.get_task(payload.get("task_id", ""), user_id=user)
        if task and self.root_for(task):
            return  # own settlements must not generate a self-exciting event loop
        for saved in list(self.store.scenes.values()):
            if saved.user_id != user or not saved.settings.enabled:
                continue
            scene = self.store.get(user, saved.session_id)
            if event.seq and int(scene.last_trigger.get("seq") or 0) >= int(event.seq):
                continue
            scene.dirty = True
            scene.next_check_at = min(scene.next_check_at, time.time() + config.ambient.cooldown_s)
            scene.last_trigger = {"event_id": event.event_id, "event_type": event.event.value, "seq": event.seq}
            scene.revision += 1
            self.store.put(scene)

    def available(self, task):
        scene = self.store.get(task["user_id"], task["metadata"]["ambient_session"])
        manager = self.conversation.message_manager
        if scene.task_id != task["task_id"] or not self._enabled(scene) or not manager:
            return False
        if not manager.get_session(scene.session_id, user_id=scene.user_id) or manager.has_active_user_turn(scene.user_id):
            return False
        if self.conversation.agent_is_active(scene.user_id, scene.session_id):
            return False
        active = set(self.runtime.active_run_ids())
        occupied = sum(run["run_id"] in active for row in self.tasks.execution_tasks(run_type=RUN_TYPE) for run in row["runs"])
        return occupied < config.ambient.max_parallel

    def recover(self):
        if self.runtime._shutting_down or not config.ambient.enabled:
            return
        if self.event_log:
            cursor = self.event_log.get_consumer_cursor("ambient.v1")
            for row in self.event_log.query(after_seq=cursor, limit=200, oldest_first=True):
                kind = EventType(row["event_type"]) if row["event_type"] in EventType._value2member_map_ else None
                if kind in {EventType.INTERACTION_COMPLETED, EventType.MEMORY_REPLAY_COMPLETED, EventType.GOAL_GAPS_UPDATED, EventType.TASK_EXECUTION_SETTLED, EventType.ENVIRONMENT_STATE_CHANGED, EventType.SEMANTIC_UI_INTERACTED, EventType.UI_CONTEXT_CHANGED}:
                    self._observe(SimpleNamespace(payload=row.get("payload", {}), event=kind, event_id=row["event_id"], seq=row["seq"]))
                self.event_log.commit_consumer_cursor("ambient.v1", row["seq"])
        now = time.time()
        for task in self.tasks.execution_tasks(run_type=RUN_TYPE):
            saved = self.store.scenes.get(task["user_id"])
            if saved and saved.task_id and saved.task_id != task["task_id"] and task["status"] != "cancelled":
                self.runtime.cancel_task(task_id=task["task_id"], user_id=task["user_id"], reason="personal_attention_consolidated")
        for saved in list(self.store.scenes.values()):
            scene = self.store.get(saved.user_id, saved.session_id)
            if not self._enabled(scene):
                continue
            manager = self.conversation.message_manager
            if not manager:
                continue
            if not manager.get_session(scene.session_id, user_id=scene.user_id):
                # A deleted transcript does not delete the personal Agent/Task.
                scene.session_id = manager.create_session(scene.session_id or None, user_id=scene.user_id)
                self.store.put(scene)
            task = self.tasks.get_task(scene.task_id, user_id=scene.user_id) if scene.task_id else None
            if task and (task["status"] in {"paused", "cancelled"} or any(run["status"] in ACTIVE for run in task["runs"])):
                continue
            if scene.admission:
                prior = next((row for row in (task or {}).get("runs", []) if row["run_id"] == scene.admission["run_id"]), None)
                if prior:
                    scene.admission = None
                    self.store.put(scene)
                    continue
            if not scene.admission:
                if now < scene.next_check_at or manager.has_active_user_turn(scene.user_id):
                    continue
                if self.conversation.agent_is_active(scene.user_id, scene.session_id):
                    continue
                day = datetime.now(timezone.utc).date().isoformat()
                usage = self.store.usage.get(scene.user_id, {})
                used = int(usage.get("cycles", 0)) if usage.get("day") == day else 0
                if used >= config.ambient.daily_cycles:
                    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    if scene.next_check_at < tomorrow:
                        scene.next_check_at = tomorrow
                        self.store.put(scene)
                    continue
                if task is None:
                    # Recover an actor created just before a situation-store failure.
                    task = next((item for item in self.tasks.list_tasks(user_id=scene.user_id, limit=10000) if item.get("source") == RUN_TYPE and item.get("metadata", {}).get("ambient_session") == scene.session_id and item["metadata"].get("generation") == scene.generation and item["status"] != "cancelled"), None)
                    if task is None:
                        task = self.tasks.create_task(user_id=scene.user_id, session_id=scene.session_id, title=self._session(scene.user_id, scene.session_id)["title"], source=RUN_TYPE, metadata={"ambient_session": scene.session_id, "generation": scene.generation, "continuable": True})
                    scene.task_id = task["task_id"]
                scene.admission = {"run_id": f"ambient_{uuid4().hex}", "revision": scene.revision, "generation": scene.generation, "trigger": scene.last_trigger or {"event_type": "ambient.periodic"}}
                scene.dirty = False
                scene.next_check_at = now + config.ambient.interval_s
                previous = deepcopy(self.store.usage)
                self.store.usage[scene.user_id] = {"day": day, "cycles": used + 1}
                try:
                    self.store.put(scene)
                except Exception:
                    self.store.usage = previous
                    raise
            # Durable admission is written first; retrying start_run is idempotent.
            self.tasks.start_run(task_id=scene.task_id, user_id=scene.user_id, run_id=scene.admission["run_id"], run_type=RUN_TYPE, session_id=scene.session_id, status="pending", metadata=scene.admission)

    def assert_execution(self):
        frame = current_ambient()
        if frame is None or not frame.active or frame.service is not self:
            raise PermissionError("an active Ambient Runtime execution is required")
        context = frame.context
        scene = self.store.get(context.user_id, context.session_id)
        if not self._enabled(scene) or scene.generation != frame.generation:
            raise PermissionError("ambient authority has been revoked")
        task = self.tasks.get_task(context.task_id, user_id=context.user_id)
        if task is None or self.descendant_authority(task) is None:
            raise PermissionError("execution is outside this ambient task lineage")
        self.tasks.assert_action_execution(task_id=context.task_id, user_id=context.user_id, expected_objective=task["objective"], task_run_id=context.task_run_id, execution_token=context.execution_token)
        return frame, scene

    def annotate(self, *, message_id, selected_text, start_offset, end_offset, title, content, session_id=None):
        frame, scene = self.assert_execution()
        manager = self.conversation.message_manager
        target = session_id or scene.session_id
        session = self._session(scene.user_id, target)
        existing = next((row for row in session["followups"] if row.get("source") == "agent" and row["message_id"] == message_id and row["start_offset"] == start_offset and row["end_offset"] == end_offset and row["query"] == title and row["response"] == content), None)
        if existing:
            return {"annotation_id": existing["id"], "status": existing.get("state", "open")}
        if frame.notes >= 3:
            raise ValueError("annotation budget exhausted for this activation")
        result = manager.add_followup(target, user_id=scene.user_id, message_id=message_id, selected_text=selected_text, start_offset=start_offset, end_offset=end_offset, query_type="initiative", custom_query=None, query=title, response=content, source="agent")
        if result is None:
            raise ValueError("annotation must match an exact visible message span")
        frame.notes += 1
        return {"annotation_id": result["id"], "status": "open"}

    async def say(self, content, session_id=None):
        frame, scene = self.assert_execution()
        manager = self.conversation.message_manager
        target = session_id or scene.session_id
        self._session(scene.user_id, target)
        turn = f"ambient_notice_{frame.context.task_run_id}"
        messages = self.conversation.background_agents.messages
        retained = next((row for row in messages.pending_communications(scene.user_id) if row["content"] == content and row["session_id"] == target), None)
        if retained:
            turn = retained["message_id"]
        existing = next((row for row in manager.get_messages(target, user_id=scene.user_id) if row.get("conversation_turn_id") == turn), None)
        if existing:
            return {"ok": True, "already_sent": True, "content": existing["content"], "conversation_turn_id": turn}
        admission = messages.communication_admission(scene.user_id, content, delivery_id=turn)
        if not admission["allowed"]:
            if admission["status"] == "deferred":
                if not retained:
                    messages.defer_communication(frame.context, session_id=target, content=content, delivery_id=turn)
                scene.next_check_at = min(scene.next_check_at, time.time() + admission["retry_after_s"])
                scene.revision += 1
                self.store.put(scene)
                return {**admission, "retained": True}
            if retained:
                self.tasks.acknowledge_agent_messages(user_id=scene.user_id, message_ids=[turn])
            return admission
        if not manager.begin_turn(target, turn, "runtime", "", scene.user_id):
            raise RuntimeError("could not begin ambient notice")
        if not manager.commit_turn(target, turn, content, user_id=scene.user_id, agent_message_ids=[turn]):
            raise RuntimeError("could not commit ambient notice")
        if retained:
            self.tasks.acknowledge_agent_messages(user_id=scene.user_id, message_ids=[turn])
        await messages.record_communication(user_id=scene.user_id, session_id=target, kind="ambient", content=content, delivery_id=turn)
        return {"ok": True, "conversation_turn_id": turn}

    def feedback(self, user, session, feedback):
        if session:
            self._session(user, session)
        manager = self.conversation.message_manager
        target = session or self.store.get(user).session_id
        note = manager.set_followup_state(target, user_id=user, followup_id=feedback.annotation_id, state=feedback.decision)
        if note is None:
            raise KeyError("agent annotation not found")
        scene = self.store.get(user)
        self.self_model.state.update(user, lambda row: setattr(row, "feedback", [*row.feedback, {**feedback.model_dump(), "query": note["query"], "response": note["response"]}][-30:]))
        scene.revision += 1
        scene.dirty = True
        scene.next_check_at = min(scene.next_check_at, time.time() + config.ambient.cooldown_s)
        self.store.put(scene)
        return self.view(user, session)

    def _context(self, task, run, token, scene):
        context = RunContext(request_id=run["run_id"], trace_id=run["run_id"], task_id=task["task_id"], task_run_id=run["run_id"], execution_token=token, conversation_turn_id=run["run_id"], session_state=SessionState(session_id=scene.session_id, user_id=scene.user_id, trace_id=run["run_id"]), input_payload={"metadata": {"origin": RUN_TYPE, "multi_agent": True, "ui_language": scene.settings.ui_language, "timezone": scene.settings.timezone}})
        workspace = self.conversation.capability_service.workspace_service
        if workspace is not None:
            context.workspace_handle = workspace.resolve_workspace_handle(user_id=scene.user_id, workspace_id=scene.session_id).model_dump()
        return context

    async def run(self, task, run, token):
        from agentkit.security.approval import approval_scope

        scene = self.store.get(task["user_id"], task["metadata"]["ambient_session"])
        if not self._enabled(scene) or run["metadata"]["generation"] != scene.generation:
            return {"status": "cancelled", "detail": {"error": "ambient scope changed"}}
        context = self._context(task, run, token, scene)
        checkpoint = run["metadata"].get("checkpoint") or {}
        context.agent_message_ids = checkpoint.get("agent_message_ids", [])
        scope = DelegationScope(_Budget(count=int(checkpoint.get("delegation_spent") or 0)), agent_task_id=task["task_id"], workspace_id=scene.session_id)
        def save(value):
            self.tasks.checkpoint_run(task_id=task["task_id"], user_id=scene.user_id, run_id=run["run_id"], token=token, checkpoint={**value, "agent_message_ids": context.agent_message_ids, "delegation_spent": scope.budget.count})
        async with self.conversation.agent_execution(scene.user_id, scene.session_id):
            if self.conversation.message_manager.has_active_user_turn(scene.user_id):
                return {"status": "pending", "detail": {}}
            with bind_ambient(AmbientExecution(self, context, scene.generation)), bind_delegation(scope), approval_scope("ambient.activation", {}, confirmed=False):
                try:
                    async with asyncio.timeout(config.ambient.timeout_s):
                        result = await self.conversation.run_ambient_turn(run_context=context, situation={"initiative": scene.model_dump(exclude={"admission"}), "cognition": self.self_model.working_context(scene.user_id)}, checkpoint_sink=save, checkpoint=run["metadata"].get("checkpoint"))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.assert_execution()
                    logger.warning("Ambient activation paused ({}): {}", type(exc).__name__, str(exc)[:300])
                    return {"status": "paused", "detail": {"error": "ambient activation interrupted; resume from checkpoint"}}
            return self.finish(task, run, result)

    def finish(self, task, run, result):
        status = result.get("status")
        detail = {"output": str(result.get("content") or "")[:4000], "error": result.get("error"), "usage": result.get("usage"), "agent_message_ids": result.get("agent_message_ids", [])}
        if status == "needs_confirmation":
            detail["pending_action"] = result
            return {"status": "waiting_human", "detail": detail}
        detail["pending_action"] = None
        return {"status": "completed" if status == "success" else "failed", "detail": detail}

    async def confirm(self, user, session, command):
        scene = self.store.get(user, session)
        if session:
            self._session(user, session)
        if not self._enabled(scene):
            raise PermissionError("ambient mode is disabled")

        async def continue_action(task, run, token, pending):
            from agentkit.security.approval import approval_scope
            from .capability_service import ToolInvocationContext

            if task["task_id"] != scene.task_id or run["metadata"]["generation"] != scene.generation:
                raise TaskExecutionConflict("ambient context changed")
            context = self._context(task, run, token, scene)
            context.agent_message_ids = pending.get("agent_message_ids", [])
            scope = DelegationScope(_Budget(count=int((run["metadata"].get("checkpoint") or {}).get("delegation_spent") or 0)), agent_task_id=task["task_id"], workspace_id=scene.session_id)
            user_config = deepcopy(self._config(user))
            user_config.setdefault("api", {})["max_tokens"] = min(int(user_config.get("api", {}).get("max_tokens") or config.ambient.max_tokens), config.ambient.max_tokens)
            user_config.setdefault("action", {}).setdefault("gaps", {})["enabled"] = False
            async def execute(name, arguments):
                return await self.conversation.capability_service.call_tool(name, arguments, run_context=context, user_config=user_config, ctx=ToolInvocationContext(session_id=scene.session_id, user_id=user, source=RUN_TYPE, metadata={"run_context": context, "user_config": user_config}))
            def save(value):
                self.tasks.checkpoint_run(task_id=task["task_id"], user_id=user, run_id=run["run_id"], token=token, checkpoint={**value, "agent_message_ids": context.agent_message_ids, "delegation_spent": scope.budget.count})
            with bind_ambient(AmbientExecution(self, context, scene.generation)), bind_delegation(scope), approval_scope("ambient.continuation", {}, confirmed=False):
                method = self.conversation.resume_action if command.action == "approve" else self.conversation.reject_pending_action
                args = {"approved_call_id": command.tool_call_id} if command.action == "approve" else {}
                async with asyncio.timeout(config.ambient.timeout_s):
                    return await method(pending=pending, run_context=context, session_id=scene.session_id, user_id=user, user_config=user_config, tool_executor=execute, checkpoint_sink=save, **args)

        await self.runtime.continue_confirmation(task_id=scene.task_id, user_id=user, run_id=command.run_id, call_id=command.tool_call_id, operation=continue_action)
        return self.view(user, session)
