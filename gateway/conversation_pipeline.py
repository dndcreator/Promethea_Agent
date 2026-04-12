from __future__ import annotations

import inspect
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from .protocol import (
    ConversationRunInput,
    ConversationRunOutput,
    EventType,
    MemoryRecallBundle,
    ModeDecision,
    NormalizedInput,
    PlanResult,
    ResponseDraft,
    ToolExecutionBundle,

)

from .memory_recall_schema import MemoryRecallRequest
from .prompt_assembler import PromptAssembler
from .soul_service import build_soul_response_payload, schedule_soul_evolution
from .runtime_governance import (
    build_context_budget_snapshot,
    build_orchestration_snapshot,
    build_task_graph_snapshot,
)

PROMPT_ASSEMBLER = PromptAssembler()


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off", ""}:
            return False
        return default
    return bool(value)


def _normalize_recall_context(value: Any) -> str:
    """Accept only real text context; reject mock/object stringifications."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_recall_snippet(context: str, *, max_chars: int = 80) -> str:
    text = str(context or "").strip()
    if not text:
        return ""
    lines = [ln.strip("- ").strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("[")]
    if not lines:
        return ""
    snippet = lines[0].replace("\n", " ").strip()
    if len(snippet) > max_chars:
        snippet = snippet[: max(1, int(max_chars) - 3)] + "..."
    return snippet


def _build_memory_visibility(
    *,
    memory_bundle: MemoryRecallBundle,
    feedback_hints: List[Dict[str, Any]],
) -> Dict[str, Any]:
    notices: List[str] = []
    recall_notice = ""
    if memory_bundle.recalled:
        snippet = _extract_recall_snippet(memory_bundle.context)
        if snippet:
            recall_notice = f"我参考了你的历史记忆：{snippet}"
        else:
            recall_notice = "我参考了你的历史记忆来回答。"
        notices.append(recall_notice)

    saved_rows = [row for row in (feedback_hints or []) if str((row or {}).get("type", "")) == "memory_saved"]
    review_rows = [row for row in (feedback_hints or []) if str((row or {}).get("type", "")) == "memory_review_needed"]
    write_notice = ""
    review_notice = ""
    if saved_rows:
        first = saved_rows[-1]
        mt = str(first.get("memory_type") or "记忆")
        write_notice = f"已记住你的一条{mt}信息。"
        notices.append(write_notice)
    if review_rows:
        first = review_rows[-1]
        mt = str(first.get("memory_type") or "记忆")
        review_notice = f"检测到{mt}冲突，待你确认后再写入。"
        notices.append(review_notice)

    return {
        "enabled": bool(memory_bundle.recalled or feedback_hints),
        "recalled": bool(memory_bundle.recalled),
        "recall_notice": recall_notice,
        "write_notice": write_notice,
        "review_notice": review_notice,
        "feedback_hints": list(feedback_hints or []),
        "notices": notices,
    }


def _memory_visibility_enabled(user_config: Optional[Dict[str, Any]]) -> bool:
    cfg = user_config if isinstance(user_config, dict) else {}
    memory_cfg = cfg.get("memory", {}) if isinstance(cfg.get("memory", {}), dict) else {}
    visibility = memory_cfg.get("visibility", {}) if isinstance(memory_cfg.get("visibility", {}), dict) else {}
    value = visibility.get("enabled")
    if value is None:
        return True
    return _to_bool(value, default=True)

def _extract_context_fields(
    run_context: Optional[Any],
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if run_context is not None:
        trace_id = getattr(run_context, "trace_id", None)
        request_id = getattr(run_context, "request_id", None)
        run_session_id = getattr(run_context, "session_id", None)
        run_user_id = getattr(run_context, "user_id", None)
        tenant_id = getattr(run_context, "tenant_id", None)
        environment = getattr(run_context, "environment", None)
        session_state = getattr(run_context, "session_state", None)
        if run_session_id is None and session_state is not None:
            run_session_id = getattr(session_state, "session_id", None)
        if run_user_id is None and session_state is not None:
            run_user_id = getattr(session_state, "user_id", None)
        if tenant_id is None and session_state is not None:
            tenant_id = getattr(session_state, "tenant_id", None)
        if environment is None and session_state is not None:
            environment = getattr(session_state, "environment", None)
        if trace_id is None and session_state is not None:
            trace_id = getattr(session_state, "trace_id", None)
        if trace_id:
            fields["trace_id"] = str(trace_id)
        if request_id:
            fields["request_id"] = str(request_id)
        if run_session_id:
            fields["session_id"] = str(run_session_id)
        if run_user_id:
            fields["user_id"] = str(run_user_id)
        if tenant_id:
            fields["tenant_id"] = str(tenant_id)
        if environment:
            fields["environment"] = str(environment)
    if session_id and "session_id" not in fields:
        fields["session_id"] = str(session_id)
    if user_id and "user_id" not in fields:
        fields["user_id"] = str(user_id)
    return fields


async def _emit_stage_event(
    service: Any,
    *,
    stage: str,
    status: str,
    run_context: Optional[Any],
    session_id: Optional[str],
    user_id: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not service.event_emitter:
        return
    event_map = {
        "started": EventType.CONVERSATION_STAGE_STARTED,
        "finished": EventType.CONVERSATION_STAGE_FINISHED,
        "failed": EventType.CONVERSATION_STAGE_FAILED,
    }
    event_type = event_map.get(status)
    if event_type is None:
        return
    body = {
        "stage": stage,
        "status": status,
        **_extract_context_fields(run_context, session_id=session_id, user_id=user_id),
    }
    if payload:
        body.update(payload)
    await service.event_emitter.emit(event_type, body)


async def stage_input_normalization(service: Any, run_input: ConversationRunInput) -> NormalizedInput:
    session_id = run_input.session_id
    user_id = run_input.user_id
    run_context = run_input.run_context
    if run_context is not None:
        session_id = session_id or getattr(run_context, "session_id", None)
        user_id = user_id or getattr(run_context, "user_id", None)

    user_message = (run_input.user_message or "").strip()
    if not user_message:
        for msg in reversed(run_input.messages or []):
            if str(msg.get("role", "")).lower() == "user":
                user_message = str(msg.get("content", "") or "").strip()
                break
    if not user_message and run_context is not None:
        payload = getattr(run_context, "input_payload", {}) or {}
        user_message = str(payload.get("message") or payload.get("query") or "").strip()

    payload = {}
    if run_context is not None:
        payload = dict(getattr(run_context, "input_payload", {}) or {})

    recent_messages: List[Dict[str, Any]] = []
    if run_input.include_recent and service.message_manager and session_id and user_id:
        recent_messages = service.message_manager.get_recent_messages(session_id, user_id=user_id)

    return NormalizedInput(
        user_message=user_message,
        session_id=session_id,
        user_id=user_id,
        channel=run_input.channel or "web",
        input_payload=payload,
        attachments=payload.get("attachments") or [],
        metadata=payload.get("metadata") or {},
        recent_messages=recent_messages,
    )


async def stage_mode_detection(service: Any, normalized: NormalizedInput) -> ModeDecision:
    text = (normalized.user_message or "").lower()
    if "workflow" in text or "/workflow" in text:
        return ModeDecision(mode="workflow", reason="explicit_workflow", confidence=0.9)
    if len(text) > 160 or "分析" in text or "plan" in text or "step" in text:
        return ModeDecision(mode="deep", reason="complexity_heuristic", confidence=0.75)
    return ModeDecision(mode="fast", reason="default_fast_path", confidence=0.65)


async def stage_memory_recall(
    service: Any,
    *,
    normalized: NormalizedInput,
    run_context: Optional[Any],
    user_config: Optional[Dict[str, Any]],
    mode: ModeDecision,
) -> MemoryRecallBundle:
    if not normalized.user_message or not normalized.session_id or not normalized.user_id:
        return MemoryRecallBundle(recalled=False, reason="missing_identity")
    should_recall = await service._should_recall_memory(
        normalized.user_message,
        user_config=user_config,
        user_id=normalized.user_id,
    )
    if not should_recall or not service.memory_service or not service.memory_service.is_enabled():
        reason = "mode_fast" if mode.mode == "fast" else "not_needed"
        return MemoryRecallBundle(recalled=False, reason=reason)

    req_id = ""
    trace_id = ""
    if run_context is not None:
        req_id = str(getattr(run_context, "request_id", "") or "")
        trace_id = str(getattr(run_context, "trace_id", "") or "")
        if not req_id:
            session_state = getattr(run_context, "session_state", None)
            req_id = str(getattr(session_state, "request_id", "") or "")
        if not trace_id:
            session_state = getattr(run_context, "session_state", None)
            trace_id = str(getattr(session_state, "trace_id", "") or "")

    recall_request = MemoryRecallRequest(
        request_id=req_id or f"recall_{normalized.session_id}",
        trace_id=trace_id or f"trace_{normalized.session_id}",
        session_id=normalized.session_id,
        user_id=normalized.user_id,
        query_text=normalized.user_message,
        mode=mode.mode,
        top_k=8 if mode.mode in {"deep", "workflow"} else 4,
        filters={"channel": normalized.channel},
    )
    context = ""
    recall_memory = getattr(service.memory_service, "recall_memory", None)
    if callable(recall_memory):
        recall_out = recall_memory(
            recall_request,
            run_context=run_context,
        )
        result = await recall_out if inspect.isawaitable(recall_out) else recall_out
        context = _normalize_recall_context(
            getattr(result, "formatted_context", None)
            or (result.get("formatted_context") if isinstance(result, dict) else None)
            or (result if isinstance(result, str) else "")
        )
        if not context:
            get_context = getattr(service.memory_service, "get_context", None)
            if callable(get_context):
                try:
                    fallback_out = get_context(
                        normalized.user_message,
                        normalized.session_id,
                        normalized.user_id,
                    )
                except TypeError:
                    fallback_out = get_context(
                        normalized.user_message,
                        normalized.session_id,
                    )
                raw_fallback = await fallback_out if inspect.isawaitable(fallback_out) else fallback_out
                context = _normalize_recall_context(raw_fallback)
    else:
        get_context = getattr(service.memory_service, "get_context", None)
        if callable(get_context):
            try:
                recall_out = get_context(
                    normalized.user_message,
                    normalized.session_id,
                    normalized.user_id,
                )
            except TypeError:
                recall_out = get_context(
                    normalized.user_message,
                    normalized.session_id,
                )
            raw_context = await recall_out if inspect.isawaitable(recall_out) else recall_out
            context = _normalize_recall_context(raw_context)
    if not context:
        return MemoryRecallBundle(recalled=False, reason="empty_context")
    return MemoryRecallBundle(
        recalled=True,
        context=context,
        reason="memory_recall_policy",
        source="memory_service",
        confidence=0.8,
    )


async def stage_plan_or_reason(
    service: Any,
    *,
    normalized: NormalizedInput,
    run_context: Optional[Any],
    mode: ModeDecision,
    user_config: Optional[Dict[str, Any]],
    base_system_prompt: str,
) -> PlanResult:
    if (
        mode.mode == "fast"
        or not service.reasoning_service
        or not service.reasoning_service.is_enabled(user_id=normalized.user_id)
    ):
        return PlanResult(used_reasoning=False, base_system_prompt=base_system_prompt)

    result = await service.reasoning_service.run(
        session_id=normalized.session_id or "default_session",
        user_id=normalized.user_id or "default_user",
        user_message=normalized.user_message,
        recent_messages=normalized.recent_messages,
        base_system_prompt=base_system_prompt,
        user_config=user_config,
        run_context=run_context,
    )
    workflow_trace = await _attach_plan_workflow_trace(
        service,
        normalized=normalized,
        mode=mode,
        reasoning_result=result if isinstance(result, dict) else {},
        run_context=run_context,
    )
    if workflow_trace and isinstance(result, dict):
        result = dict(result)
        result["workflow_trace"] = workflow_trace
    return PlanResult(
        used_reasoning=bool(result.get("used_reasoning")),
        system_prompt=str(result.get("system_prompt", "") or ""),
        base_system_prompt=base_system_prompt,
        reasoning=result if isinstance(result, dict) else {},
    )


def _normalize_plan_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(raw_steps, list):
        return normalized
    for idx, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"Plan Step {idx + 1}").strip() or f"Plan Step {idx + 1}"
        goal = str(item.get("goal") or title).strip() or title
        normalized.append(
            {
                "title": title,
                "goal": goal,
                "requires_memory": _to_bool(item.get("requires_memory"), default=False),
                "requires_tools": _to_bool(item.get("requires_tools"), default=False),
                "tool_intent": str(item.get("tool_intent") or "").strip(),
                "memory_query": str(item.get("memory_query") or "").strip(),
            }
        )
    return normalized


async def _attach_plan_workflow_trace(
    service: Any,
    *,
    normalized: NormalizedInput,
    mode: ModeDecision,
    reasoning_result: Dict[str, Any],
    run_context: Optional[Any],
) -> Dict[str, Any]:
    if mode.mode not in {"deep", "workflow"}:
        return {}
    if not service.workflow_engine:
        return {}
    if not bool(reasoning_result.get("used_reasoning")):
        return {}

    steps = _normalize_plan_steps(reasoning_result.get("plan_steps"))
    if not steps:
        return {}
    try:
        from .workflow_models import WorkflowDefinition, WorkflowStep

        workflow_id = f"reasoning_plan_{uuid.uuid4().hex}"
        definition_steps: List[WorkflowStep] = []
        for idx, step in enumerate(steps):
            definition_steps.append(
                WorkflowStep(
                    step_id=f"plan_{idx + 1}",
                    step_type="reasoning_step",
                    name=step["title"],
                    description=step["goal"],
                    inputs=step,
                )
            )
        definition = WorkflowDefinition(
            workflow_id=workflow_id,
            workflow_type="linear",
            name=f"Reasoning Plan {workflow_id[-8:]}",
            description="Ephemeral workflow trace generated from reasoning plan steps.",
            owner_user_id=normalized.user_id or "default_user",
            steps=definition_steps,
            policy={
                "source": "reasoning_plan",
                "mode": mode.mode,
                "tree_id": reasoning_result.get("tree_id"),
            },
        )
        service.workflow_engine.define_workflow(definition)
        start_async = getattr(service.workflow_engine, "start_workflow_async", None)
        kwargs = {
            "workflow_id": workflow_id,
            "session_id": normalized.session_id or "default_session",
            "user_id": normalized.user_id or "default_user",
            "workspace_id": normalized.session_id or "default_workspace",
            "run_context": run_context,
            "run_metadata": {
                "source": "reasoning_plan",
                "mode": mode.mode,
                "tree_id": reasoning_result.get("tree_id"),
                "step_count": len(steps),
            },
        }
        if callable(start_async):
            run = await start_async(**kwargs)
        else:
            run = service.workflow_engine.start_workflow(**kwargs)
        return {
            "workflow_id": workflow_id,
            "workflow_run_id": str(getattr(run, "workflow_run_id", "") or ""),
            "step_count": len(steps),
            "source": "reasoning_plan",
        }
    except Exception as e:
        logger.debug("conversation_pipeline: attach plan workflow trace skipped: {}", e)
        return {}


async def stage_tool_execution(
    service: Any,
    *,
    run_input: ConversationRunInput,
    mode: ModeDecision,
) -> ToolExecutionBundle:
    return ToolExecutionBundle(
        enabled=run_input.tool_executor is not None,
        strategy="llm_native" if run_input.tool_executor is not None else "none",
        tool_executor=run_input.tool_executor,
        metadata={"mode": mode.mode},
    )


async def stage_response_synthesis(
    service: Any,
    *,
    normalized: NormalizedInput,
    memory_bundle: MemoryRecallBundle,
    plan: PlanResult,
    tools: ToolExecutionBundle,
    mode: ModeDecision,
    run_input: ConversationRunInput,
    user_config: Optional[Dict[str, Any]],
) -> ResponseDraft:
    org_context: Dict[str, Any] = {}
    if run_input.run_context is not None:
        rs0 = getattr(run_input.run_context, "reasoning_state", None)
        if isinstance(rs0, dict) and isinstance(rs0.get("org_context"), dict):
            org_context = dict(rs0.get("org_context") or {})
    if (
        getattr(service, "org_context_service", None)
        and normalized.user_id
        and isinstance(user_config, dict)
        and not org_context
    ):
        try:
            org_context = await service.org_context_service.recall_for_turn(
                query=normalized.user_message,
                user_id=normalized.user_id,
                user_config=user_config,
                audience=str((normalized.metadata or {}).get("audience") or ""),
                context_type=None,
                top_k=None,
            )
        except Exception as e:
            logger.debug("conversation_pipeline: org context recall skipped: {}", e)
            org_context = {"enabled": True, "recalled": False, "reason": "org_context_error"}

    if run_input.run_context is not None:
        rs = getattr(run_input.run_context, "reasoning_state", None)
        if isinstance(rs, dict):
            rs["org_context"] = dict(org_context or {})
        else:
            try:
                setattr(run_input.run_context, "reasoning_state", {"org_context": dict(org_context or {})})
            except Exception:
                pass

    messages: List[Dict[str, Any]] = []
    if run_input.messages:
        messages = [dict(m) for m in run_input.messages]
        prompt_assembly = {
            "used_block_ids": [],
            "dropped_block_ids": [],
            "compacted": False,
            "source": "prebuilt_messages",
        }
    else:
        assembly = PROMPT_ASSEMBLER.assemble(
            run_context=run_input.run_context,
            mode=mode,
            plan=plan,
            memory_bundle=memory_bundle,
            tools=tools,
            user_config=user_config,
        )
        system_prompt = assembly.get("system_prompt", "")
        prompt_assembly = assembly.get("debug", {})
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(normalized.recent_messages)
        messages.append({"role": "user", "content": normalized.user_message})

    response_data = await service.run_chat_loop(
        messages,
        user_config=user_config,
        session_id=normalized.session_id,
        user_id=normalized.user_id,
        run_context=run_input.run_context,
        tool_executor=tools.tool_executor,
    )
    final_response = response_data if isinstance(response_data, dict) else {"raw": response_data}
    feedback_hints: List[Dict[str, Any]] = []
    if service.memory_service and normalized.session_id and normalized.user_id:
        drain = getattr(service.memory_service, "drain_visibility_hints", None)
        if callable(drain):
            try:
                hint_out = drain(
                    session_id=normalized.session_id,
                    user_id=normalized.user_id,
                    limit=3,
                )
                feedback_hints = list(hint_out or [])
            except Exception:
                feedback_hints = []
    memory_visibility = _build_memory_visibility(memory_bundle=memory_bundle, feedback_hints=feedback_hints)
    if _memory_visibility_enabled(user_config):
        final_response["memory_visibility"] = memory_visibility
    else:
        final_response["memory_visibility"] = {"enabled": False, "notices": []}
    final_response.setdefault("prompt_assembly", prompt_assembly)
    final_response["soul"] = build_soul_response_payload(user_config)
    final_response["org_context"] = {
        "enabled": bool((org_context or {}).get("enabled")),
        "recalled": bool((org_context or {}).get("recalled")),
        "org_id": str((org_context or {}).get("org_id") or ""),
        "audience": str((org_context or {}).get("audience") or ""),
        "backend": str((org_context or {}).get("backend") or ""),
        "items": list((org_context or {}).get("items") or []),
    }
    return ResponseDraft(
        status=str(final_response.get("status", "success") or "success"),
        content=str(final_response.get("content", "") or ""),
        messages=messages,
        response_data=final_response,
    )


async def run_staged_pipeline(service: Any, run_input: ConversationRunInput) -> ConversationRunOutput:
    stages = [
        "input_normalization",
        "mode_detection",
        "memory_recall",
        "planning_reasoning",
        "tool_execution",
        "response_synthesis",
    ]
    state: Dict[str, Any] = {"stages": [], "stage_status": {}}
    current_stage: Optional[str] = None
    run_context = run_input.run_context
    session_id = run_input.session_id
    user_id = run_input.user_id

    try:
        current_stage = stages[0]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        normalized = await stage_input_normalization(service, run_input)
        session_id = normalized.session_id
        user_id = normalized.user_id
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"user_message_length": len(normalized.user_message)},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok"}

        user_config = run_input.user_config
        if user_config is None and service.config_service and user_id:
            user_config = service.config_service.get_merged_config(user_id)
        base_system_prompt, config_user = await service._get_user_prompt_and_config(
            user_id or "default_user",
            normalized.channel,
        )
        if user_config is None:
            user_config = config_user

        current_stage = stages[1]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        mode = await stage_mode_detection(service, normalized)
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"mode": mode.mode, "reason": mode.reason},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok", "mode": mode.mode}

        current_stage = stages[2]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        memory_bundle = await stage_memory_recall(
            service,
            normalized=normalized,
            run_context=run_context,
            user_config=user_config,
            mode=mode,
        )
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"recalled": memory_bundle.recalled},
        )
        state["stages"].append(current_stage)
        memory_stage_status = "ok" if memory_bundle.recalled else "skipped"
        if (not memory_bundle.recalled) and str(memory_bundle.reason or "") not in {"mode_fast", "not_needed", "missing_identity"}:
            memory_stage_status = "degraded"
        state["stage_status"][current_stage] = {
            "status": memory_stage_status,
            "reason_code": str(memory_bundle.reason or ""),
            "recalled": bool(memory_bundle.recalled),
        }

        current_stage = stages[3]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        plan = await stage_plan_or_reason(
            service,
            normalized=normalized,
            run_context=run_context,
            mode=mode,
            user_config=user_config,
            base_system_prompt=base_system_prompt,
        )
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"used_reasoning": plan.used_reasoning},
        )
        state["stages"].append(current_stage)
        plan_stage_status = "ok" if plan.used_reasoning else ("skipped" if mode.mode == "fast" else "degraded")
        state["stage_status"][current_stage] = {
            "status": plan_stage_status,
            "used_reasoning": bool(plan.used_reasoning),
            "reason_code": "reasoning_disabled_or_unavailable" if plan_stage_status == "degraded" else "",
        }

        current_stage = stages[4]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        tools = await stage_tool_execution(service, run_input=run_input, mode=mode)
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"enabled": tools.enabled},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {
            "status": "ok" if tools.enabled else "skipped",
            "enabled": bool(tools.enabled),
        }

        current_stage = stages[5]
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="started",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
        )
        response = await stage_response_synthesis(
            service,
            normalized=normalized,
            memory_bundle=memory_bundle,
            plan=plan,
            tools=tools,
            mode=mode,
            run_input=run_input,
            user_config=user_config,
        )
        await schedule_soul_evolution(
            service=service,
            user_id=normalized.user_id,
            user_config=user_config,
            user_message=normalized.user_message,
            assistant_message=response.content,
        )
        await _emit_stage_event(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"status": response.status},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok", "response_status": response.status}

        raw = dict(response.response_data)
        degraded_stages = [
            stage_name
            for stage_name, info in (state.get("stage_status") or {}).items()
            if isinstance(info, dict) and str(info.get("status") or "") == "degraded"
        ]
        capability_state = {
            "memory": state["stage_status"].get("memory_recall", {}),
            "reasoning": state["stage_status"].get("planning_reasoning", {}),
            "tools": state["stage_status"].get("tool_execution", {}),
            "workflow_trace_attached": bool(isinstance(plan.reasoning, dict) and plan.reasoning.get("workflow_trace")),
            "degraded": bool(degraded_stages),
            "degraded_stages": degraded_stages,
        }
        workflow_trace = (
            plan.reasoning.get("workflow_trace")
            if isinstance(plan.reasoning, dict)
            else None
        )
        task_graph = build_task_graph_snapshot(
            stage_status=state.get("stage_status", {}),
            mode=mode.mode,
            response_status=response.status,
            workflow_trace=workflow_trace if isinstance(workflow_trace, dict) else None,
        )
        context_budget = build_context_budget_snapshot(
            raw.get("prompt_assembly", {}) if isinstance(raw.get("prompt_assembly"), dict) else {}
        )
        orchestration = build_orchestration_snapshot(
            mode=mode.mode,
            used_reasoning=bool(plan.used_reasoning),
            workflow_trace=workflow_trace if isinstance(workflow_trace, dict) else None,
            reasoning=plan.reasoning if isinstance(plan.reasoning, dict) else None,
        )
        raw.setdefault("pipeline", state)
        raw.setdefault("mode", mode.mode)
        raw.setdefault("memory_recalled", memory_bundle.recalled)
        raw.setdefault("used_reasoning", plan.used_reasoning)
        raw.setdefault("capability_state", capability_state)
        raw.setdefault("task_graph", task_graph)
        raw.setdefault("context_budget", context_budget)
        raw.setdefault("orchestration", orchestration)
        if isinstance(plan.reasoning, dict) and plan.reasoning.get("workflow_trace"):
            raw.setdefault("workflow_trace", plan.reasoning.get("workflow_trace"))
        return ConversationRunOutput(
            status=response.status,
            content=response.content,
            tool_call_id=raw.get("tool_call_id"),
            tool_name=raw.get("tool_name"),
            args=raw.get("args") if isinstance(raw.get("args"), dict) else None,
            raw=raw,
        )
    except Exception as e:
        failed_stage = current_stage or stages[min(len(state["stages"]), len(stages) - 1)]
        await _emit_stage_event(
            service,
            stage=failed_stage,
            status="failed",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"error": str(e)},
        )
        raise




