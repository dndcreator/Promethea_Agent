"""Persistent child inbox and Action driver hosted by the existing TaskRuntime."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from loguru import logger

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import MultiAgentConfig, config
from .delegation import (
    DelegationScope, _Budget, bind_delegation, child_configuration,
    current_delegation, delegation_enabled, delegation_limits,
)
from .models.run_context import RunContext
from .models.session_state import SessionState
from .tools.projection import project_capability_snapshot
from .agent_messages import AgentMessages, INBOX_RUN_TYPE


RUN_TYPE = "subagent"


class ChildDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    parent_session_id: str = Field(min_length=1, max_length=200)
    parent_agent_task_id: str | None = None
    parent_task_id: str | None = None
    parent_action_loop_id: str | None = None
    ancestor_action_loop_ids: list[str] = Field(max_length=3)
    depth: int = Field(ge=1, le=3)
    allowed_tools: list[str] = Field(max_length=2048)
    tool_policy: dict
    workspace_id: str = Field(min_length=1, max_length=200)
    limits: dict
    language: dict

    @field_validator("limits")
    @classmethod
    def validate_limits(cls, value):
        allowed = set(delegation_limits({}))
        if set(value) != allowed:
            raise ValueError("child limits must be complete")
        checked = MultiAgentConfig(**value)
        return {key: getattr(checked, key) for key in allowed}


class AgentControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["list", "get", "send", "interrupt", "resume", "cancel"]
    child_id: str | None = Field(default=None, min_length=1, max_length=160)
    message: str | None = Field(default=None, min_length=1, max_length=16000)


class BackgroundAgents:
    """Own child descriptors and message semantics, not execution leases or loops."""

    def __init__(self, *, conversation, task_runtime, task_service):
        self.conversation = conversation
        self.runtime = task_runtime
        self.tasks = task_service
        self.messages = AgentMessages(self)

    def recover(self):
        self.messages.recover()

    @staticmethod
    def _descriptor(task):
        value = (task.get("metadata") or {}).get("delegation")
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported or missing child descriptor")
        return ChildDescriptor.model_validate(value).model_dump()

    def _owned(self, child_id, parent):
        task = self.tasks.get_task(child_id, user_id=parent.user_id)
        if task is None:
            raise KeyError("child agent not found")
        descriptor = self._descriptor(task)
        scope = current_delegation()
        if scope is not None and scope.depth:
            authorized = not scope.closed and scope.agent_task_id and descriptor.get("parent_agent_task_id") == scope.agent_task_id
        else:
            authorized = not descriptor.get("parent_agent_task_id") and descriptor["parent_session_id"] == parent.session_id
        if not authorized:
            raise PermissionError("only the owning parent can address this child")
        return task

    def available(self, task):
        user_config = self._config(task["user_id"])
        if not config.multi_agent.enabled or not user_config.get("multi_agent", {}).get("enabled", True):
            return False
        if task.get("source") == INBOX_RUN_TYPE:
            session = self._descriptor(task)["parent_session_id"]
            manager = self.conversation.message_manager
            if not (manager and manager.get_session(session, user_id=task["user_id"]) and not manager.has_active_turn(session, user_id=task["user_id"], exclude_turn_ids={row["run_id"] for row in task["runs"]}) and not self.conversation.agent_is_active(task["user_id"], session)):
                return False
        active = set(self.runtime.active_run_ids())
        tasks = [*self.tasks.execution_tasks(run_type=RUN_TYPE), *self.tasks.execution_tasks(run_type=INBOX_RUN_TYPE)]
        child_runs = {run["run_id"] for item in tasks for run in item["runs"]}
        user_runs = {run["run_id"] for item in tasks if item["user_id"] == task["user_id"] for run in item["runs"]}
        return (
            len(active & child_runs) + self.conversation.delegation._active < config.multi_agent.max_parallel
            and len(active & user_runs) < delegation_limits(user_config)["max_parallel"]
        )

    def active_count(self):
        active = set(self.runtime.active_run_ids())
        return sum(run["run_id"] in active for kind in (RUN_TYPE, INBOX_RUN_TYPE) for task in self.tasks.execution_tasks(run_type=kind) for run in task["runs"])

    def _config(self, user_id):
        service = self.conversation.config_service
        return service.get_merged_config(user_id) if service is not None else config.model_dump()

    async def start(self, request, *, parent, user_config):
        if self.runtime._shutting_down:
            raise RuntimeError("Task runtime is shutting down")
        scope = current_delegation()
        limits = delegation_limits(user_config)
        if scope is None or scope.closed or scope.budget.closed or not delegation_enabled(parent, user_config):
            raise PermissionError("multi-agent mode is not enabled for this turn")
        if scope.depth >= limits["max_depth"] or scope.budget.count >= limits["max_children"]:
            raise PermissionError("delegation depth or turn budget exhausted")
        if scope.depth and not scope.agent_task_id:
            raise PermissionError("a persistent child needs a persistent parent identity")
        pending = sum(1 for task in self.tasks.list_tasks(user_id=parent.user_id, limit=10000) if task.get("source") == "subagent" and task["status"] == "running")
        if pending >= config.multi_agent.max_pending:
            raise PermissionError("background child admission limit reached")
        catalog = await self.conversation.capability_service.get_tool_catalog(run_context=parent, user_config=user_config)
        allowed = {row["name"] for row in project_capability_snapshot(catalog, schema_budget_chars=0)["compact_index"] if row["callable_now"]}
        if request.tools is not None:
            if not set(request.tools) <= allowed:
                raise PermissionError("child tool selection exceeds the parent's available tools")
            allowed &= set(request.tools)
        # Catalog refresh may suspend; admission is rechecked before the durable commit.
        if scope.closed or scope.budget.closed or scope.budget.count >= limits["max_children"]:
            raise PermissionError("delegation admission closed")
        if sum(1 for task in self.tasks.list_tasks(user_id=parent.user_id, limit=10000) if task.get("source") == "subagent" and task["status"] == "running") >= config.multi_agent.max_pending:
            raise PermissionError("background child admission limit reached")
        metadata = (getattr(parent, "input_payload", {}) or {}).get("metadata") or {}
        parent_loop = getattr(parent, "action_loop_id", None)
        workspace = getattr(parent, "workspace_handle", {}) or {}
        descriptor = {
            "version": 1, "parent_session_id": parent.session_id,
            "parent_agent_task_id": scope.agent_task_id, "parent_task_id": getattr(parent, "task_id", None),
            "parent_action_loop_id": parent_loop,
            "ancestor_action_loop_ids": [*scope.ancestor_action_loop_ids, *([parent_loop] if parent_loop else [])],
            "depth": scope.depth + 1, "allowed_tools": sorted(allowed),
            "tool_policy": deepcopy(getattr(parent, "tool_policy", {}) or {}),
            "workspace_id": workspace.get("workspace_id") or parent.session_id,
            "limits": limits,
            "language": {key: metadata[key] for key in ("timezone", "ui_language") if key in metadata},
        }
        run_id = f"agent_turn_{uuid4().hex}"
        task = self.tasks.create_task(
            user_id=parent.user_id, title=request.label, objective=request.objective,
            session_id=parent.session_id, source="subagent", metadata={"delegation": descriptor, "continuable": True},
            initial_run={"run_id": run_id, "run_type": RUN_TYPE, "trace_id": getattr(parent, "trace_id", None), "metadata": {"message": request.objective, "message_source": "parent-agent", "sender_task_id": scope.agent_task_id, "sender_session_id": parent.session_id}},
        )
        scope.budget.count += 1
        # The durable inbox owns the message now, independent of the request's lifetime.
        self._schedule_accepted(task["task_id"], parent.user_id, run_id)
        return {"ok": True, "status": "accepted", "child_id": task["task_id"], "run_id": run_id, "message_id": run_id, "label": request.label, "background": True}

    async def control(self, request, *, parent, user_config):
        if request.action == "list":
            result = []
            for task in self.tasks.list_tasks(user_id=parent.user_id, limit=10000):
                if task.get("source") != "subagent":
                    continue
                try:
                    self._owned(task["task_id"], parent)
                except (PermissionError, ValueError, KeyError):
                    continue
                result.append(self.view(task))
            return {"agents": result}
        if not request.child_id:
            raise ValueError("child_id is required")
        task = self._owned(request.child_id, parent)
        if request.action == "get":
            return self.view(task)
        if request.action == "send":
            if not request.message or not delegation_enabled(parent, user_config):
                raise PermissionError("a message and enabled multi-agent mode are required")
            if task["status"] in {"paused", "cancelled"}:
                raise ValueError("resume or recreate the child before sending more work")
            pending = [run for run in task["runs"] if run["status"] in {"pending", "running"}]
            if len(pending) >= config.multi_agent.max_children:
                raise ValueError("child inbox is full")
            run_id = f"agent_turn_{uuid4().hex}"
            scope = current_delegation()
            self.tasks.start_run(task_id=task["task_id"], user_id=parent.user_id, run_id=run_id, run_type=RUN_TYPE, session_id=parent.session_id, status="pending", metadata={"message": request.message, "message_source": "parent-agent", "sender_task_id": scope.agent_task_id if scope else None, "sender_session_id": parent.session_id})
            self._schedule_accepted(task["task_id"], parent.user_id, run_id)
            return {"ok": True, "status": "accepted", "child_id": task["task_id"], "run_id": run_id, "message_id": run_id}
        if request.action == "cancel":
            return self.view(self.runtime.cancel_task(task_id=task["task_id"], user_id=parent.user_id))
        if request.action == "resume":
            if not delegation_enabled(parent, user_config):
                raise PermissionError("multi-agent mode is required to resume work")
            return self.view(self.runtime.resume_task(task_id=task["task_id"], user_id=parent.user_id))
        return self.view(self.runtime.pause_task(task_id=task["task_id"], user_id=parent.user_id))

    def _schedule_accepted(self, task_id, user_id, run_id):
        try:
            self.runtime.schedule_run(task_id=task_id, user_id=user_id, run_id=run_id)
        except Exception:
            logger.exception("Durably accepted child message {} remains queued for recovery", run_id)

    @staticmethod
    def view(task):
        status = "ready" if task["status"] == "waiting_user" and all(run["status"] == "completed" for run in task["runs"]) else task["status"]
        return {
            "child_id": task["task_id"], "label": task["title"], "status": status, "revision": task["revision"],
            "turns": [{"run_id": run["run_id"], "status": run["status"], "output": (run.get("metadata") or {}).get("output", ""), "error": (run.get("metadata") or {}).get("error")} for run in task["runs"][-20:]],
        }

    async def run(self, task, run, token):
        if task.get("source") == INBOX_RUN_TYPE:
            return await self._run_parent_followup(task, run, token)
        descriptor = self._descriptor(task)
        user_config = self._config(task["user_id"])
        limits = {key: min(value, delegation_limits(user_config)[key]) for key, value in descriptor["limits"].items()}
        user_config = child_configuration(user_config, limits)
        session_id = descriptor["parent_session_id"]
        context = RunContext(
            request_id=run["run_id"], trace_id=run.get("trace_id") or run["run_id"],
            task_id=task["task_id"], task_run_id=run["run_id"], execution_token=token,
            conversation_turn_id=run["run_id"], tool_policy=deepcopy(descriptor["tool_policy"]),
            session_state=SessionState(session_id=session_id, user_id=task["user_id"], trace_id=run["run_id"]),
            input_payload={"message": run["metadata"]["message"], "metadata": {**descriptor["language"], "multi_agent": True}},
        )
        workspace = self.conversation.capability_service.workspace_service
        if workspace is not None:
            context.workspace_handle = workspace.resolve_workspace_handle(user_id=task["user_id"], workspace_id=descriptor["workspace_id"]).model_dump()
        scope = DelegationScope(
            _Budget(), depth=int(descriptor["depth"]), allowed_tools=frozenset(descriptor["allowed_tools"]),
            parent_action_loop_id=descriptor.get("parent_action_loop_id"),
            ancestor_action_loop_ids=tuple(descriptor["ancestor_action_loop_ids"]),
            agent_task_id=task["task_id"], workspace_id=descriptor["workspace_id"],
        )
        checkpoint = run["metadata"].get("checkpoint")
        if checkpoint:
            scope.budget.count = int(checkpoint.get("delegation_spent") or 0)
            context.agent_message_ids = checkpoint.get("agent_message_ids", [])

        def save(value):
            self.tasks.checkpoint_run(task_id=task["task_id"], user_id=task["user_id"], run_id=run["run_id"], token=token, checkpoint={**value, "delegation_spent": scope.budget.count, "agent_message_ids": context.agent_message_ids})

        history = []
        for previous in task["runs"]:
            if previous["run_id"] == run["run_id"]:
                break
            if previous["status"] == "completed":
                if previous["metadata"].get("message"):
                    history.append({"role": "user", "content": previous["metadata"]["message"]})
                history.append({"role": "assistant", "content": previous["metadata"].get("output", "")})
        with bind_delegation(scope):
            try:
                async with asyncio.timeout(limits["timeout_s"]):
                    result = await self.conversation.run_delegated_turn(
                        objective=run["metadata"]["message"], label=task["title"], run_context=context,
                        user_config=user_config, max_steps=limits["child_steps"], history=history[-20:],
                        checkpoint_sink=save, checkpoint=checkpoint,
                    )
            except TimeoutError:
                return {"status": "failed", "detail": {"error": "child deadline exceeded"}}
        return {
            "status": "completed" if result.get("status") == "success" else "failed",
            "detail": {"output": str(result.get("content") or "")[:limits["result_chars"]], "result_summary": str(result.get("content") or "")[:600], "usage": result.get("usage"), "error": result.get("error"), "agent_message_ids": result.get("agent_message_ids", [])},
        }

    async def _run_parent_followup(self, task, run, token):
        from agentkit.security.approval import approval_scope

        descriptor = self._descriptor(task)
        user, session = task["user_id"], descriptor["parent_session_id"]
        manager = self.conversation.message_manager
        async with self.conversation.agent_execution(user, session):
            if manager.has_active_turn(session, user_id=user, exclude_turn_ids={run["run_id"]}):
                return {"status": "pending", "detail": {}}
            pending = self.messages.pending(user_id=user, session_id=session)
            if not pending:
                return {"status": "completed", "detail": {}}
            if not manager.begin_turn(session, run["run_id"], "runtime", "", user):
                raise RuntimeError("could not admit parent continuation")
            context = RunContext(
                request_id=run["run_id"], trace_id=run["run_id"], task_id=task["task_id"],
                task_run_id=run["run_id"], execution_token=token, conversation_turn_id=run["run_id"],
                session_state=SessionState(session_id=session, user_id=user, trace_id=run["run_id"]),
                input_payload={"metadata": {**descriptor["language"], "origin": "agent_inbox", "multi_agent": True}},
                tool_policy=deepcopy(descriptor["tool_policy"]),
            )
            checkpoint = run["metadata"].get("checkpoint")
            if checkpoint:
                context.agent_message_ids = checkpoint.get("agent_message_ids", [])
            # A notification is not a new grant of external-write authority.
            scope = DelegationScope(_Budget(), background_notification=True, workspace_id=descriptor["workspace_id"])
            workspace = self.conversation.capability_service.workspace_service
            if workspace is not None:
                context.workspace_handle = workspace.resolve_workspace_handle(user_id=user, workspace_id=descriptor["workspace_id"]).model_dump()

            def save(value):
                self.tasks.checkpoint_run(task_id=task["task_id"], user_id=user, run_id=run["run_id"], token=token, checkpoint={**value, "agent_message_ids": context.agent_message_ids})

            try:
                with bind_delegation(scope), approval_scope("subagent.notification", {}, confirmed=False):
                    async with asyncio.timeout(delegation_limits(self._config(user))["timeout_s"]):
                        result = await self.conversation.run_agent_followup(
                            run_context=context, checkpoint=checkpoint, checkpoint_sink=save,
                        )
                if result.get("status") != "success":
                    manager.abort_turn(session, run["run_id"], user_id=user, error=result.get("error"))
                    return {"status": "failed", "detail": {"error": result.get("error") or "parent continuation did not complete"}}
                ids = result.get("agent_message_ids", [])
                self.tasks.assert_action_execution(task_id=task["task_id"], user_id=user, expected_objective=task["objective"], task_run_id=run["run_id"], execution_token=token)
                if not manager.commit_turn(session, run["run_id"], result.get("content", ""), user_id=user, reasoning_steps=result.get("reasoning_steps"), agent_message_ids=ids):
                    raise RuntimeError("could not commit parent continuation")
            except asyncio.CancelledError:
                # Keep the pending turn and checkpoint for the same durable run.
                raise
            except Exception as exc:
                logger.exception("Parent notification paused before commit")
                return {"status": "paused", "detail": {"error": str(exc)}}
            if self.conversation.event_emitter:
                from .protocol import EventType

                await self.conversation.event_emitter.emit(EventType.CONVERSATION_COMPLETE, {"session_id": session, "user_id": user, "response": result.get("content", ""), "conversation_turn_id": run["run_id"], "source": "agent_inbox", "status": "success"})
            return {"status": "completed", "detail": {"output": result.get("content", ""), "agent_message_ids": ids, "usage": result.get("usage")}}
