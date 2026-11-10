"""Admit user work from chat and run it under the existing TaskRuntime."""
from copy import deepcopy
from uuid import uuid4

from .action.models import resolve_action_budget
from .capability_service import ToolInvocationContext
from .delegation import current_delegation
from .models.run_context import RunContext
from .models.session_state import SessionState


RUN_TYPE = "conversation_task"


class ConversationTasks:
    def __init__(self, conversation, runtime):
        self.conversation = conversation
        self.runtime = runtime
        self.tasks = runtime.task_service
        runtime.register_driver(RUN_TYPE, self)

    def _caller(self, ctx):
        context = ctx.metadata.get("run_context") if ctx else None
        delegation = current_delegation()
        if (not isinstance(context, RunContext) or ctx.source != "chat" or not context.conversation_turn_id
                or ctx.user_id != context.user_id or ctx.session_id != context.session_id
                or context.task_id or (delegation and delegation.depth)
                or not self.conversation.message_manager.get_session(context.session_id, user_id=context.user_id)):
            raise PermissionError("task handoff requires an authenticated user conversation turn")
        return context

    @staticmethod
    def _view(task, *, include_output=True):
        run = task["runs"][0]
        result = {"task_id": task["task_id"], "run_id": run["run_id"], "title": task["title"],
                  "status": task["status"], "run_status": run["status"], "session_ids": task["session_ids"]}
        if include_output:
            result.update(output=run["metadata"].get("output", ""),
                          input_request=run["metadata"].get("input_request"),
                          pending_confirmation=run["status"] == "waiting_human")
        return result

    def start(self, ctx, title):
        origin = self._caller(ctx)
        payload = origin.input_payload
        objective = str(payload.get("message") or "").strip()
        title = str(title or "").strip()
        if not title or len(title) > 240 or not objective:
            raise ValueError("task requires a title and a user objective")
        existing = next((task for task in self.tasks.execution_tasks(run_type=RUN_TYPE)
                         if task["user_id"] == origin.user_id and task["runs"][0]["session_id"] == origin.session_id
                         and task["metadata"].get("origin_turn_id") == origin.conversation_turn_id), None)
        if existing:
            return self._view(existing)
        run_id = f"run_{uuid4().hex}"
        task = self.tasks.create_task(
            user_id=origin.user_id, title=title, objective=objective, session_id=origin.session_id, source=RUN_TYPE,
            metadata={"origin_turn_id": origin.conversation_turn_id,
                      "workspace_id": origin.workspace_handle.get("workspace_id") or origin.session_id,
                      "tool_policy": deepcopy(origin.tool_policy), "requested_mode": origin.requested_mode,
                      "requested_skill": origin.requested_skill, "active_skill": deepcopy(origin.active_skill),
                      "attachments": [{"file_id": item["file_id"]} for item in payload.get("attachments") or []
                                      if isinstance(item, dict) and item.get("file_id")],
                      "language": {key: payload.get("metadata", {}).get(key) for key in ("ui_language", "timezone")
                                   if payload.get("metadata", {}).get(key)}},
            initial_run={"run_id": run_id, "run_type": RUN_TYPE, "trace_id": run_id},
        )
        self.runtime.schedule_run(task_id=task["task_id"], user_id=origin.user_id, run_id=run_id)
        return self._view(task)

    def list(self, ctx):
        origin = self._caller(ctx)
        return {"tasks": [self._view(task, include_output=False) for task in self.tasks.list_tasks(user_id=origin.user_id, limit=200)
                          if task["source"] == RUN_TYPE][:20]}

    def _owned(self, task_id, user):
        task = self.tasks.get_task(task_id, user_id=user)
        if not task or task["source"] != RUN_TYPE:
            raise KeyError("conversation task not found")
        return task

    def resume(self, ctx, task_id):
        origin = self._caller(ctx)
        task = self._owned(task_id, origin.user_id)
        run = task["runs"][0]
        if run["status"] == "paused" and not (run["metadata"].get("checkpoint") or {}).get("pending_input"):
            self.runtime.resume_task(task_id=task_id, user_id=origin.user_id, expected_revision=task["revision"])
        self.tasks.attach_session(task_id=task_id, user_id=origin.user_id, session_id=origin.session_id)
        return self._view(self._owned(task_id, origin.user_id))

    def available(self, task):
        return task["source"] == RUN_TYPE and self.conversation.capability_service is not None

    def _context(self, task, run, token):
        user, session, run_id = task["user_id"], run["session_id"], run["run_id"]
        origin = task["metadata"]
        context = RunContext(request_id=run_id, trace_id=run_id, task_id=task["task_id"], task_run_id=run_id,
                             execution_token=token, conversation_turn_id=run_id,
                             session_state=SessionState(session_id=session, user_id=user, trace_id=run_id),
                             tool_policy=deepcopy(origin["tool_policy"]), requested_mode=origin["requested_mode"],
                             requested_skill=origin["requested_skill"], active_skill=deepcopy(origin["active_skill"]),
                             input_payload={"metadata": {**origin["language"], "origin": RUN_TYPE}})
        workspace = self.conversation.capability_service.workspace_service
        if workspace is not None:
            context.workspace_handle = workspace.resolve_workspace_handle(user_id=user, workspace_id=origin["workspace_id"]).model_dump()
        return context

    def _hooks(self, context, user_config):
        async def execute(name, arguments):
            return await self.conversation.capability_service.call_tool(
                name, arguments, run_context=context, user_config=user_config,
                ctx=ToolInvocationContext(session_id=context.session_id, user_id=context.user_id, source=RUN_TYPE,
                                          metadata={"run_context": context, "user_config": user_config}),
            )

        def save(value):
            self.tasks.checkpoint_run(task_id=context.task_id, user_id=context.user_id, run_id=context.task_run_id,
                                      token=context.execution_token, checkpoint=value)

        return {"session_id": context.session_id, "user_id": context.user_id, "run_context": context,
                "user_config": user_config, "tool_executor": execute, "checkpoint_sink": save}

    async def run(self, task, run, token):
        context = self._context(task, run, token)
        checkpoint = run["metadata"].get("checkpoint") or None
        if checkpoint and run["metadata"].get("resume_action_result"):
            checkpoint = {**checkpoint, "resume_result": True}
        if checkpoint:
            messages = []
            config = self.conversation.config_service.get_merged_config(context.user_id)
        else:
            prepared = await self.conversation.prepare_chat_turn(
                session_id=context.session_id, user_id=context.user_id, user_message=task["objective"],
                channel="web", run_context=context, attachments=task["metadata"]["attachments"],
            )
            messages, config = prepared["messages"], prepared["user_config"]
        result = await self.conversation.run_chat_loop(
            messages, checkpoint=checkpoint, max_recursion=resolve_action_budget(config), **self._hooks(context, config),
        )
        return self.finish(task, run, result)

    def finish(self, task, run, result):
        status = result.get("status")
        detail = {"output": str(result.get("content") or "")[:16000], "error": result.get("error"),
                  "execution_outcome": result.get("execution_outcome"), "usage": result.get("usage"),
                  "input_request": result.get("input_request"),
                  "pending_action": result if status == "needs_confirmation" else None}
        run_status = {"needs_input": "waiting_user", "needs_confirmation": "waiting_human"}.get(status)
        return {"status": run_status or ("paused" if result.get("execution_outcome") else "completed" if status == "success" else "failed"),
                "detail": detail}

    async def confirm(self, user, task_id, run_id, call_id, action):
        self._owned(task_id, user)

        async def continue_action(task, run, token, pending):
            context = self._context(task, run, token)
            config = self.conversation.config_service.get_merged_config(user)
            options = self._hooks(context, config)
            if action == "approve":
                return await self.conversation.resume_action(pending=pending, approved_call_id=call_id, **options)
            return await self.conversation.reject_pending_action(pending=pending, **options)

        await self.runtime.continue_confirmation(task_id=task_id, user_id=user, run_id=run_id, call_id=call_id,
                                                 operation=continue_action)
        return self._owned(task_id, user)
