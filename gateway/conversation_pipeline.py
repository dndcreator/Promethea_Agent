from __future__ import annotations

from typing import Any, Dict, List, Optional

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

PROMPT_ASSEMBLER = PromptAssembler()

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
        session_state = getattr(run_context, "session_state", None)
        if run_session_id is None and session_state is not None:
            run_session_id = getattr(session_state, "session_id", None)
        if run_user_id is None and session_state is not None:
            run_user_id = getattr(session_state, "user_id", None)
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
    result = await service.memory_service.recall_memory(
        recall_request,
        run_context=run_context,
    )
    context = result.formatted_context or ""
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
    return PlanResult(
        used_reasoning=bool(result.get("used_reasoning")),
        system_prompt=str(result.get("system_prompt", "") or ""),
        base_system_prompt=base_system_prompt,
        reasoning=result if isinstance(result, dict) else {},
    )


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
    final_response.setdefault("prompt_assembly", prompt_assembly)
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
    state: Dict[str, Any] = {"stages": []}
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

        raw = dict(response.response_data)
        raw.setdefault("pipeline", state)
        raw.setdefault("mode", mode.mode)
        raw.setdefault("memory_recalled", memory_bundle.recalled)
        raw.setdefault("used_reasoning", plan.used_reasoning)
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




