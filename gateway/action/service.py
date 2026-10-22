from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from agentkit.mcp.tool_result import ToolErrorInfo, ToolExecutionResult, failed_tool_result, normalize_tool_result
from agentkit.security.approval import approval_scope
from gateway.events import EventEmitter
from gateway.protocol import EventType
from config import GoalGapConfig
from gateway.goal_gaps import GoalGapState, apply_gap_delta, gap_event_delta, gap_outcome, gap_projection, observe_gap_step

from .model_action import AnswerDeltaProjector, InvalidModelAction, ModelAction, ToolCallProposal, parse_model_action
from .models import ActionContext, ActionResult, ActionRun
from .observation import RuntimeObservation
from .state_machine import ActionPhase
from .state_machine import RuntimeActionStateMachine
from .checkpoint import capture as capture_checkpoint, restore as restore_checkpoint


CapabilityInspector = Callable[[List[str]], Awaitable[Dict[str, Any]]]
CapabilityResolver = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
OutputSink = Callable[[str], Awaitable[None]]
ReasoningSink = Callable[[Dict[str, Any]], Awaitable[None]]


class ModelResponseError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_REQUEST_FAILED", usage: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.usage = usage


class ActionService:
    """Runtime-owned model/action/observation control loop."""

    def __init__(self, *, event_emitter: Optional[EventEmitter] = None, conversation_core: Any, task_service: Optional[Any] = None, capability_service: Optional[Any] = None) -> None:
        self.event_emitter = event_emitter
        self.conversation_core = conversation_core
        self.task_service = task_service
        self.capability_service = capability_service

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
        metadata: Optional[Dict[str, Any]] = None,
        approved_call_ids: Optional[set[str]] = None,
        output_sink: Optional[OutputSink] = None,
        reasoning_sink: Optional[ReasoningSink] = None,
        prepare_messages: Optional[Callable] = None,
        checkpoint_sink: Optional[Callable] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
            ),
            budget=budget,
            approved_call_ids=set(approved_call_ids or ()),
        )
        if checkpoint:
            if checkpoint.get("result"):
                return dict(checkpoint["result"])
            action_run = restore_checkpoint(checkpoint, action_run.context)
        self._load_goal_gaps(action_run)
        restored_messages = None
        if checkpoint:
            restored_messages = list(action_run.messages)
            pending = checkpoint.get("pending_calls") or []
            if pending:
                calls = [ToolCallProposal(tool_name=row["tool_name"], arguments=dict(row["arguments"]), call_id=row["call_id"]) for row in pending]
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
            ),
            budget=int(pending.get("budget") or 5),
            run_id=str(pending.get("action_run_id") or pending.get("action_loop_id") or f"act_{uuid.uuid4().hex}"),
            status="running",
            trace=[dict(item) for item in (pending.get("action_trace") or [])],
            machine=machine,
            step=int(pending.get("step") or 1),
            observations=[dict(item) for item in (pending.get("observations") or [])],
            execution_path=[dict(item) for item in (pending.get("execution_path") or [])],
            reasoning_steps=[dict(item) for item in (pending.get("reasoning_steps") or [])],
            approved_call_ids=set(pending.get("approved_call_ids") or ()) | {str(approved_call_id)},
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
            ),
            budget=int(pending.get("budget") or 5),
            run_id=str(pending.get("action_run_id") or pending.get("action_loop_id") or f"act_{uuid.uuid4().hex}"),
            status="running",
            trace=[dict(item) for item in (pending.get("action_trace") or [])],
            machine=machine,
            step=int(pending.get("step") or 1),
            observations=[dict(item) for item in (pending.get("observations") or [])],
            execution_path=[dict(item) for item in (pending.get("execution_path") or [])],
            reasoning_steps=[dict(item) for item in (pending.get("reasoning_steps") or [])],
            approved_call_ids=set(pending.get("approved_call_ids") or ()),
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
        messages.extend(self._observation_messages(str(pending.get("content") or ""), observations))
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
        budget = max(1, int(action_run.budget or 5))
        messages = list(resume_messages) if resume_messages is not None else list(action_run.messages)
        usage = dict(resume_usage or {"prompt_tokens": 0, "completion_tokens": 0})
        action_run.status = "running"
        if resume_messages is None:
            action_run.add_trace("action.started", {"goal": action_run.goal, "budget": budget})
            await self._emit_lifecycle("action.started", action_run, {"goal": action_run.goal, "budget": budget})
            await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="loop_started")

        try:
            while resumed_action is not None or action_run.step < budget:
                self._assert_task_execution(action_run)
                await self._checkpoint(action_run, messages, usage)
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
                        if exc.code not in {"MODEL_EMPTY_RESPONSE", "MODEL_OUTPUT_LIMIT"}:
                            raise
                        self._merge_usage(usage, exc.usage)
                        await self._observe_outcome(
                            action_run, messages, model_step_id=model_step_id,
                            result=ToolExecutionResult(
                                tool_name="runtime.model_response", ok=False,
                                error=ToolErrorInfo(
                                    code=exc.code, message=str(exc), category="model_output",
                                    retryable=True,
                                    advice="Return one concise, complete runtime action; split large work into smaller actions. No partial action was executed.",
                                ),
                            ),
                        )
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
                    except InvalidModelAction as exc:
                        await self._observe_outcome(
                            action_run, messages, model_step_id=model_step_id,
                            result=ToolExecutionResult(
                                tool_name="runtime.model_action", ok=False,
                                error=ToolErrorInfo(
                                    code="INVALID_MODEL_ACTION", message=str(exc), category="validation",
                                    retryable=True,
                                    advice="The proposed action was not executed. Return one valid JSON runtime action, using only supplied evidence and procedure references.",
                                ),
                            ),
                        )
                        continue

                self._assert_task_execution(action_run)
                if "gap_update" in action.raw:
                    await self._apply_goal_delta(action_run, action.raw["gap_update"])

                if action.kind == "answer":
                    return await self._complete_answer(
                        action_run,
                        action=action,
                        usage=usage,
                        started=started,
                        model_step_id=model_step_id,
                        messages=messages,
                    )

                if action.kind == "capability_inspect":
                    await self._transition(
                        action_run,
                        ActionPhase.VALIDATING,
                        cause="capability_inspection_proposed",
                        facts={"model_step_id": model_step_id, "names": action.capability_names},
                    )
                    await self._transition(action_run, ActionPhase.EXECUTING, cause="capability_inspection_started")
                    result = await self._capability_outcome(
                        "runtime.capability_inspect", capability_inspector, action.capability_names,
                    )
                    await self._observe_outcome(
                        action_run, messages, model_step_id=model_step_id,
                        result=result, assistant_content=content,
                    )
                    continue

                if action.kind == "capability_request":
                    if action.capability_request is None:
                        raise RuntimeError("capability resolution is unavailable")
                    request = {
                        "objective": action.capability_request.objective,
                        "required_capabilities": list(action.capability_request.required_capabilities),
                        "preferred_modalities": list(action.capability_request.preferred_modalities),
                        "max_side_effect": action.capability_request.max_side_effect,
                    }
                    await self._transition(
                        action_run,
                        ActionPhase.VALIDATING,
                        cause="capability_resolution_proposed",
                        facts={"model_step_id": model_step_id, "request": request},
                    )
                    await self._transition(action_run, ActionPhase.EXECUTING, cause="capability_resolution_started")
                    result = await self._capability_outcome(
                        "runtime.capability_resolve", capability_resolver, request,
                    )
                    projection = result.value if isinstance(result.value, dict) else {}
                    action_run.execution_path.append(
                        {
                            "kind": "capability_request",
                            **request,
                            "exposed_procedures": [
                                item["reference"] for item in projection.get("process_experience", {}).get("rules", [])
                            ],
                            "candidate_names": [
                                str(item.get("name") or "")
                                for item in (projection.get("candidates") or [])
                                if isinstance(item, dict) and str(item.get("name") or "").strip()
                            ],
                        }
                    )
                    await self._observe_outcome(
                        action_run, messages, model_step_id=model_step_id,
                        result=result, assistant_content=content,
                    )
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
                if isinstance(pending, ActionResult):
                    pending.usage = dict(usage)
                    return pending
                if preparation_error is None and tool_executor is None:
                    preparation_error = ToolErrorInfo(
                        code="TOOL_EXECUTOR_UNAVAILABLE", message="Runtime tool execution is unavailable; no calls were executed.",
                        category="capability", retryable=False,
                    )
                if preparation_error is not None:
                    results = [ToolExecutionResult(tool_name=call.tool_name, ok=False, error=preparation_error) for call in action.calls]
                else:
                    await self._transition(
                        action_run,
                        ActionPhase.EXECUTING,
                        cause="tool_batch_started",
                        facts={"model_step_id": model_step_id, "call_count": len(action.calls)},
                    )
                    await self._checkpoint(action_run, messages, usage, pending_calls=[{
                        "tool_name": call.tool_name, "arguments": call.arguments, "call_id": call.call_id,
                    } for call in action.calls])
                    results = await self._execute_batch(action_run, action, tool_executor, model_step_id=model_step_id)
                from gateway.delegation import take_delegated_usage

                self._merge_usage(usage, take_delegated_usage())
                observations = await self._record_tool_results(
                    action_run, action, results, model_step_id=model_step_id,
                    started_ids={call.call_id for call in action.calls} if preparation_error is None else set(),
                )
                messages.extend(self._observation_messages(content, observations))
                await self._transition(action_run, ActionPhase.AWAITING_MODEL, cause="observation_committed")

            return await self._finish_budget_exhausted(
                action_run,
                messages,
                usage,
                started,
                output_sink=output_sink,
                reasoning_sink=reasoning_sink,
            )
        except asyncio.CancelledError:
            if action_run.machine.phase not in {ActionPhase.FAILED, ActionPhase.CANCELLED, ActionPhase.COMPLETED}:
                await self._transition(action_run, ActionPhase.CANCELLED, cause="runtime_task_cancelled")
            action_run.status = "cancelled"
            action_run.ended_at = time.time()
            raise
        except Exception as exc:
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
                usage=usage if any(usage.values()) else None,
            )

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
        for call in action.calls:
            if call.call_id in action_run.approved_call_ids:
                continue
            requires_confirmation = False
            if confirmation_resolver is not None:
                try:
                    requires_confirmation = confirmation_resolver(call.tool_name, call.arguments)
                    if inspect.isawaitable(requires_confirmation):
                        requires_confirmation = await requires_confirmation
                except Exception as exc:
                    return ToolErrorInfo(
                        code="TOOL_AUTHORIZATION_UNAVAILABLE", message=str(exc) or type(exc).__name__,
                        category="policy", retryable=False,
                        advice="This batch was not executed. Authorization could not be established; do not bypass it.",
                        details={"tool_name": call.tool_name},
                    )
            if not requires_confirmation:
                continue
            await self._transition(
                action_run,
                ActionPhase.WAITING_CONFIRMATION,
                cause="confirmation_required",
                facts={"model_step_id": model_step_id, "tool_call_id": call.call_id, "tool_name": call.tool_name},
            )
            action_run.status = "needs_confirmation"
            raw_calls = [
                {"id": item.call_id, "name": item.tool_name, "args": dict(item.arguments)}
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
                "procedure_refs": list(action.raw.get("procedure_refs", [])),
                "content": assistant_content,
                "model_step_id": model_step_id,
                "step": action_run.step,
                "budget": action_run.budget,
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
                **self._gap_result(action_run),
                "action_state": action_run.machine.snapshot(),
                "action_state_transitions": list(action_run.machine.transitions),
            }
            return ActionResult(
                status="needs_confirmation",
                content=assistant_content,
                raw=raw,
                run_id=action_run.run_id,
                trace=list(action_run.trace),
            )
        return None

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

    async def _apply_goal_delta(self, action_run: ActionRun, raw: Any) -> None:
        policy = self._gap_policy(action_run)
        if not policy.enabled:
            return
        try:
            state = apply_gap_delta(action_run.gap_state, raw, action_run.observations, max_gaps=policy.max_gaps, max_updates=policy.max_updates, loop_id=action_run.run_id)
        except (ValueError, TypeError) as exc:
            action_run.gap_feedback = str(exc)[:200]
            action_run.add_trace("goal.gaps.rejected", {"reason": action_run.gap_feedback})
            return
        if state.revision != action_run.gap_state.revision:
            action_run.gap_feedback = ""
            await self._save_goal_gaps(action_run, state)

    def _gap_view(self, action_run: ActionRun) -> Dict[str, Any]:
        policy = self._gap_policy(action_run)
        return gap_projection(action_run.gap_state, context_chars=policy.context_chars, window=policy.window,
                              feedback=action_run.gap_feedback, observations=action_run.observations)

    def _with_goal_projection(self, action_run: ActionRun, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._gap_policy(action_run).enabled:
            return messages
        view = self._gap_view(action_run)
        if not (action_run.gap_state.gaps or action_run.gap_feedback or view.get("recent_obstacles")):
            return messages
        context = "Runtime goal gaps (authoritative revision; interpretations may be provisional):\n" + json.dumps(view, ensure_ascii=False, separators=(",", ":"))
        result = [dict(item) for item in messages]
        for message in result:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                message["content"] += "\n\n" + context
                break
        else:
            result.insert(0, {"role": "system", "content": context})
        return result

    @staticmethod
    def _gap_result(action_run: ActionRun) -> Dict[str, Any]:
        if not action_run.gap_state.gaps:
            return {}
        return {"goal_gaps": action_run.gap_state.model_dump(), "goal_progress": gap_outcome(action_run.gap_state)}

    async def _record_tool_results(self, action_run: ActionRun, action: ModelAction, results: List[ToolExecutionResult], *, model_step_id: str, started_ids: set[str]) -> List[RuntimeObservation]:
        observations = [RuntimeObservation.from_result(
            action_loop_id=action_run.run_id, model_step_id=model_step_id,
            tool_call_id=call.call_id, tool_name=call.tool_name, result=result,
            capability_snapshot_id=self._capability_snapshot_id(action_run), scope=self._observation_scope(action_run),
        ) for call, result in zip(action.calls, results)]
        for call, result, observation in zip(action.calls, results, observations):
            action_run.execution_path.append({
                "kind": "tool_call", "tool_call_id": call.call_id, "tool_name": call.tool_name,
                "args": dict(call.arguments), "ok": bool(result.ok), "observation_id": observation.observation_id,
                "executed": call.call_id in started_ids, "requires_confirmation": call.call_id in action_run.approved_call_ids,
                "procedure_refs": list(action.raw.get("procedure_refs", [])),
            })
        action_run.approved_call_ids.difference_update(call.call_id for call in action.calls)
        await self._commit_observations(action_run, observations)
        return observations

    async def _execute_batch(self, action_run: ActionRun, action: ModelAction, executor: Any, *, model_step_id: str) -> List[ToolExecutionResult]:
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
                    spec = registry.resolve_for_call(tool_name=call.tool_name, params=call.arguments) if registry is not None else None
                    parallel = bool(spec is not None and spec.concurrency_safe)
                    if running and (not parallel or len(running) >= policy.max_parallel_tool_calls):
                        await settle(all_pending=not parallel)
                        continue
                    break
                self._assert_task_execution(action_run)
                task = asyncio.create_task(self._execute_call(executor, call, call.call_id in action_run.approved_call_ids, action_run=action_run))
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

    async def _execute_call(self, executor: Any, call: ToolCallProposal, approved: bool, *, action_run: ActionRun) -> ToolExecutionResult:
        self._assert_task_execution(action_run)
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
        messages.extend(self._observation_messages(assistant_content, [observation]))
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
    ) -> ActionResult:
        self._assert_task_execution(action_run)
        self._validate_answer_evidence(action_run, action)
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
            "evidence_refs": list(action.evidence_refs),
            **self._gap_result(action_run),
            "action_state": action_run.machine.snapshot(),
            "action_state_transitions": list(action_run.machine.transitions),
        }
        return ActionResult(
            status="success",
            content=action.content,
            raw=raw,
            run_id=action_run.run_id,
            trace=list(action_run.trace),
            usage=usage if any(usage.values()) else None,
        )

    async def _finish_budget_exhausted(
        self,
        action_run: ActionRun,
        messages: List[Dict[str, Any]],
        usage: Dict[str, int],
        started: float,
        *,
        output_sink: Optional[OutputSink],
        reasoning_sink: Optional[ReasoningSink],
    ) -> ActionResult:
        self._assert_task_execution(action_run)
        await self._observe_outcome(
            action_run, messages, model_step_id=f"step_{uuid.uuid4().hex}",
            result=ToolExecutionResult(
                tool_name="runtime.action_budget", ok=False,
                error=ToolErrorInfo(
                    code="ACTION_BUDGET_EXHAUSTED", message="The action budget is exhausted; no further tools may execute in this turn.",
                    category="budget", retryable=False,
                    advice="Give the user a concise answer explaining the verified results and remaining obstacles; do not claim unfinished work succeeded.",
                ),
            ),
        )
        messages.append({
            "role": "user",
            "content": (
                "The runtime action budget is exhausted. Return an action=answer JSON object based only on committed "
                "observations. Do not propose another runtime action."
            ),
        })
        model_step_id = f"step_{uuid.uuid4().hex}"
        response = await self._call_model(
            action_run,
            messages,
            model_step_id,
            output_sink=output_sink,
            reasoning_sink=reasoning_sink,
        )
        self._merge_usage(usage, response.get("usage"))
        await self._transition(action_run, ActionPhase.EVALUATING, cause="budget_final_response_received")
        action = parse_model_action(str(response.get("content") or ""))
        if action.kind != "answer":
            raise InvalidModelAction("model proposed a non-answer after the runtime budget was exhausted")
        if "gap_update" in action.raw:
            await self._apply_goal_delta(action_run, action.raw["gap_update"])
        return await self._complete_answer(
            action_run,
            action=action,
            usage=usage,
            started=started,
            model_step_id=model_step_id,
            messages=messages,
        )

    async def _call_model(
        self,
        action_run: ActionRun,
        messages: List[Dict[str, Any]],
        model_step_id: str,
        *,
        output_sink: Optional[OutputSink],
        reasoning_sink: Optional[ReasoningSink],
    ) -> Dict[str, Any]:
        if action_run.context.prepare_messages is not None:
            messages = await action_run.context.prepare_messages(messages, action_run.observations)
        messages = self._with_goal_projection(action_run, messages)
        streamer = getattr(self.conversation_core, "call_llm_stream", None)
        if output_sink is not None and callable(streamer):
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
                user_config=action_run.context.user_config,
                user_id=action_run.context.user_id,
                reasoning_sink=publish_reasoning,
                result_sink=publish_result,
            ):
                text = str(chunk or "")
                if text.startswith("[error]"):
                    raw = {"status": "error", "error": text.removeprefix("[error]").strip(), "content": "".join(chunks)}
                    break
                chunks.append(text)
                delta = projector.feed(text)
                if delta:
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
                user_config=action_run.context.user_config,
                user_id=action_run.context.user_id,
            )
            raw = response if isinstance(response, dict) else {"content": str(response or "")}
            source = "runtime"
        if str(raw.get("status") or "success").lower() in {"success", "ok", "completed"} and not str(raw.get("content") or "").strip():
            raw = {**raw, "status": "error", "code": "MODEL_EMPTY_RESPONSE", "error": "Model returned no action or answer."}
        await self._record_model_call(
            action_run,
            messages=messages,
            model_step_id=model_step_id,
            response=raw,
            source=source,
        )
        status = str(raw.get("status") or "success").strip().lower()
        if status not in {"success", "ok", "completed"}:
            detail = str(raw.get("error") or raw.get("content") or "model provider request failed")
            raise ModelResponseError(detail, code=str(raw.get("code") or "MODEL_REQUEST_FAILED"), usage=raw.get("usage"))
        return raw

    async def _record_model_call(
        self,
        action_run: ActionRun,
        *,
        messages: List[Dict[str, Any]],
        model_step_id: str,
        response: Dict[str, Any],
        source: str,
    ) -> None:
        self_model_context = self._self_model_context(action_run)
        manifest = {
            "model_call_id": f"model_{uuid.uuid4().hex}",
            "model_step_id": model_step_id,
            "provider_request_id": str(response.get("request_id")) if response.get("request_id") else None,
            "action_loop_id": action_run.run_id,
            "source": source,
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
            "provider_error_code": response.get("code"),
            "finish_reason": response.get("finish_reason"),
            "usage": response.get("usage"),
            "max_tokens": response.get("max_tokens"),
            "reasoning_chars": response.get("reasoning_chars"),
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
        messages = [{"role": "assistant", "content": assistant_content}] if assistant_content.strip() else []
        return [*messages, {"role": "user", "content": blocks}]

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
        if not isinstance(usage, dict):
            return
        total["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        total["completion_tokens"] += int(usage.get("completion_tokens") or 0)

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
                "content": _bounded_text(str(content or ""), max_chars=12000),
                "content_hash": _stable_hash(content),
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
                })
            else:
                blocks.append({"type": block_type, "content_hash": _stable_hash(block)})
        projected.append({"role": str(message.get("role") or ""), "content": blocks})
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
