from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from agentkit.mcp.tool_result import ToolErrorInfo, ToolExecutionResult, error_from_exception, failed_tool_result, normalize_tool_result
from agentkit.security.approval import approval_scope
from gateway.events import EventEmitter
from gateway.protocol import EventType
from config import GoalGapConfig, ActionConfig, config as global_config
from gateway.goal_gaps import GoalGapState, GapRecoveryState, answer_disposition, apply_gap_delta, admit_gap_action, gap_event_delta, gap_outcome, gap_projection, observe_gap_step, validate_partial_evidence, validate_user_dependency

from .model_action import AnswerDeltaProjector, InvalidModelAction, ModelAction, ToolCallProposal, parse_model_action
from .models import MAX_ACTION_BUDGET, ActionContext, ActionResult, ActionRun, resolve_action_budget
from .observation import RuntimeObservation
from .state_machine import ActionPhase
from .state_machine import RuntimeActionStateMachine
from .checkpoint import capture as capture_checkpoint, restore as restore_checkpoint, continue_run as continue_checkpoint
from .completion import parse_final_answer, runtime_progress_notice
from .context_window import compact_action_history
from .recovery import recover as recover_model_output, reset_failures
from gateway.tools.registry import ToolNotFoundError
from gateway.tools.spec import SideEffectLevel


CapabilityInspector = Callable[[List[str]], Awaitable[Dict[str, Any]]]
CapabilityResolver = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
OutputSink = Callable[[Any], Awaitable[None]]
ReasoningSink = Callable[[Dict[str, Any]], Awaitable[None]]


class ModelResponseError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_REQUEST_FAILED", usage: Optional[Dict[str, Any]] = None, signature: str = ""):
        super().__init__(message)
        self.code = code
        self.usage = usage
        self.signature = signature


class ActionService:
    """Runtime-owned model/action/observation control loop."""

    def __init__(self, *, event_emitter: Optional[EventEmitter] = None, conversation_core: Any, task_service: Optional[Any] = None, capability_service: Optional[Any] = None) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core
        self.task_service = task_service
        self.capability_service = capability_service
        self._active_runs: Dict[str, ActionRun] = {}
        self.control_lock = asyncio.Lock()

    def active_turn(self, *, user_id: str, session_id: str, turn_id: str) -> Optional[ActionRun]:
        return next((run for run in self._active_runs.values()
                     if run.accepting_steering and run.context.user_id == user_id and run.context.session_id == session_id
                     and getattr(run.context.run_context, "conversation_turn_id", None) == turn_id
                     and run.machine.phase not in {ActionPhase.COMPLETED, ActionPhase.FAILED, ActionPhase.CANCELLED, ActionPhase.WAITING_CONFIRMATION}), None)

    async def steer_turn(self, *, user_id, session_id, turn_id, persist, lookup=None):
        async with self.control_lock:
            previous = lookup() if lookup is not None else None
            if previous is not None:
                return previous
            run = self.active_turn(user_id=user_id, session_id=session_id, turn_id=turn_id)
            if run is None or run.context.read_steering is None:
                raise ValueError("turn_not_steerable")
            row = persist()
            await self._emit_event(EventType.ACTION_STEERING_RECEIVED, run, self._steering_presentation(row, "pending"))
            return {**row, "action_loop_id": run.run_id}

    @staticmethod
    async def _replace_answer(run, content, output_sink):
        if run.streamed_answer != content and output_sink is not None:
            await output_sink({"operation": "replace", "content": content} if run.streamed_answer else content)
        run.streamed_answer = content

    async def _apply_steering(self, run, messages, usage, output_sink) -> bool:
        source = run.context.read_steering
        if source is None:
            return False
        async with self.control_lock:
            pending = source()
            # A checkpoint may survive a crash just before the receipt was saved.
            recovered = [row["message_id"] for row in pending
                         if row["message_id"] in run.applied_steering_ids and row.get("status") != "applied"]
            if recovered and run.context.acknowledge_steering:
                run.context.acknowledge_steering(recovered)
            rows = [row for row in pending if row["message_id"] not in run.applied_steering_ids]
            if not rows:
                return False
            await self._replace_answer(run, "", output_sink)
            run.status = "running"
            run.approved_call_ids.clear()
            messages.extend({"role": "user", "content": row["content"]} for row in rows)
            ids = [row["message_id"] for row in rows]
            run.applied_steering_ids.extend(ids)
            await self._checkpoint(run, messages, usage)
            if run.context.acknowledge_steering:
                run.context.acknowledge_steering(ids)
            for row in rows:
                await self._emit_event(EventType.ACTION_STEERING_APPLIED, run, {**self._steering_presentation(row, "completed"), "step": run.step})
            if output_sink is not None:
                await output_sink({"type": "steering", "status": "applied", "message_ids": ids})
            return True

    @staticmethod
    def _steering_presentation(row, status):
        return {"kind": "task", "activity_id": f"steering:{row['message_id']}", "message_id": row["message_id"],
                "status": status, "content": row["content"], "summary": row["content"],
                "presentation": {"title": "Execution guidance", "title_i18n": {"zh": "调整执行方向", "en": "Execution guidance"}}}

    async def run_action(
        self,
        *,
        goal: str,
        messages: List[Dict[str, Any]],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        run_context: Optional[Any] = None,
        tool_executor: Optional[Any] = None,
        confirmation_resolver: Optional[Any] = None,
        capability_inspector: Optional[CapabilityInspector] = None,
        capability_resolver: Optional[CapabilityResolver] = None,
        budget: Optional[int] = None,
        allow_progress_grace: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        approved_call_ids: Optional[set[str]] = None,
        output_sink: Optional[OutputSink] = None,
        reasoning_sink: Optional[ReasoningSink] = None,
        prepare_messages: Optional[Callable] = None,
        checkpoint_sink: Optional[Callable] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        read_steering: Optional[Callable] = None,
        acknowledge_steering: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        grace_steps = 0
        if allow_progress_grace and all(getattr(run_context, key, None) is None for key in ("cost_budget", "token_budget")):
            policy = ActionConfig(**{**global_config.action.model_dump(), **((user_config or {}).get("action") or {})})
            grace_steps = policy.progress_grace_steps
        action_run = ActionRun(
            goal=str(goal or ""),
            messages=list(messages or []),
            context=ActionContext(
                session_id=session_id,
                user_id=user_id,
                user_config=user_config,
                run_context=run_context,
                metadata=dict(metadata or {}),
                prepare_messages=prepare_messages,
                checkpoint_sink=checkpoint_sink,
                read_steering=read_steering,
                acknowledge_steering=acknowledge_steering,
            ),
            budget=budget,
            progress_grace_steps=grace_steps,
            approved_call_ids=set(approved_call_ids or ()),
        )
        continuing = bool(checkpoint and checkpoint.get("resume_result") and
                          (checkpoint.get("result") or {}).get("execution_outcome"))
        input_response = (checkpoint or {}).get("input_response")
        if checkpoint:
            restore_checkpoint(checkpoint, action_run.context)
            if checkpoint.get("result") and not continuing and input_response is None:
                return dict(checkpoint["result"])
            if continuing:
                action_run = continue_checkpoint(checkpoint, action_run.context, goal=action_run.goal, budget=budget)
                action_run.progress_grace_steps = grace_steps
                action_run.messages.append({"role": "user", "_runtime_rebuild": action_run.goal, "content": (
                    "The user explicitly resumed this task. A new bounded execution slice is active. "
                    "Continue from the committed observations and remaining goal gaps; previous budget-stop "
                    "observations describe the earlier slice. Do not repeat already committed side effects "
                    "without checking whether another operation is actually required."
                )})
            else:
                action_run = restore_checkpoint(checkpoint, action_run.context)
            action_run.progress_grace_steps = min(action_run.progress_grace_steps, grace_steps)
        self._load_goal_gaps(action_run)
        restored_messages = None
        if checkpoint and not continuing:
            restored_messages = list(action_run.messages)
            if input_response is not None:
                pending_input = action_run.pending_input or {}
                if action_run.machine.phase != ActionPhase.WAITING_INPUT or not isinstance(input_response, dict) or input_response.get("request_id") != pending_input.get("request_id"):
                    raise ValueError("input response does not match a waiting Runtime request")
                reply = input_response.get("content")
                if not isinstance(reply, str) or not reply.strip() or len(reply) > 16000:
                    raise ValueError("input response requires bounded non-empty text")
                action_run.budget = action_run.step + int(budget or resolve_action_budget(user_config))
                await self._observe_outcome(
                    action_run, restored_messages, model_step_id=pending_input["model_step_id"],
                    assistant_content=pending_input["action_content"],
                    result=ToolExecutionResult(tool_name="runtime.user_input", ok=True, value={
                        "request_id": pending_input["request_id"], "user_report": reply,
                        "external_result_verified": False, "tool_authorization_granted": False,
                        "execution_slice_steps": action_run.budget - action_run.step,
                    }),
                )
                action_run.pending_input = None
                await self._checkpoint(action_run, restored_messages, checkpoint.get("usage") or {})
            pending = checkpoint.get("pending_calls") or []
            if pending:
                calls = [ToolCallProposal(tool_name=row["tool_name"], arguments=dict(row["arguments"]), call_id=row["call_id"],
                                          operation=row.get("operation", "tool_call")) for row in pending]
                action = ModelAction(kind="tool_calls", calls=calls)
                results = [ToolExecutionResult(
                    tool_name=call.tool_name, ok=False,
                    error=ToolErrorInfo("TOOL_OUTCOME_UNKNOWN", "Runtime restarted during this call. It was not replayed; inspect actual state before retrying.", "recovery", False),
                ) for call in calls]
                observations = await self._record_tool_results(action_run, action, results, model_step_id="recovery", started_ids={call.call_id for call in calls})
                restored_messages.extend(self._observation_messages("", observations))
                await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="interrupted_calls_observed")
        result = await self._run(
            action_run,
            tool_executor=tool_executor,
            confirmation_resolver=confirmation_resolver,
            capability_inspector=capability_inspector,
            capability_resolver=capability_resolver,
            output_sink=output_sink,
            reasoning_sink=reasoning_sink,
            resume_messages=restored_messages,
            resume_usage=(checkpoint or {}).get("usage"),
        )
        payload = result.to_chat_loop_result()
        await self._checkpoint(action_run, payload.get("messages") or restored_messages or messages, payload.get("usage") or {}, result=payload)
        return payload

    @staticmethod
    async def _checkpoint(action_run, messages, usage, **options):
        sink = action_run.context.checkpoint_sink
        if sink is not None:
            pending = sink(capture_checkpoint(action_run, messages, usage, **options))
            if inspect.isawaitable(pending):
                await pending

    async def resume_action(
        self,
        *,
        pending: Dict[str, Any],
        approved_call_id: str,
        user_config: Optional[Dict[str, Any]],
        session_id: Optional[str],
        user_id: Optional[str],
        run_context: Optional[Any],
        tool_executor: Any,
        confirmation_resolver: Optional[Any],
        capability_inspector: Optional[CapabilityInspector] = None,
        capability_resolver: Optional[CapabilityResolver] = None,
        output_sink: Optional[OutputSink] = None,
        reasoning_sink: Optional[ReasoningSink] = None,
        prepare_messages: Optional[Callable] = None,
        checkpoint_sink: Optional[Callable] = None,
        read_steering: Optional[Callable] = None,
        acknowledge_steering: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        transitions = [dict(item) for item in (pending.get("action_state_transitions") or [])]
        if str(approved_call_id) != str(pending.get("tool_call_id") or ""):
            raise ValueError("approval does not match the pending tool call")
        machine = RuntimeActionStateMachine.restore(transitions)
        if machine.phase != ActionPhase.WAITING_CONFIRMATION:
            raise RuntimeError("pending action is not waiting for confirmation")
        self._restore_confirmation_scope(pending, session_id=session_id, user_id=user_id, run_context=run_context)
        action_run = ActionRun(
            goal=str(pending.get("goal") or ""),
            messages=[],
            context=ActionContext(
                session_id=session_id,
                user_id=user_id,
                user_config=user_config,
                run_context=run_context,
                metadata={"source": "action_confirmation_resume"},
                prepare_messages=prepare_messages,
                checkpoint_sink=checkpoint_sink,
                read_steering=read_steering,
                acknowledge_steering=acknowledge_steering,
            ),
            budget=int(pending.get("budget") or 5),
            progress_grace_steps=int(pending.get("progress_grace_steps") or 0),
            run_id=str(pending.get("action_run_id") or pending.get("action_loop_id") or f"act_{uuid.uuid4().hex}"),
            status="running",
            trace=[dict(item) for item in (pending.get("action_trace") or [])],
            machine=machine,
            step=int(pending.get("step") or 1),
            observations=[dict(item) for item in (pending.get("observations") or [])],
            execution_path=[dict(item) for item in (pending.get("execution_path") or [])],
            reasoning_steps=[dict(item) for item in (pending.get("reasoning_steps") or [])],
            approved_call_ids=set(pending.get("approved_call_ids") or ()) | {str(approved_call_id)},
            applied_steering_ids=list(pending.get("applied_steering_ids") or []),
            model_recovery=dict(pending.get("model_recovery") or {}),
            model_protocol=pending.get("model_protocol", "prompt_json"),
            model_wire=dict(pending.get("model_wire") or {}),
            gap_state=GoalGapState.model_validate(pending.get("goal_gaps") or {}),
            gap_task_objective=str((pending.get("task_checkpoint") or {}).get("objective") or ""),
            gap_execution_token=dict((pending.get("task_checkpoint") or {}).get("execution_token") or {}),
        )
        self._load_goal_gaps(action_run, capture_token=not bool(pending.get("task_checkpoint")))
        calls = [
            ToolCallProposal(
                tool_name=str(item.get("name") or item.get("tool_name") or ""),
                arguments=dict(item.get("args") or {}),
                call_id=str(item.get("id") or item.get("call_id") or f"call_{uuid.uuid4().hex}"),
                operation=item.get("operation", "tool_call"),
            )
            for item in (pending.get("pending_tool_calls") or [])
            if isinstance(item, dict)
        ]
        if not calls:
            raise RuntimeError("pending action has no tool calls")
        action = ModelAction(kind="tool_calls", calls=calls, raw={"procedure_refs": pending.get("procedure_refs", [])})
        messages = [dict(item) for item in (pending.get("current_messages") or [])]
        model_step_id = str(pending.get("model_step_id") or f"step_{uuid.uuid4().hex}")
        assistant_content = str(pending.get("content") or "")
        result = await self._run(
            action_run,
            tool_executor=tool_executor,
            confirmation_resolver=confirmation_resolver,
            capability_inspector=capability_inspector,
            capability_resolver=capability_resolver,
            resume_messages=messages,
            resume_usage=pending.get("usage"),
            resumed_action=action,
            resumed_step_id=model_step_id,
            resumed_content=assistant_content,
            output_sink=output_sink,
            reasoning_sink=reasoning_sink,
        )
        payload = result.to_chat_loop_result()
        await self._checkpoint(action_run, payload.get("messages") or messages, payload.get("usage") or {}, result=payload)
        return payload

    async def reject_pending_action(
        self,
        *,
        pending: Dict[str, Any],
        user_config: Optional[Dict[str, Any]],
        session_id: Optional[str],
        user_id: Optional[str],
        run_context: Optional[Any],
        tool_executor: Any,
        confirmation_resolver: Optional[Any],
        capability_inspector: Optional[CapabilityInspector] = None,
        capability_resolver: Optional[CapabilityResolver] = None,
        output_sink: Optional[OutputSink] = None,
        reasoning_sink: Optional[ReasoningSink] = None,
        prepare_messages: Optional[Callable] = None,
        checkpoint_sink: Optional[Callable] = None,
        read_steering: Optional[Callable] = None,
        acknowledge_steering: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """Commit a human denial as an observation and let the model replan or answer."""
        transitions = [dict(item) for item in (pending.get("action_state_transitions") or [])]
        machine = RuntimeActionStateMachine.restore(transitions)
        if machine.phase != ActionPhase.WAITING_CONFIRMATION:
            raise RuntimeError("pending action is not waiting for confirmation")
        self._restore_confirmation_scope(pending, session_id=session_id, user_id=user_id, run_context=run_context)
        action_run = ActionRun(
            goal=str(pending.get("goal") or ""),
            messages=[],
            context=ActionContext(
                session_id=session_id,
                user_id=user_id,
                user_config=user_config,
                run_context=run_context,
                metadata={"source": "action_confirmation_rejected"},
                prepare_messages=prepare_messages,
                checkpoint_sink=checkpoint_sink,
                read_steering=read_steering,
                acknowledge_steering=acknowledge_steering,
            ),
            budget=int(pending.get("budget") or 5),
            progress_grace_steps=int(pending.get("progress_grace_steps") or 0),
            run_id=str(pending.get("action_run_id") or pending.get("action_loop_id") or f"act_{uuid.uuid4().hex}"),
            status="running",
            trace=[dict(item) for item in (pending.get("action_trace") or [])],
            machine=machine,
            step=int(pending.get("step") or 1),
            observations=[dict(item) for item in (pending.get("observations") or [])],
            execution_path=[dict(item) for item in (pending.get("execution_path") or [])],
            reasoning_steps=[dict(item) for item in (pending.get("reasoning_steps") or [])],
            approved_call_ids=set(pending.get("approved_call_ids") or ()),
            applied_steering_ids=list(pending.get("applied_steering_ids") or []),
            model_recovery=dict(pending.get("model_recovery") or {}),
            model_protocol=pending.get("model_protocol", "prompt_json"),
            model_wire=dict(pending.get("model_wire") or {}),
            gap_state=GoalGapState.model_validate(pending.get("goal_gaps") or {}),
            gap_task_objective=str((pending.get("task_checkpoint") or {}).get("objective") or ""),
            gap_execution_token=dict((pending.get("task_checkpoint") or {}).get("execution_token") or {}),
        )
        self._load_goal_gaps(action_run, capture_token=not bool(pending.get("task_checkpoint")))
        model_step_id = str(pending.get("model_step_id") or f"step_{uuid.uuid4().hex}")
        calls = [
            ToolCallProposal(
                tool_name=str(item.get("name") or item.get("tool_name") or ""),
                arguments=dict(item.get("args") or {}),
                call_id=str(item.get("id") or item.get("call_id") or f"call_{uuid.uuid4().hex}"),
                operation=item.get("operation", "tool_call"),
            )
            for item in (pending.get("pending_tool_calls") or [])
            if isinstance(item, dict)
        ]
        if not calls:
            raise RuntimeError("pending action has no tool calls")
        observations = [
            RuntimeObservation.from_result(
                action_loop_id=action_run.run_id,
                model_step_id=model_step_id,
                tool_call_id=call.call_id,
                tool_name=call.tool_name,
                result=ToolExecutionResult(
                    tool_name=call.tool_name,
                    ok=False,
                    content=[{"type": "text", "text": "The user declined this action." if call.call_id == pending.get("tool_call_id") else "This batch action was not executed after another action was declined."}],
                    error=ToolErrorInfo(
                        code="USER_DECLINED" if call.call_id == pending.get("tool_call_id") else "BATCH_NOT_EXECUTED",
                        message="The user declined this action." if call.call_id == pending.get("tool_call_id") else "Another action was declined; this action was not executed.",
                        category="approval",
                        retryable=False,
                    ),
                ),
                capability_snapshot_id=self._capability_snapshot_id(action_run),
                scope=self._observation_scope(action_run),
            )
            for call in calls
        ]
        messages = [dict(item) for item in (pending.get("current_messages") or [])]
        for call, observation in zip(calls, observations):
            action_run.execution_path.append({
                "kind": "tool_call", "tool_call_id": call.call_id,
                "tool_name": call.tool_name, "args": dict(call.arguments),
                "ok": False, "executed": False,
                "requires_confirmation": call.call_id == pending.get("tool_call_id"),
                "observation_id": observation.observation_id,
                "procedure_refs": list(pending.get("procedure_refs", [])),
            })
        await self._commit_observations(action_run, observations)
        messages.extend(self._observation_messages(str(pending.get("content") or ""), observations, model_step_id=model_step_id if model_step_id in action_run.model_wire else None))
        await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="confirmation_rejection_observed")
        result = await self._run(
            action_run,
            tool_executor=tool_executor,
            confirmation_resolver=confirmation_resolver,
            capability_inspector=capability_inspector,
            capability_resolver=capability_resolver,
            resume_messages=messages,
            resume_usage=pending.get("usage"),
            output_sink=output_sink,
            reasoning_sink=reasoning_sink,
        )
        payload = result.to_chat_loop_result()
        await self._checkpoint(action_run, payload.get("messages") or messages, payload.get("usage") or {}, result=payload)
        return payload

    async def _run(
        self,
        action_run: ActionRun,
        *,
        tool_executor: Optional[Any],
        confirmation_resolver: Optional[Any],
        capability_inspector: Optional[CapabilityInspector],
        capability_resolver: Optional[CapabilityResolver],
        resume_messages: Optional[List[Dict[str, Any]]] = None,
        resume_usage: Optional[Dict[str, int]] = None,
        resumed_action: Optional[ModelAction] = None,
        resumed_step_id: Optional[str] = None,
        resumed_content: str = "",
        output_sink: Optional[OutputSink] = None,
        reasoning_sink: Optional[ReasoningSink] = None,
    ) -> ActionResult:
        started = time.perf_counter()
        action_run.budget = max(1, int(action_run.budget or 5))
        messages = list(resume_messages) if resume_messages is not None else list(action_run.messages)
        usage = dict(resume_usage or {"prompt_tokens": 0, "completion_tokens": 0})
        action_run.status = "running"
        stop_reason = "budget_exhausted"
        unavailable_model = None
        if resume_messages is None:
            action_run.add_trace("action.started", {"goal": action_run.goal, "budget": action_run.budget})
            await self._emit_lifecycle("action.started", action_run, {"goal": action_run.goal, "budget": action_run.budget})
            await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="loop_started")

        self._active_runs[action_run.run_id] = action_run
        try:
            while resumed_action is not None or action_run.step < action_run.budget:
                self._assert_task_execution(action_run)
                if await self._apply_steering(action_run, messages, usage, output_sink) and resumed_action is not None:
                    resumed_action = None
                    await self._transition(action_run, ActionPhase.OBSERVING, cause="outdated_approval_withdrawn")
                    await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="user_steering_applied")
                await self._checkpoint(action_run, messages, usage)
                control = action_run.gap_state.recovery
                limit = self._gap_policy(action_run).max_recovery_attempts
                if self._gap_policy(action_run).enabled and max(control.rejections, control.failed_trials) >= limit:
                    stop_reason = "recovery_exhausted"
                    break
                if action_run.machine.phase == ActionPhase.AWAITING_MODEL and control.mode == "reassess":
                    await self._transition(action_run, ActionPhase.REASSESSING, cause="goal_progress_reassessment",
                                           facts={"reason": control.reason, "evidence_refs": control.evidence_refs})
                if resumed_action is not None:
                    action = resumed_action
                    resumed_action = None
                    model_step_id = str(resumed_step_id)
                    content = resumed_content
                else:
                    action_run.step += 1
                    model_step_id = f"step_{uuid.uuid4().hex}"
                    try:
                        response = await self._call_model(
                            action_run,
                            messages,
                            model_step_id,
                            output_sink=output_sink,
                            reasoning_sink=reasoning_sink,
                        )
                    except ModelResponseError as exc:
                        await self._replace_answer(action_run, "", output_sink)
                        if exc.code not in {"MODEL_EMPTY_RESPONSE", "MODEL_OUTPUT_LIMIT"}:
                            if not action_run.observations and exc.code not in {"MODEL_ADMISSION_CLOSED", "MODEL_TRANSPORT_TRANSIENT"}:
                                raise
                            stop_reason = "recovery_exhausted"
                            unavailable_model = exc
                            break
                        self._merge_usage(usage, exc.usage)
                        retry, advice = self._recover_output(action_run, exc.code, exc.signature)
                        await self._observe_outcome(
                            action_run, messages, model_step_id=model_step_id,
                            result=ToolExecutionResult(
                                tool_name="runtime.model_response", ok=False,
                                error=ToolErrorInfo(
                                    code=exc.code, message=str(exc), category="model_output",
                                    retryable=retry, advice=advice,
                                ),
                            ),
                        )
                        if not retry:
                            stop_reason = "recovery_exhausted"
                            break
                        continue
                    self._merge_usage(usage, response.get("usage"))
                    content = str(response.get("content") or "")
                    await self._transition(
                        action_run,
                        ActionPhase.EVALUATING,
                        cause="model_response_received",
                        facts={"model_step_id": model_step_id},
                    )

                    try:
                        action = parse_model_action(content)
                        exposed = {ref for item in action_run.execution_path for ref in item.get("exposed_procedures", [])}
                        if not set(action.raw.get("procedure_refs", [])).issubset(exposed):
                            raise InvalidModelAction("procedure_refs must reference experience exposed in this action loop")
                        self._validate_answer_evidence(action_run, action)
                        # Audit retains provider bytes; accepted history uses the canonical object.
                        content = json.dumps(action.raw, ensure_ascii=False)
                    except InvalidModelAction as exc:
                        await self._replace_answer(action_run, "", output_sink)
                        retry, advice = self._recover_output(action_run, exc.reason, _stable_hash(content))
                        await self._observe_outcome(
                            action_run, messages, model_step_id=model_step_id,
                            result=ToolExecutionResult(
                                tool_name="runtime.model_action", ok=False,
                                error=ToolErrorInfo(
                                    code="INVALID_MODEL_ACTION", message=str(exc), category="validation",
                                    retryable=retry, advice=advice, details={"reason": exc.reason},
                                ),
                            ),
                        )
                        if not retry:
                            stop_reason = "recovery_exhausted"
                            break
                        continue

                reset_failures(action_run.model_recovery)
                self._assert_task_execution(action_run)
                if await self._apply_steering(action_run, messages, usage, output_sink):
                    await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="user_steering_applied")
                    continue
                delta_accepted = "gap_update" not in action.raw or await self._apply_goal_delta(
                    action_run, action.raw["gap_update"],
                    allow_inferred_delivery=action.kind == "answer" and not action.raw.get("disposition"),
                )
                if await self._apply_steering(action_run, messages, usage, output_sink):
                    await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="user_steering_applied")
                    continue

                if action.kind in {"answer", "await_user"}:
                    try:
                        disposition = self._terminal_disposition(action_run, action, delta_accepted=delta_accepted)
                    except ValueError as exc:
                        await self._replace_answer(action_run, "", output_sink)
                        await self._observe_outcome(
                            action_run, messages, model_step_id=model_step_id, assistant_content=content,
                            result=ToolExecutionResult(tool_name="runtime.terminal_decision", ok=False, error=ToolErrorInfo(
                                "USER_DEPENDENCY_REQUIRED" if action.kind == "await_user" else "GOAL_UNRESOLVED",
                                str(exc), "progress_control", False,
                                advice="Continue with a permitted investigation or submit a justified terminal decision.",
                            )),
                        )
                        continue
                    if action.kind == "await_user":
                        return await self._await_input(action_run, action, messages, usage, model_step_id, output_sink)
                    result = await self._complete_answer(
                        action_run,
                        action=action,
                        usage=usage,
                        started=started,
                        model_step_id=model_step_id,
                        messages=messages,
                        execution_outcome={"stop_reason": disposition, "goal_status": "unverified",
                                           "response_source": "model"} if disposition else None,
                    )
                    await self._replace_answer(action_run, action.content, output_sink)
                    return result

                if await self._control_progress(action_run, action, messages, model_step_id, content, output_sink):
                    continue

                pending = await self._prepare_tool_batch(
                    action_run,
                    action=action,
                    model_step_id=model_step_id,
                    messages=messages,
                    assistant_content=content,
                    confirmation_resolver=confirmation_resolver,
                )
                preparation_error = pending if isinstance(pending, ToolErrorInfo) else None
                if await self._apply_steering(action_run, messages, usage, output_sink):
                    await self._transition(action_run, ActionPhase.OBSERVING, cause="outdated_proposal_withdrawn")
                    await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="user_steering_applied")
                    continue
                if isinstance(pending, ActionResult):
                    pending.usage = dict(usage)
                    return pending
                if preparation_error is None and tool_executor is None and any(not call.is_capability for call in action.calls):
                    preparation_error = ToolErrorInfo(
                        code="TOOL_EXECUTOR_UNAVAILABLE", message="Runtime tool execution is unavailable; no calls were executed.",
                        category="capability", retryable=False,
                    )
                if preparation_error is not None:
                    results = []
                    for call in action.calls:
                        blocked_by = preparation_error.details.get("tool_call_id")
                        error = preparation_error if not blocked_by or call.call_id == blocked_by else ToolErrorInfo(
                            code="BATCH_NOT_EXECUTED", message="Another proposed operation failed admission; this call was not executed.",
                            category="validation", retryable=False,
                            details={"blocking_call_id": blocked_by, "cause_code": preparation_error.code},
                        )
                        results.append(ToolExecutionResult(tool_name=call.tool_name, ok=False, error=error))
                else:
                    await self._transition(
                        action_run,
                        ActionPhase.EXECUTING,
                        cause="tool_batch_started",
                        facts={"model_step_id": model_step_id, "call_count": len(action.calls)},
                    )
                    await self._checkpoint(action_run, messages, usage, pending_calls=[{
                        "tool_name": call.tool_name, "arguments": call.arguments, "call_id": call.call_id,
                        "operation": call.operation,
                    } for call in action.calls])
                    results = await self._execute_batch(
                        action_run, action, tool_executor, model_step_id=model_step_id,
                        capability_inspector=capability_inspector, capability_resolver=capability_resolver,
                    )
                from gateway.delegation import take_delegated_usage

                delegated_usage = take_delegated_usage()
                if delegated_usage:
                    self._merge_usage(usage, delegated_usage)
                observations = await self._record_tool_results(
                    action_run, action, results, model_step_id=model_step_id,
                    started_ids={call.call_id for call in action.calls} if preparation_error is None else set(),
                )
                messages.extend(self._observation_messages(content, observations, model_step_id=model_step_id if model_step_id in action_run.model_wire else None))
                previous_budget = action_run.budget
                self._grant_progress_grace(action_run, messages, observations)
                await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="observation_committed",
                                       facts={"step_budget_extended": action_run.budget - previous_budget}
                                       if action_run.budget > previous_budget else None)

            return await self._finish_stopped(
                action_run,
                messages,
                usage,
                started,
                output_sink=output_sink,
                reasoning_sink=reasoning_sink,
                stop_reason=stop_reason,
                unavailable_model=unavailable_model,
            )
        except asyncio.CancelledError:
            if action_run.machine.phase not in {ActionPhase.FAILED, ActionPhase.CANCELLED, ActionPhase.COMPLETED}:
                await self._transition(action_run, ActionPhase.CANCELLED, cause="runtime_task_cancelled")
            action_run.status = "cancelled"
            action_run.ended_at = time.time()
            raise
        except Exception as exc:
            await self._replace_answer(action_run, "", output_sink)
            if isinstance(exc, ModelResponseError):
                self._merge_usage(usage, exc.usage)
            if isinstance(exc, (ModelResponseError, InvalidModelAction)):
                logger.warning("ActionService model step failed: {}", exc)
            else:
                logger.exception("ActionService control loop failed: {}", exc)
            if action_run.machine.phase not in {ActionPhase.FAILED, ActionPhase.CANCELLED, ActionPhase.COMPLETED}:
                await self._transition(
                    action_run,
                    ActionPhase.FAILED,
                    cause="runtime_error",
                    facts={"error_type": exc.__class__.__name__, "message": str(exc)},
                )
            action_run.status = "error"
            action_run.ended_at = time.time()
            action_run.add_trace("action.failed", {"error": str(exc)})
            await self._emit_lifecycle("action.failed", action_run, {"error": str(exc)})
            return ActionResult(
                status="error",
                content="",
                raw={
                    "status": "error",
                    "error": {
                        "type": exc.__class__.__name__,
                        "code": getattr(exc, "code", "RUN_FAILED"),
                        "message": str(exc),
                    },
                    "observations": list(action_run.observations),
                    "execution_path": list(action_run.execution_path),
                    "reasoning_steps": list(action_run.reasoning_steps),
                    **self._gap_result(action_run),
                    "action_state": action_run.machine.snapshot(),
                    "action_state_transitions": list(action_run.machine.transitions),
                },
                run_id=action_run.run_id,
                trace=list(action_run.trace),
                usage=usage or None,
            )
        finally:
            action_run.accepting_steering = False
            self._active_runs.pop(action_run.run_id, None)

    def _terminal_disposition(self, run, action, *, delta_accepted=True):
        state = run.gap_state if self._gap_policy(run).enabled else GoalGapState()
        if not delta_accepted:
            raise ValueError("The terminal decision depends on a rejected Goal Gap update.")
        if action.kind == "await_user":
            validate_user_dependency(state, action.raw.get("user_dependency"), run.observations,
                                     input_kind=action.raw.get("input_kind", "acknowledgement"))
            return None
        if (not state.gaps and state.recovery.mode == "reassess" and getattr(run.context.run_context, "task_id", None)
                and not action.raw.get("disposition")):
            raise ValueError("The task still has an unresolved Runtime obstacle; continue or report a blocked goal.")
        blocked = action.raw.get("disposition") == "blocked"
        if blocked:
            validate_partial_evidence(state, action.evidence_refs, run.observations)
        return answer_disposition(state, blocked=blocked, observations=run.observations)

    async def _await_input(self, run, action, messages, usage, model_step_id, output_sink):
        request = {"request_id": f"input_{uuid.uuid4().hex}", "content": action.content,
                   "input_kind": action.raw.get("input_kind", "acknowledgement")}
        run.pending_input = {**request, "model_step_id": model_step_id, "action_content": json.dumps(action.raw, ensure_ascii=False)}
        await self._transition(run, ActionPhase.WAITING_INPUT, cause="user_input_requested",
                               facts={"request_id": request["request_id"], "model_step_id": model_step_id})
        run.status = "needs_input"
        waiting = ActionResult(status="needs_input", content=action.content, run_id=run.run_id,
            usage=usage, trace=list(run.trace), raw={
                "messages": messages, "input_request": request, "observations": list(run.observations),
                "reasoning_steps": list(run.reasoning_steps), **self._gap_result(run),
                "action_state": run.machine.snapshot(), "action_state_transitions": list(run.machine.transitions),
            })
        await self._checkpoint(run, messages, usage, result=waiting.to_chat_loop_result())
        await self._replace_answer(run, action.content, output_sink)
        return waiting

    async def _prepare_tool_batch(
        self,
        action_run: ActionRun,
        *,
        action: ModelAction,
        model_step_id: str,
        messages: List[Dict[str, Any]],
        assistant_content: str,
        confirmation_resolver: Optional[Any],
    ) -> Optional[ActionResult | ToolErrorInfo]:
        await self._transition(
            action_run,
            ActionPhase.VALIDATING,
            cause="tool_batch_proposed",
            facts={"model_step_id": model_step_id, "call_count": len(action.calls)},
        )
        pending_call = None
        for call in action.calls:
            if call.is_capability:
                continue
            requires_confirmation = False
            if confirmation_resolver is not None:
                try:
                    requires_confirmation = confirmation_resolver(call.tool_name, call.arguments)
                    if inspect.isawaitable(requires_confirmation):
                        requires_confirmation = await requires_confirmation
                except Exception as exc:
                    if getattr(exc, "code", None):
                        error = error_from_exception(exc)
                        return ToolErrorInfo(error.code, error.message, error.category, error.retryable, error.advice,
                                             {**error.details, "tool_call_id": call.call_id})
                    return ToolErrorInfo(
                        code="TOOL_AUTHORIZATION_UNAVAILABLE", message=str(exc) or type(exc).__name__,
                        category="policy", retryable=False,
                        advice="This batch was not executed. Authorization could not be established; do not bypass it.",
                        details={"tool_name": call.tool_name, "tool_call_id": call.call_id},
                    )
            if not requires_confirmation or call.call_id in action_run.approved_call_ids:
                continue
            pending_call = pending_call or call
        if pending_call is None:
            return None
        call = pending_call
        await self._transition(
            action_run,
            ActionPhase.WAITING_CONFIRMATION,
            cause="confirmation_required",
            facts={"model_step_id": model_step_id, "tool_call_id": call.call_id, "tool_name": call.tool_name},
        )
        action_run.status = "needs_confirmation"
        raw_calls = [
            {"id": item.call_id, "name": item.tool_name, "args": dict(item.arguments), "operation": item.operation}
            for item in action.calls
        ]
        raw = {
            "status": "needs_confirmation",
            "tool_call_id": call.call_id,
            "tool_name": call.tool_name,
            "args": dict(call.arguments),
            "current_messages": list(messages),
            "pending_tool_calls": raw_calls,
            "approved_call_ids": sorted(action_run.approved_call_ids),
            "applied_steering_ids": list(action_run.applied_steering_ids),
            "procedure_refs": list(action.raw.get("procedure_refs", [])),
            "content": assistant_content,
            "model_step_id": model_step_id,
            "step": action_run.step,
            "budget": action_run.budget,
            "progress_grace_steps": action_run.progress_grace_steps,
            "goal": action_run.goal,
            "runtime_scope": {
                "user_id": action_run.context.user_id,
                "session_id": action_run.context.session_id,
                **{key: getattr(action_run.context.run_context, key, None) for key in
                   ("task_id", "task_run_id", "workflow_run_id", "conversation_turn_id")},
            },
            "task_checkpoint": {"objective": action_run.gap_task_objective, "execution_token": action_run.gap_execution_token}
                if self.task_service is not None and getattr(action_run.context.run_context, "task_id", None) else None,
            "observations": list(action_run.observations),
            "execution_path": list(action_run.execution_path),
            "reasoning_steps": list(action_run.reasoning_steps),
            "model_recovery": dict(action_run.model_recovery),
            "model_protocol": action_run.model_protocol,
            "model_wire": dict(action_run.model_wire),
            **self._gap_result(action_run),
            "action_state": action_run.machine.snapshot(),
            "action_state_transitions": list(action_run.machine.transitions),
        }
        return ActionResult(
            status="needs_confirmation", content=assistant_content, raw=raw,
            run_id=action_run.run_id, trace=list(action_run.trace),
        )

    @staticmethod
    def _restore_confirmation_scope(pending: Dict[str, Any], *, session_id: Optional[str],
                                    user_id: Optional[str], run_context: Optional[Any]) -> None:
        scope = pending.get("runtime_scope") or {}
        for key, actual in (("user_id", user_id), ("session_id", session_id)):
            if scope.get(key) and scope[key] != actual:
                raise PermissionError(f"confirmation {key} does not match its Runtime checkpoint")
        for key in ("task_id", "task_run_id", "workflow_run_id", "conversation_turn_id"):
            expected = scope.get(key)
            actual = getattr(run_context, key, None)
            if key != "conversation_turn_id" and actual and actual != expected:
                raise PermissionError("confirmation task scope does not match its Runtime checkpoint")
            if expected:
                if run_context is None or actual and actual != expected:
                    raise PermissionError("confirmation requires its original Runtime context")
                setattr(run_context, key, expected)
        checkpoint = pending.get("task_checkpoint") or {}
        token = checkpoint.get("execution_token") or {}
        if token and run_context is not None:
            existing = getattr(run_context, "execution_token", None)
            if existing and existing != token:
                raise PermissionError("confirmation execution token does not match its Runtime checkpoint")
            run_context.execution_token = dict(token)

    def _assert_task_execution(self, action_run: ActionRun) -> None:
        context = action_run.context
        task_id = getattr(context.run_context, "task_id", None)
        if self.task_service is not None and task_id:
            self.task_service.assert_action_execution(
                task_id=task_id, user_id=context.user_id,
                expected_objective=action_run.gap_task_objective,
                task_run_id=getattr(context.run_context, "task_run_id", None),
                execution_token=action_run.gap_execution_token,
            )

    @staticmethod
    def _gap_policy(action_run: ActionRun) -> GoalGapConfig:
        config = action_run.context.user_config or {}
        action = config.get("action") or {}
        return GoalGapConfig(**(action.get("gaps") or {}))

    def _load_goal_gaps(self, action_run: ActionRun, *, capture_token: bool = True) -> None:
        context = action_run.context
        task_id = getattr(context.run_context, "task_id", None)
        if self.task_service is None or not task_id:
            return
        task = self.task_service.get_task(task_id, user_id=context.user_id)
        if task is None or not context.user_id:
            raise PermissionError("goal state requires an owned Runtime task")
        action_run.gap_state = GoalGapState.model_validate(task.get("goal_gaps") or {})
        if not action_run.observations:
            # Goal requirements survive Task runs; execution guards need this loop's receipts.
            action_run.gap_state.recent = []
            action_run.gap_state.recovery = GapRecoveryState()
        action_run.gap_task_revision = action_run.gap_state.revision
        if capture_token:
            action_run.gap_task_objective = task.get("objective", "")
            action_run.gap_execution_token = dict(getattr(context.run_context, "execution_token", None) or {})
        self._assert_task_execution(action_run)
        if context.run_context is not None and action_run.gap_state.gaps:
            context.run_context.goal_gaps = self._gap_view(action_run)

    async def _save_goal_gaps(self, action_run: ActionRun, state: GoalGapState) -> bool:
        context = action_run.context
        task_id = getattr(context.run_context, "task_id", None)
        if self.task_service is not None and task_id:
            from gateway.task_service import TaskRevisionConflict
            try:
                self.task_service.commit_goal_gaps(
                    task_id=task_id, user_id=context.user_id, state=state,
                    expected_revision=action_run.gap_task_revision,
                    expected_objective=action_run.gap_task_objective,
                    execution_token=action_run.gap_execution_token,
                )
            except TaskRevisionConflict as exc:
                self._load_goal_gaps(action_run, capture_token=False)
                action_run.gap_feedback = str(exc)
                return False
            action_run.gap_task_revision = state.revision
        else:
            await self._emit_event(EventType.GOAL_GAPS_UPDATED, action_run, gap_event_delta(action_run.gap_state, state))
        action_run.gap_state = state
        run_context = context.run_context
        if run_context is not None:
            run_context.goal_gaps = self._gap_view(action_run)
        action_run.add_trace("goal.gaps.updated", {"revision": state.revision, "summary": gap_outcome(state)})
        return True

    async def _apply_goal_delta(self, action_run: ActionRun, raw: Any, *, allow_inferred_delivery: bool = False) -> bool:
        policy = self._gap_policy(action_run)
        if not policy.enabled:
            return True
        registry = getattr(self.capability_service, "tool_registry", None)

        def output_schema(name):
            try:
                return registry.resolve(tool_name=name, params={}).output_schema
            except ToolNotFoundError:
                return {}

        try:
            state = apply_gap_delta(action_run.gap_state, raw, action_run.observations, max_gaps=policy.max_gaps,
                                    max_updates=policy.max_updates, loop_id=action_run.run_id,
                                    output_schema=output_schema if registry is not None else None,
                                    allow_inferred_delivery=allow_inferred_delivery)
        except (ValueError, TypeError) as exc:
            action_run.gap_feedback = str(exc)[:200]
            action_run.add_trace("goal.gaps.rejected", {"reason": action_run.gap_feedback})
            return False
        if state.revision != action_run.gap_state.revision:
            action_run.gap_feedback = ""
            return await self._save_goal_gaps(action_run, state)
        return True

    def _gap_view(self, action_run: ActionRun) -> Dict[str, Any]:
        policy = self._gap_policy(action_run)
        return gap_projection(action_run.gap_state, context_chars=policy.context_chars, window=policy.window,
                              feedback=action_run.gap_feedback, observations=action_run.observations,
                              objective=action_run.goal if policy.semantic_context else "",
                              advisory_recovery=policy.advisory_recovery)

    def _with_goal_projection(self, action_run: ActionRun, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._gap_policy(action_run).enabled:
            return messages
        view = self._gap_view(action_run)
        if not (action_run.gap_state.gaps or action_run.gap_state.recent or action_run.gap_feedback or view.get("recent_obstacles") or view.get("execution_control")):
            return messages
        context = "Runtime goal gaps (authoritative revision; interpretations may be provisional):\n" + json.dumps(view, ensure_ascii=False, separators=(",", ":"))
        from gateway.runtime_io import replace_context, GOAL_CONTEXT
        return replace_context(messages, GOAL_CONTEXT, context)

    @staticmethod
    def _gap_result(action_run: ActionRun) -> Dict[str, Any]:
        if not (action_run.gap_state.gaps or action_run.gap_state.recent or action_run.gap_state.recovery.failed_calls):
            return {}
        return {"goal_gaps": action_run.gap_state.model_dump(), "goal_progress": gap_outcome(action_run.gap_state)}

    async def _record_tool_results(self, action_run: ActionRun, action: ModelAction, results: List[ToolExecutionResult], *, model_step_id: str, started_ids: set[str]) -> List[RuntimeObservation]:
        observations = [RuntimeObservation.from_result(
            action_loop_id=action_run.run_id, model_step_id=model_step_id,
            tool_call_id=call.call_id, tool_name=call.tool_name, result=result,
            capability_snapshot_id=self._capability_snapshot_id(action_run), scope=self._observation_scope(action_run),
        ) for call, result in zip(action.calls, results)]
        for call, result, observation in zip(action.calls, results, observations):
            record = {
                "kind": call.operation, "tool_call_id": call.call_id, "tool_name": call.tool_name,
                "args": dict(call.arguments), "ok": bool(result.ok), "observation_id": observation.observation_id,
                "executed": call.call_id in started_ids, "requires_confirmation": call.call_id in action_run.approved_call_ids,
                "procedure_refs": list(action.raw.get("procedure_refs", [])),
            }
            if call.operation == "capability_request":
                projection = result.value if result.ok and isinstance(result.value, dict) else {}
                record.update({**call.arguments,
                    "exposed_procedures": [item["reference"] for item in (projection.get("process_experience") or {}).get("rules", [])],
                    "candidate_names": [str(item.get("name")) for item in (projection.get("candidates") or [])
                                        if isinstance(item, dict) and item.get("name")],
                })
            action_run.execution_path.append(record)
        action_run.approved_call_ids.difference_update(call.call_id for call in action.calls)
        await self._commit_observations(action_run, observations)
        known = {gap.id for gap in action_run.gap_state.gaps}
        for call, result in zip(action.calls, results):
            if (call.operation != "tool_call" or call.tool_name != "reasoning.run"
                    or call.call_id not in started_ids or not result.ok or not isinstance(result.value, dict)):
                continue
            proposals = result.value.get("delivery_gaps")
            if not isinstance(proposals, list):
                continue
            create = [row for row in proposals if isinstance(row, dict) and isinstance(row.get("id"), str)
                      and row["id"] not in known]
            if create and await self._apply_goal_delta(action_run, {"revision": action_run.gap_state.revision, "create": create}):
                known.update(row["id"] for row in create)
        return observations

    def _grant_progress_grace(self, run: ActionRun, messages: List[Dict[str, Any]], observations: List[RuntimeObservation]) -> None:
        extra = min(run.progress_grace_steps, MAX_ACTION_BUDGET - run.budget)
        if extra <= 0 or run.step != run.budget:
            return
        context = run.context.run_context
        if any(getattr(context, key, None) is not None for key in ("cost_budget", "token_budget")):
            return
        tracked = bool(run.gap_state.gaps)
        recent = run.gap_state.recent[-self._gap_policy(run).window:]
        progress = ("checked" if any(frame.progress for frame in recent)
                    else "candidate" if any(frame.candidate_progress for frame in recent) else None)
        if (tracked and not progress) or (not tracked and run.gap_state.recovery.mode != "execute"):
            return
        if not observations or (not tracked and any(not row.ok for row in observations)):
            return
        executed = {row["observation_id"] for row in run.execution_path[-len(observations):]
                    if row.get("executed") and row.get("kind") == "tool_call"}
        def evidence(row):
            value = row.get("structured_result")
            return row.get("model_projection") if value is None else value

        prior, latest = run.observations[:-len(observations)], run.observations[-len(observations):]
        for row in latest:
            value = evidence(row)
            if not row.get("ok") or row["observation_id"] not in executed or value in (None, "", [], {}):
                continue
            # Changing arguments alone does not make an unchanged result new evidence.
            if any(item.get("ok") and item.get("tool_name") == row["tool_name"] and evidence(item) == value for item in prior):
                continue
            run.budget += extra
            run.progress_grace_steps = 0
            run.add_trace("action.budget_extended", {"step": run.step, "extra_steps": extra,
                                                     "progress": progress or "new_observation", "observation_id": row["observation_id"]})
            messages.append({"role": "user", "name": "promethea_action_budget", "content": (
                f"Runtime granted {extra} additional decisions after recent progress. "
                "Use them for the most important remaining checks or to finish the answer. "
                "Do not repeat completed work. No further automatic extension is available."
            )})
            break

    async def _execute_batch(self, action_run: ActionRun, action: ModelAction, executor: Any, *, model_step_id: str,
                             capability_inspector=None, capability_resolver=None) -> List[ToolExecutionResult]:
        from config import ActionConfig, config

        policy = ActionConfig(**{**config.action.model_dump(), **((action_run.context.user_config or {}).get("action") or {})})
        running = set()
        tasks = {}
        results = {}

        async def settle(*, all_pending=False):
            if not running:
                return
            done, _ = await asyncio.wait(running, return_when=asyncio.ALL_COMPLETED if all_pending else asyncio.FIRST_COMPLETED)
            for task in done:
                results[tasks[task]] = task.result()
                running.remove(task)

        try:
            for index, call in enumerate(action.calls):
                while True:
                    registry = getattr(self.capability_service, "tool_registry", None)
                    try:
                        spec = registry.resolve_for_call(tool_name=call.tool_name, params=call.arguments) if registry is not None and not call.is_capability else None
                    except ToolNotFoundError:
                        spec = None  # Dispatch revalidates; lookup failure is not a scheduler crash.
                    parallel = bool(spec is not None and spec.concurrency_safe)
                    if running and (not parallel or len(running) >= policy.max_parallel_tool_calls):
                        await settle(all_pending=not parallel)
                        continue
                    break
                self._assert_task_execution(action_run)
                task = asyncio.create_task(self._execute_call(
                    executor, call, call.call_id in action_run.approved_call_ids, action_run=action_run,
                    capability_inspector=capability_inspector, capability_resolver=capability_resolver,
                ))
                tasks[task] = index
                running.add(task)
                if not parallel:
                    await settle(all_pending=True)
            await settle(all_pending=True)
        except BaseException as exc:
            for task in tasks:
                if not task.done():
                    task.cancel()
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            if isinstance(exc, asyncio.CancelledError):
                started = set(tasks.values())
                for task, value in zip(tasks, settled):
                    if isinstance(value, ToolExecutionResult):
                        results[tasks[task]] = value
                for index, call in enumerate(action.calls):
                    if index not in results:
                        dispatched = index in started
                        results[index] = ToolExecutionResult(tool_name=call.tool_name, ok=False, error=ToolErrorInfo(
                            code="TOOL_INTERRUPTED" if dispatched else "TOOL_NOT_EXECUTED",
                            message="Execution was interrupted; side effects may have occurred." if dispatched else "This call was not dispatched before cancellation.",
                            category="cancellation", retryable=False,
                        ))
                await self._record_tool_results(
                    action_run, action, [results[index] for index in range(len(action.calls))], model_step_id=model_step_id,
                    started_ids={action.calls[index].call_id for index in started},
                )
            raise
        return [results[index] for index in range(len(action.calls))]

    async def _execute_call(self, executor: Any, call: ToolCallProposal, approved: bool, *, action_run: ActionRun,
                            capability_inspector=None, capability_resolver=None) -> ToolExecutionResult:
        self._assert_task_execution(action_run)
        if call.is_capability:
            inspector = call.operation == "capability_inspect"
            return await self._capability_outcome(
                call.tool_name, capability_inspector if inspector else capability_resolver,
                call.arguments["capability_names"] if inspector else call.arguments,
            )
        try:
            with approval_scope(call.tool_name, call.arguments, confirmed=approved):
                value = executor(call.tool_name, dict(call.arguments))
                if inspect.isawaitable(value):
                    value = await value
            return normalize_tool_result(call.tool_name, value)
        except Exception as exc:
            return failed_tool_result(call.tool_name, exc)

    @staticmethod
    async def _capability_outcome(name: str, callback: Optional[Callable], request: Any) -> ToolExecutionResult:
        if callback is None:
            return ToolExecutionResult(
                tool_name=name, ok=False,
                error=ToolErrorInfo("CAPABILITY_SERVICE_UNAVAILABLE", "This Runtime capability operation is unavailable.", "capability"),
            )
        try:
            projection = await callback(request)
            if not isinstance(projection, dict):
                raise ValueError("capability operation returned an invalid projection")
            return normalize_tool_result(name, projection)
        except Exception as exc:
            return failed_tool_result(name, exc)

    async def _control_progress(self, run, action, messages, model_step_id, content, output_sink) -> bool:
        policy = self._gap_policy(run)
        if not policy.enabled:
            return False
        registry = getattr(self.capability_service, "tool_registry", None)

        def can_explore(call):
            if call.is_capability:
                return True
            try:
                if registry is None:
                    return False
                level = registry.resolve_for_call(tool_name=call.tool_name, params=call.arguments).side_effect_level
                return level == SideEffectLevel.READ_ONLY or (
                    policy.advisory_recovery and level == SideEffectLevel.WORKSPACE_WRITE)
            except (ValueError, ToolNotFoundError):
                return False

        diagnostic = run.gap_state.recovery.mode == "reassess" and bool(action.calls) and all(can_explore(call) for call in action.calls)
        calls = [{"tool_name": call.tool_name, "args": call.arguments} for call in action.calls]
        candidate, denial = admit_gap_action(run.gap_state, calls, run.observations, diagnostic=diagnostic)
        if candidate.revision != run.gap_state.revision and not await self._save_goal_gaps(run, candidate):
            denial = "Goal state changed; reassess the current Runtime revision before execution."
        if not denial:
            return False
        await self._replace_answer(run, "", output_sink)
        results = [ToolExecutionResult(tool_name=call["tool_name"], ok=False, error=ToolErrorInfo(
            code="ACTION_REASSESSMENT_REQUIRED", message=denial, category="progress_control", retryable=False,
            advice="No proposed operation executed. Investigate with a new read-only call, or propose an evidence-backed recovery.",
        )) for call in calls]
        observations = await self._record_tool_results(run, action, results, model_step_id=model_step_id, started_ids=set())
        messages.extend(self._observation_messages(content, observations, model_step_id=model_step_id if model_step_id in run.model_wire else None))
        await self._transition(run, ActionPhase.AWAITING_MODEL, cause="progress_control_rejected_proposal")
        return True

    async def _observe_outcome(
        self, action_run: ActionRun, messages: List[Dict[str, Any]], *,
        model_step_id: str, result: ToolExecutionResult, assistant_content: str = "",
    ) -> None:
        observation = RuntimeObservation.from_result(
            action_loop_id=action_run.run_id, model_step_id=model_step_id,
            tool_call_id=f"runtime_{uuid.uuid4().hex}", tool_name=result.tool_name,
            result=result, capability_snapshot_id=self._capability_snapshot_id(action_run),
            scope=self._observation_scope(action_run),
        )
        await self._commit_observations(action_run, [observation])
        messages.extend(self._observation_messages(assistant_content, [observation], model_step_id=model_step_id if assistant_content and model_step_id in action_run.model_wire else None))
        await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="observation_committed")

    @staticmethod
    def _validate_answer_evidence(action_run: ActionRun, action: ModelAction) -> None:
        known = {item.get("observation_id") for item in action_run.observations}
        if any(ref not in known for ref in action.evidence_refs):
            raise InvalidModelAction("answer references observations outside the current action loop")

    async def _commit_observations(
        self,
        action_run: ActionRun,
        observations: List[RuntimeObservation],
    ) -> None:
        await self._transition(
            action_run,
            ActionPhase.OBSERVING,
            cause="tool_batch_settled",
            facts={"observation_count": len(observations)},
        )
        for observation in observations:
            payload = _json_safe(observation.as_dict())
            payload["model_projection"] = [block for block in payload["model_projection"] if not block.get("_workspace_media")]
            action_run.observations.append(payload)
            await self._emit_event(
                EventType.ACTION_OBSERVATION_COMMITTED,
                action_run,
                _audit_observation(payload),
            )
        policy = self._gap_policy(action_run)
        if policy.enabled:
            candidate = observe_gap_step(action_run.gap_state, action_run.execution_path, action_run.observations[-len(observations):] if observations else [], window=policy.window)
            if candidate.revision != action_run.gap_state.revision:
                await self._save_goal_gaps(action_run, candidate)

    async def _complete_answer(
        self,
        action_run: ActionRun,
        *,
        action: ModelAction,
        usage: Dict[str, int],
        started: float,
        model_step_id: str,
        messages: List[Dict[str, Any]],
        execution_outcome: Optional[Dict[str, Any]] = None,
        completion_error: Optional[Dict[str, Any]] = None,
    ) -> ActionResult:
        self._assert_task_execution(action_run)
        self._validate_answer_evidence(action_run, action)
        action_run.accepting_steering = False
        await self._transition(
            action_run,
            ActionPhase.COMPLETED,
            cause="answer_committed",
            facts={"model_step_id": model_step_id, "evidence_refs": action.evidence_refs},
        )
        action_run.status = "success"
        action_run.ended_at = time.time()
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        action_run.add_trace("action.finished", {"status": "success", "duration_ms": duration_ms})
        await self._emit_lifecycle("action.finished", action_run, {"status": "success", "duration_ms": duration_ms})
        raw = {
            "status": "success",
            "content": action.content,
            "messages": messages,
            "observations": list(action_run.observations),
            "execution_path": list(action_run.execution_path),
            "reasoning_steps": list(action_run.reasoning_steps),
            "model_recovery": dict(action_run.model_recovery),
            "evidence_refs": list(action.evidence_refs),
            **self._gap_result(action_run),
            "action_state": action_run.machine.snapshot(),
            "action_state_transitions": list(action_run.machine.transitions),
        }
        if execution_outcome is not None:
            raw["execution_outcome"] = execution_outcome
        if completion_error is not None:
            raw["completion_error"] = completion_error
        return ActionResult(
            status="success",
            content=action.content,
            raw=raw,
            run_id=action_run.run_id,
            trace=list(action_run.trace),
            usage=usage or None,
        )

    async def _finish_stopped(
        self,
        action_run: ActionRun,
        messages: List[Dict[str, Any]],
        usage: Dict[str, int],
        started: float,
        *,
        output_sink: Optional[OutputSink],
        reasoning_sink: Optional[ReasoningSink],
        stop_reason: str = "budget_exhausted",
        unavailable_model: Optional[ModelResponseError] = None,
    ) -> ActionResult:
        action_run.accepting_steering = False
        await self._apply_steering(action_run, messages, usage, output_sink)
        self._assert_task_execution(action_run)
        progress_recovery = max(action_run.gap_state.recovery.rejections, action_run.gap_state.recovery.failed_trials) >= self._gap_policy(action_run).max_recovery_attempts
        await self._observe_outcome(
            action_run, messages, model_step_id=f"step_{uuid.uuid4().hex}",
            result=ToolExecutionResult(
                tool_name="runtime.action_budget" if stop_reason == "budget_exhausted" else "runtime.action_recovery" if progress_recovery else "runtime.model_recovery", ok=False,
                error=ToolErrorInfo(
                    code="ACTION_BUDGET_EXHAUSTED" if stop_reason == "budget_exhausted" else "ACTION_RECOVERY_EXHAUSTED" if progress_recovery else "MODEL_RECOVERY_EXHAUSTED",
                    message="Execution stopped; no further tools may execute in this turn.",
                    category="budget" if stop_reason == "budget_exhausted" else "execution_boundary", retryable=False,
                    advice="Give the user a concise answer explaining the verified results and remaining obstacles; do not claim unfinished work succeeded.",
                ),
            ),
        )
        completion_messages = [*messages, {
            "role": "user",
            "content": (
                f"Execution has stopped ({stop_reason}). Give a concise final progress report in the "
                "user's language. For tracked gaps, only results supported by a checked Goal Gap are verified. "
                "Successful tool calls with assumed inputs are trials: describe the limitation, not their output as a deliverable. "
                "Use an answer action with evidence_refs for any verified partial deliverables. "
                "Explain what remains unverified or blocked. "
                "Return ordinary user-facing text or an answer action. If progress specifically needs a human "
                "response, use await_user to persist the question and pause instead of only describing a wait. "
                "No tools can execute in this phase. Do not promise an unavailable capability."
            ),
        }]
        model_step_id = f"step_{uuid.uuid4().hex}"
        completion_error = None
        response_source = "model"
        try:
            if unavailable_model is not None:
                raise unavailable_model
            response = await self._call_model(
                action_run, completion_messages, model_step_id,
                output_sink=output_sink, reasoning_sink=reasoning_sink,
                final_answer=True,
            )
            self._merge_usage(usage, response.get("usage"))
            action = parse_final_answer(str(response.get("content") or ""))
            self._validate_answer_evidence(action_run, action)
            delta_accepted = "gap_update" not in action.raw or await self._apply_goal_delta(action_run, action.raw["gap_update"])
            if action.kind == "await_user":
                self._terminal_disposition(action_run, action, delta_accepted=delta_accepted)
            elif self._gap_policy(action_run).enabled and action_run.gap_state.gaps:
                if not delta_accepted:
                    raise ValueError("The progress report depends on a rejected Goal Gap update.")
                validate_partial_evidence(action_run.gap_state, action.evidence_refs, action_run.observations)
        except Exception as exc:
            if isinstance(exc, ModelResponseError):
                self._merge_usage(usage, exc.usage)
            completion_error = {"code": getattr(exc, "code", "FINAL_RESPONSE_FAILED"), "message": str(exc), "type": type(exc).__name__}
            await self._observe_outcome(
                action_run, messages, model_step_id=model_step_id,
                result=ToolExecutionResult(tool_name="runtime.completion", ok=False, error=ToolErrorInfo(
                    completion_error["code"], str(exc), "completion", False,
                )),
            )
            response_source = "runtime"
            payload = getattr(action_run.context.run_context, "input_payload", None) or {}
            metadata = payload.get("metadata") or {}
            action = ModelAction(kind="answer", content=runtime_progress_notice(
                action_run.observations, str(metadata.get("ui_language") or "en"), stop_reason=stop_reason,
                completion_code=completion_error["code"],
            ))
            action_run.add_trace("action.completion_failed", completion_error)
        await self._transition(action_run, ActionPhase.EVALUATING, cause="budget_final_response_settled")
        if action.kind == "await_user":
            return await self._await_input(action_run, action, messages, usage, model_step_id, output_sink)
        result = await self._complete_answer(
            action_run,
            action=action,
            usage=usage,
            started=started,
            model_step_id=model_step_id,
            messages=messages,
            execution_outcome={
                "stop_reason": stop_reason, "goal_status": "unverified",
                "response_source": response_source,
            },
            completion_error=completion_error,
        )
        await self._replace_answer(action_run, action.content, output_sink)
        return result

    async def _call_model(
        self,
        action_run: ActionRun,
        messages: List[Dict[str, Any]],
        model_step_id: str,
        *,
        output_sink: Optional[OutputSink],
        reasoning_sink: Optional[ReasoningSink],
        final_answer: bool = False,
    ) -> Dict[str, Any]:
        policy = ActionConfig(**{**global_config.action.model_dump(), **((action_run.context.user_config or {}).get("action") or {})})
        self._assert_task_execution(action_run)
        prepared = self._with_goal_projection(action_run, messages)
        remaining = [gap.requirement for gap in action_run.gap_state.gaps if gap.state != "resolved"][:3]
        prepared, compacted = compact_action_history(prepared, action_run.observations,
            max_chars=min(policy.context_action_chars, policy.observation_history_chars),
            max_batches=policy.context_action_batches, per_result_chars=policy.observation_chars,
            goal="\n".join([action_run.goal, *remaining]))
        if compacted:
            action_run.add_trace("action.context_rebuilt", {"step": action_run.step, "retained_observations": len(action_run.observations)})
        if action_run.context.prepare_messages is not None:
            prepared = await action_run.context.prepare_messages(prepared, action_run.observations)
        # Checkpoints retain the accepted bounded view; full observations remain Runtime-owned.
        messages[:] = prepared
        usage = {}
        for attempt in range(policy.max_model_recoveries + 1):
            self._assert_task_execution(action_run)
            try:
                response = await self._call_model_once(
                    action_run, messages, model_step_id, output_sink=output_sink,
                    reasoning_sink=reasoning_sink, final_answer=final_answer,
                )
            except ModelResponseError as exc:
                self._merge_usage(usage, exc.usage)
                exc.usage = usage
                if exc.code != "MODEL_TRANSPORT_TRANSIENT" or attempt >= policy.max_model_recoveries:
                    raise
                action_run.add_trace("action.model_transport_retry", {"model_step_id": model_step_id, "retry": attempt + 1})
                await self._replace_answer(action_run, "", output_sink)
                await asyncio.sleep(0.25 * 2 ** attempt)
            else:
                if attempt:
                    self._merge_usage(usage, response.get("usage"))
                    response["usage"] = usage
                return response

    async def _call_model_once(
        self,
        action_run: ActionRun,
        messages: List[Dict[str, Any]],
        model_step_id: str,
        *,
        output_sink: Optional[OutputSink],
        reasoning_sink: Optional[ReasoningSink],
        final_answer: bool = False,
    ) -> Dict[str, Any]:
        messages = list(messages)
        initial, ceiling = self._output_limits(action_run)
        user_config = dict(action_run.context.user_config or {})
        user_config["api"] = {**user_config.get("api", {}), "max_tokens": min(ceiling, initial if final_answer else int(action_run.model_recovery.get("output_tokens") or initial))}
        purpose = "final_response" if final_answer else "action"
        if not action_run.model_protocol:
            from gateway.user_secrets import resolve_llm_runtime_settings
            action_run.model_protocol = resolve_llm_runtime_settings(action_run.context.user_id, behavior_config=user_config)["tool_protocol"]
        if action_run.model_protocol not in {"prompt_json", "native"}:
            raise ModelResponseError("Unsupported API__TOOL_PROTOCOL", code="MODEL_PROTOCOL_CONFIG")
        retained_steps = {row.get("_model_step_id") for row in messages}
        action_run.model_wire = {key: value for key, value in action_run.model_wire.items() if key in retained_steps}
        user_config["_runtime_call"] = {"purpose": purpose, "protocol": action_run.model_protocol,
                                        "wire_history": action_run.model_wire, "observations": action_run.observations}
        action_run.model_recovery["model_calls"] = int(action_run.model_recovery.get("model_calls", 0)) + 1
        streamer = getattr(self.conversation_core, "call_llm_stream", None)
        if output_sink is not None and callable(streamer):
            await self._replace_answer(action_run, "", output_sink)
            projector = AnswerDeltaProjector()
            chunks: List[str] = []
            reasoning_chunks: List[str] = []
            stream_result: Dict[str, Any] = {}

            async def publish_result(result: Dict[str, Any]) -> None:
                stream_result.update(result)

            async def publish_reasoning(delta: str) -> None:
                text = str(delta or "")
                if not text:
                    return
                reasoning_chunks.append(text)
                if reasoning_sink is not None:
                    await reasoning_sink({
                        "step_id": model_step_id,
                        "source": "provider",
                        "delta": text,
                    })

            async for chunk in streamer(
                messages,
                user_config=user_config,
                user_id=action_run.context.user_id,
                reasoning_sink=publish_reasoning,
                result_sink=publish_result,
            ):
                text = str(chunk or "")
                if text.startswith("[error]"):
                    raw = {"status": "error", "error": text.removeprefix("[error]").strip(), "content": "".join(chunks)}
                    break
                chunks.append(text)
                # Final prose is released only after the complete answer-only response
                # is validated, so a late tool envelope or truncation cannot leak.
                delta = "" if final_answer else projector.feed(text)
                if delta:
                    action_run.streamed_answer += delta
                    await output_sink(delta)
            else:
                raw = {"status": "success", "content": "".join(chunks)}
            raw.update(stream_result)
            reasoning_content = "".join(reasoning_chunks).strip()
            if reasoning_content:
                step = {
                    "step_id": model_step_id,
                    "source": "provider",
                    "content": _bounded_text(reasoning_content, max_chars=24000),
                }
                action_run.reasoning_steps.append(step)
                raw["reasoning_content"] = step["content"]
            source = "runtime_stream"
        else:
            response = await self.conversation_core.call_llm(
                messages,
                user_config=user_config,
                user_id=action_run.context.user_id,
            )
            raw = response if isinstance(response, dict) else {"content": str(response or "")}
            source = "runtime"
        if str(raw.get("status") or "success").lower() in {"success", "ok", "completed"} and not str(raw.get("content") or "").strip():
            raw = {**raw, "status": "error", "code": "MODEL_EMPTY_RESPONSE", "error": "Model returned no action or answer."}
        if str(raw.get("status") or "success").lower() in {"success", "ok", "completed"} and raw.get("native_message") and "native_bindings" in raw:
            action_run.model_wire[model_step_id] = {"message": raw["native_message"], "bindings": raw["native_bindings"]}
        await self._record_model_call(
            action_run,
            messages=messages,
            model_step_id=model_step_id,
            response=raw,
            source=source,
            purpose=purpose,
        )
        status = str(raw.get("status") or "success").strip().lower()
        if status not in {"success", "ok", "completed"}:
            detail = str(raw.get("error") or raw.get("content") or "model provider request failed")
            raise ModelResponseError(detail, code=str(raw.get("code") or "MODEL_REQUEST_FAILED"), usage=raw.get("usage"),
                                     signature=_stable_hash({"code": raw.get("code"), "content": raw.get("content")}))
        return raw

    @staticmethod
    def _output_limits(action_run: ActionRun) -> tuple[int, int]:
        api = {**global_config.api.model_dump(), **((action_run.context.user_config or {}).get("api") or {})}
        ceiling = max(1, int(api["output_token_limit"]))
        return min(ceiling, max(1, int(api["max_tokens"]))), ceiling

    def _recover_output(self, action_run: ActionRun, code: str, signature: str) -> tuple[bool, str]:
        initial, ceiling = self._output_limits(action_run)
        policy = ActionConfig(**{**global_config.action.model_dump(), **((action_run.context.user_config or {}).get("action") or {})})
        result = recover_model_output(action_run.model_recovery, code=code, signature=signature,
                                      initial=initial, ceiling=ceiling, retries=policy.max_model_recoveries)
        action_run.add_trace("action.model_recovery", {"code": code, "retry": result[0], **action_run.model_recovery})
        return result

    async def _record_model_call(
        self,
        action_run: ActionRun,
        *,
        messages: List[Dict[str, Any]],
        model_step_id: str,
        response: Dict[str, Any],
        source: str,
        purpose: str = "action",
    ) -> None:
        self_model_context = self._self_model_context(action_run)
        manifest = {
            "model_call_id": f"model_{uuid.uuid4().hex}",
            "model_step_id": model_step_id,
            "provider_request_id": str(response.get("request_id")) if response.get("request_id") else None,
            "request_sent": response.get("request_sent"),
            "action_loop_id": action_run.run_id,
            "continuation_of": action_run.context.metadata.get("continuation_of"),
            "source": source,
            "purpose": purpose,
            "input_chars": len(json.dumps(messages, ensure_ascii=False, default=str)),
            "message_metrics": [{"role": row.get("role"), "name": row.get("name"), "hash": _stable_hash(row),
                                 "chars": len(json.dumps(row.get("content"), ensure_ascii=False, default=str))} for row in messages],
            "capability_snapshot_id": self._capability_snapshot_id(action_run),
            "self_model_snapshot_id": self._self_model_snapshot_id(action_run),
            "self_model_revision": self_model_context.get("revision") or self_model_context.get("version"),
            "self_model_context_hash": _stable_hash(self_model_context) if self_model_context else None,
            "observation_ids": [item.get("observation_id") for item in action_run.observations],
            "goal_gap_revision": action_run.gap_state.revision,
            "prompt_block_ids": self._prompt_block_ids(action_run),
            "prompt_block_hashes": self._prompt_block_hashes(action_run),
            "message_count": len(messages),
            "request_messages": _audit_messages(messages),
            "request_hash": _stable_hash(messages),
            "response_content": _bounded_text(str(response.get("content") or ""), max_chars=12000),
            "response_hash": _stable_hash(response.get("content", "")),
            "model_used": response.get("model_used"),
            "provider_status": response.get("status"),
            "provider_http_status": response.get("provider_status"),
            "provider_error_code": response.get("code"),
            "finish_reason": response.get("finish_reason"),
            "usage": response.get("usage"),
            "cost_estimate": response.get("cost_estimate"),
            "max_tokens": response.get("max_tokens"),
            "reasoning_chars": response.get("reasoning_chars"),
            "model_protocol": action_run.model_protocol,
            "provider_message": response.get("native_message"),
            "wire_request_hash": _stable_hash(response["wire_request"]) if response.get("wire_request") else None,
            "wire_request": {**response["wire_request"], "messages": _audit_messages(response["wire_request"]["messages"])} if response.get("wire_request") else None,
        }
        await self._emit_event(EventType.MODEL_CALL_RECORDED, action_run, manifest)

    async def _transition(
        self,
        action_run: ActionRun,
        target: ActionPhase,
        *,
        cause: str,
        facts: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = action_run.machine.transition(target, cause=cause, facts=facts)
        action_run.add_trace("action.state.changed", record)
        run_context = action_run.context.run_context
        if run_context is not None:
            try:
                run_context.action_loop_id = action_run.run_id
                run_context.action_state = {**action_run.machine.snapshot(), "action_loop_id": action_run.run_id}
            except Exception:
                pass
        await self._emit_event(EventType.ACTION_STATE_CHANGED, action_run, record)

    async def _emit_lifecycle(self, name: str, action_run: ActionRun, payload: Dict[str, Any]) -> None:
        event_type = {
            "action.started": EventType.GATEWAY_RUN_STARTED,
            "action.finished": EventType.RESPONSE_SYNTHESIZED,
            "action.failed": EventType.REQUEST_FAILED,
        }[name]
        await self._emit_event(event_type, action_run, {"action": name, **payload})

    async def _emit_event(self, event_type: EventType, action_run: ActionRun, payload: Dict[str, Any]) -> None:
        if self.event_emitter is None:
            return
        context = action_run.context
        run_context = context.run_context
        identity = {
            "action_loop_id": action_run.run_id,
            "action_run_id": action_run.run_id,
            "session_id": context.session_id,
            "user_id": context.user_id,
            "trace_id": getattr(run_context, "trace_id", None),
            "request_id": getattr(run_context, "request_id", None),
            "task_id": getattr(run_context, "task_id", None),
            "task_run_id": getattr(run_context, "task_run_id", None),
            "workflow_run_id": getattr(run_context, "workflow_run_id", None),
            "conversation_turn_id": getattr(run_context, "conversation_turn_id", None),
            "execution_epoch": (getattr(run_context, "execution_token", None) or {}).get("epoch"),
            "attempt_id": (getattr(run_context, "execution_token", None) or {}).get("attempt_id"),
        }
        from gateway.delegation import current_delegation

        delegation = current_delegation()
        if delegation is not None and delegation.depth:
            identity.update(
                parent_action_loop_id=delegation.parent_action_loop_id,
                ancestor_action_loop_ids=list(delegation.ancestor_action_loop_ids),
                delegation_depth=delegation.depth,
            )
        await self.event_emitter.emit(event_type, {**identity, **_json_safe(payload)})

    @staticmethod
    def _observation_messages(
        assistant_content: str,
        observations: List[RuntimeObservation],
        *, model_step_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # Keep the latest bounded projection, not a growing history of gap deltas.
        try:
            action_payload = json.loads(assistant_content)
            if isinstance(action_payload, dict) and "gap_update" in action_payload:
                action_payload.pop("gap_update")
                assistant_content = json.dumps(action_payload, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, TypeError):
            pass
        blocks: List[Dict[str, Any]] = []
        for observation in observations:
            blocks.extend(observation.model_content())
        messages = [{"role": "assistant", "content": assistant_content, "_runtime_action": True}] if assistant_content.strip() else []
        if messages and model_step_id:
            messages[0]["_model_step_id"] = model_step_id
        return [*messages, {"role": "user", "content": blocks, "_runtime_observation": True}]

    @staticmethod
    def _observation_scope(action_run: ActionRun) -> Dict[str, Any]:
        context = action_run.context
        run_context = context.run_context
        return {
            key: value
            for key, value in {
                "user_id": context.user_id,
                "session_id": context.session_id,
                "task_id": getattr(run_context, "task_id", None),
                "task_run_id": getattr(run_context, "task_run_id", None),
                "workflow_run_id": getattr(run_context, "workflow_run_id", None),
                "conversation_turn_id": getattr(run_context, "conversation_turn_id", None),
                "action_loop_id": action_run.run_id,
            }.items()
            if value not in (None, "")
        }

    @staticmethod
    def _merge_usage(total: Dict[str, int], usage: Any) -> None:
        from gateway.model_usage import merge_usage
        merge_usage(total, usage)

    @staticmethod
    def _capability_snapshot_id(action_run: ActionRun) -> Optional[str]:
        snapshot = getattr(action_run.context.run_context, "tool_availability", None)
        return str(snapshot.get("snapshot_id")) if isinstance(snapshot, dict) and snapshot.get("snapshot_id") else None

    @staticmethod
    def _self_model_snapshot_id(action_run: ActionRun) -> Optional[str]:
        snapshot = ActionService._self_model_context(action_run)
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get("snapshot_id") or snapshot.get("model_id")
        return str(value) if value else None

    @staticmethod
    def _self_model_context(action_run: ActionRun) -> Dict[str, Any]:
        snapshot = getattr(action_run.context.run_context, "self_model_context", None)
        return dict(snapshot) if isinstance(snapshot, dict) else {}

    @staticmethod
    def _prompt_block_ids(action_run: ActionRun) -> List[str]:
        blocks = getattr(action_run.context.run_context, "prompt_blocks", None)
        if not isinstance(blocks, dict):
            return []
        return [str(item) for item in (blocks.get("used_block_ids") or [])]

    @staticmethod
    def _prompt_block_hashes(action_run: ActionRun) -> Dict[str, str]:
        blocks = getattr(action_run.context.run_context, "prompt_blocks", None)
        if not isinstance(blocks, dict):
            return {}
        manifest = blocks.get("block_manifest")
        if not isinstance(manifest, dict):
            return {}
        return {
            str(block_id): str(item.get("content_hash"))
            for block_id, item in manifest.items()
            if isinstance(item, dict) and item.get("content_hash")
        }


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _audit_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    projected: List[Dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            projected.append({
                "role": str(message.get("role") or ""),
                **({"name": message["name"]} if message.get("name") else {}),
                "content": _bounded_text(str(content or ""), max_chars=12000),
                "content_hash": _stable_hash(content),
                "original_chars": len(str(content or "")),
                "content_truncated": len(str(content or "")) > 12000,
            })
            continue
        blocks: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "structured")
            if block_type == "text":
                text = str(block.get("text") or "")
                blocks.append({
                    "type": "text",
                    "text": _bounded_text(text, max_chars=12000),
                    "content_hash": _stable_hash(text),
                    "original_chars": len(text),
                    "content_truncated": len(text) > 12000,
                })
            else:
                blocks.append({"type": block_type, "content_hash": _stable_hash(block)})
        projected.append({"role": str(message.get("role") or ""), **({"name": message["name"]} if message.get("name") else {}), "content": blocks})
    return projected


def _audit_observation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    # Retain text facts for paged reads; binary stream blocks are not log replay data.
    out["model_projection"] = [] if out.get("structured_result") is not None else [
        dict(block) for block in payload.get("model_projection", []) if block.get("type") == "text"
    ]
    return out


def _bounded_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump())
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        return _json_safe(as_dict())
    return str(value)
