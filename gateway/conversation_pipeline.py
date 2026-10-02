from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from loguru import logger

from .action.models import resolve_action_budget
from .memory_visibility import build_memory_visibility
from .prompt_assembler import PromptAssembler
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
from .runtime_context import build_runtime_context_block
from .runtime_governance import (
    build_context_budget_snapshot,
    build_orchestration_snapshot,
    build_task_graph_snapshot,
)
from .runtime_input_builder import build_runtime_input_blocks
from .runtime_io import blocks_debug
from .soul_service import build_soul_response_payload, schedule_soul_evolution
from .capability_service import ToolInvocationContext


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


def _memory_visibility_enabled(user_config: Optional[Dict[str, Any]]) -> bool:
    cfg = user_config if isinstance(user_config, dict) else {}
    memory_cfg = cfg.get("memory", {}) if isinstance(cfg.get("memory"), dict) else {}
    visibility = memory_cfg.get("visibility", {}) if isinstance(memory_cfg.get("visibility"), dict) else {}
    return _to_bool(visibility.get("enabled"), default=True)


def _context_fields(
    run_context: Optional[Any],
    *,
    session_id: Optional[str],
    user_id: Optional[str],
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    for name in ("trace_id", "request_id", "task_id", "run_id", "tenant_id", "environment"):
        value = getattr(run_context, name, None) if run_context is not None else None
        if value:
            fields[name] = str(value)
    resolved_session = getattr(run_context, "session_id", None) if run_context is not None else None
    resolved_user = getattr(run_context, "user_id", None) if run_context is not None else None
    if resolved_session or session_id:
        fields["session_id"] = str(resolved_session or session_id)
    if resolved_user or user_id:
        fields["user_id"] = str(resolved_user or user_id)
    return fields


async def _emit_stage(
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
    event_type = {
        "started": EventType.CONVERSATION_STAGE_STARTED,
        "finished": EventType.CONVERSATION_STAGE_FINISHED,
        "failed": EventType.CONVERSATION_STAGE_FAILED,
    }.get(status)
    if event_type is None:
        return
    await service.event_emitter.emit(
        event_type,
        {
            "stage": stage,
            "status": status,
            **_context_fields(run_context, session_id=session_id, user_id=user_id),
            **dict(payload or {}),
        },
    )


async def stage_input_normalization(service: Any, run_input: ConversationRunInput) -> NormalizedInput:
    session_id = run_input.session_id or getattr(run_input.run_context, "session_id", None)
    user_id = run_input.user_id or getattr(run_input.run_context, "user_id", None)
    user_message = str(run_input.user_message or "").strip()
    if not user_message:
        for message in reversed(run_input.messages or []):
            if str(message.get("role") or "").lower() == "user":
                content = message.get("content")
                if isinstance(content, str):
                    user_message = content.strip()
                break

    payload = dict(getattr(run_input.run_context, "input_payload", {}) or {})
    if not user_message:
        user_message = str(payload.get("message") or payload.get("query") or "").strip()

    recent_messages: List[Dict[str, Any]] = []
    if run_input.include_recent and service.message_manager and session_id and user_id and not run_input.messages:
        recent_messages = service.message_manager.get_recent_messages(session_id, user_id=user_id)

    attachments = list(run_input.attachments or payload.get("attachments") or [])
    runtime_blocks = list(run_input.runtime_blocks or [])
    if isinstance(payload.get("runtime_blocks"), list):
        runtime_blocks.extend(payload["runtime_blocks"])
    return NormalizedInput(
        user_message=user_message,
        session_id=session_id,
        user_id=user_id,
        channel=run_input.channel or "web",
        input_payload=payload,
        attachments=attachments,
        runtime_blocks=runtime_blocks,
        metadata=dict(payload.get("metadata") or {}),
        recent_messages=recent_messages,
    )


def _default_tool_executor(
    service: Any,
    *,
    normalized: NormalizedInput,
    run_context: Any,
    user_config: Optional[Dict[str, Any]],
):
    if service.capability_service is None:
        return None

    async def execute(tool_name: str, args: Dict[str, Any]) -> Any:
        context = ToolInvocationContext(
            session_id=normalized.session_id,
            user_id=normalized.user_id,
            source="conversation",
            metadata={"run_context": run_context, "user_config": user_config},
        )
        return await service.capability_service.call_tool(
            tool_name=tool_name,
            params=args,
            ctx=context,
            run_context=run_context,
            user_config=user_config,
        )

    return execute


async def stage_capability_discovery(
    service: Any,
    *,
    run_input: ConversationRunInput,
    normalized: NormalizedInput,
    run_context: Any,
    user_config: Optional[Dict[str, Any]],
) -> ToolExecutionBundle:
    action_budget = resolve_action_budget(user_config)
    catalog = list(getattr(run_context, "registered_tools", []) or [])
    if not catalog:
        catalog = await service.prepare_runtime_capabilities(
            user_config=user_config,
            run_context=run_context,
        )
    executor = run_input.tool_executor or _default_tool_executor(
        service,
        normalized=normalized,
        run_context=run_context,
        user_config=user_config,
    )
    return ToolExecutionBundle(
        enabled=bool(executor and any(item.get("callable_now") for item in catalog)),
        strategy="main_model_control_loop",
        tool_executor=executor,
        metadata={
            "tool_budget": action_budget,
            "registered_tools": catalog,
            "decision_owner": "main_model",
        },
    )


async def _attach_org_context(
    service: Any,
    *,
    normalized: NormalizedInput,
    run_context: Any,
    user_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    existing_state = getattr(run_context, "reasoning_state", None)
    if isinstance(existing_state, dict) and isinstance(existing_state.get("org_context"), dict):
        return dict(existing_state["org_context"])
    if service.org_context_service is None or not isinstance(user_config, dict) or not normalized.user_id:
        return {}
    try:
        org_context = await service.org_context_service.recall_for_turn(
            query=normalized.user_message,
            user_id=normalized.user_id,
            user_config=user_config,
            audience=str((normalized.metadata or {}).get("audience") or ""),
            context_type=None,
            top_k=None,
        )
    except Exception as exc:
        logger.debug("Conversation pipeline: org context unavailable: {}", exc)
        org_context = {"enabled": True, "recalled": False, "reason": "org_context_error"}
    reasoning_state = getattr(run_context, "reasoning_state", None)
    if not isinstance(reasoning_state, dict):
        reasoning_state = {}
        setattr(run_context, "reasoning_state", reasoning_state)
    reasoning_state["org_context"] = dict(org_context or {})
    return dict(org_context or {})


async def _assemble_response(
    service: Any,
    *,
    normalized: NormalizedInput,
    run_input: ConversationRunInput,
    run_context: Any,
    user_config: Optional[Dict[str, Any]],
    base_system_prompt: str,
    tools: ToolExecutionBundle,
) -> ResponseDraft:
    messages: List[Dict[str, Any]]
    if run_input.messages:
        messages = [dict(message) for message in run_input.messages]
        prompt_debug: Dict[str, Any] = {
            "used_block_ids": [],
            "dropped_block_ids": [],
            "compacted": False,
            "source": "prebuilt_messages",
        }
    else:
        runtime_input_blocks = build_runtime_input_blocks(
            user_message=normalized.user_message,
            user_id=normalized.user_id or "default_user",
            attachments=normalized.attachments,
            runtime_blocks=normalized.runtime_blocks,
            run_context=run_context,
        )
        setattr(run_context, "runtime_blocks", [block.to_dict() for block in runtime_input_blocks])
        assembly = PROMPT_ASSEMBLER.assemble(
            run_context=run_context,
            mode=ModeDecision(mode="fast", reason="main_model_control_loop", confidence=1.0),
            plan=PlanResult(used_reasoning=False, base_system_prompt=base_system_prompt),
            memory_bundle=MemoryRecallBundle(recalled=False, reason="available_on_demand"),
            tools=tools,
            user_config=user_config,
        )
        messages = []
        if assembly.get("system_prompt"):
            messages.append({"role": "system", "content": assembly["system_prompt"]})
        messages.extend(normalized.recent_messages)
        vision_enabled = service._is_vision_enabled(user_config=user_config, user_id=normalized.user_id)
        messages.append(
            {
                "role": "user",
                "content": service.context_compiler.compile_user_content(
                    user_text=normalized.user_message,
                    blocks=runtime_input_blocks,
                    vision_enabled=vision_enabled,
                ),
            }
        )
        prompt_debug = dict(assembly.get("debug") or {})
        prompt_debug["runtime_blocks"] = blocks_debug(runtime_input_blocks)
        prompt_debug["llm_io"] = {
            "vision_enabled": vision_enabled,
            "input_block_count": len(runtime_input_blocks),
            "compiled_user_content_type": "blocks" if isinstance(messages[-1]["content"], list) else "text",
        }

    response = await service.run_chat_loop(
        messages,
        user_config=user_config,
        session_id=normalized.session_id,
        user_id=normalized.user_id,
        run_context=run_context,
        tool_executor=tools.tool_executor if tools.enabled else None,
        max_recursion=int((tools.metadata or {}).get("tool_budget") or resolve_action_budget(user_config)),
    )
    raw = dict(response) if isinstance(response, dict) else {"raw": response}
    raw.setdefault("prompt_assembly", prompt_debug)
    raw["soul"] = build_soul_response_payload(user_config)
    return ResponseDraft(
        status=str(raw.get("status") or "success"),
        content=str(raw.get("content") or ""),
        messages=messages,
        response_data=raw,
    )


def _capability_outcome(raw: Dict[str, Any]) -> Dict[str, Any]:
    calls = [item for item in (raw.get("tool_calls") or []) if isinstance(item, dict)]
    successful_names = [
        str(item.get("tool_name") or "")
        for item in calls
        if bool(item.get("ok", False))
    ]
    failed = [item for item in calls if not bool(item.get("ok", False))]
    used_reasoning = "reasoning.run" in successful_names
    memory_recalled = "memory.get_context" in successful_names
    workflow_used = any(name.startswith("workflow.") for name in successful_names)
    mode = "workflow" if workflow_used else ("deep" if used_reasoning else "fast")
    return {
        "calls": calls,
        "mode": mode,
        "used_reasoning": used_reasoning,
        "memory_recalled": memory_recalled,
        "workflow_used": workflow_used,
        "failed": failed,
    }


async def run_staged_pipeline(service: Any, run_input: ConversationRunInput) -> ConversationRunOutput:
    stages = ["input_normalization", "capability_discovery", "model_control_loop", "response_finalize"]
    state: Dict[str, Any] = {"stages": [], "stage_status": {}}
    current_stage = stages[0]
    run_context = run_input.run_context
    session_id = run_input.session_id
    user_id = run_input.user_id

    try:
        await _emit_stage(service, stage=current_stage, status="started", run_context=run_context, session_id=session_id, user_id=user_id)
        normalized = await stage_input_normalization(service, run_input)
        session_id, user_id = normalized.session_id, normalized.user_id
        if run_context is None:
            run_context = SimpleNamespace(
                input_payload={"message": normalized.user_message, "metadata": normalized.metadata},
                reasoning_state={},
            )
            run_input.run_context = run_context
        await _emit_stage(service, stage=current_stage, status="finished", run_context=run_context, session_id=session_id, user_id=user_id)
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok"}

        user_config = run_input.user_config
        base_system_prompt, resolved_config = await service._get_user_prompt_and_config(user_id or "default_user", normalized.channel)
        if user_config is None:
            user_config = resolved_config
        setattr(
            run_context,
            "runtime_context",
            build_runtime_context_block(
                recent_messages=normalized.recent_messages,
                user_config=user_config,
                timezone_name=str((normalized.metadata or {}).get("timezone") or ""),
            ),
        )
        base_system_prompt = service._append_language_policy(service._ensure_core_system_prompt(base_system_prompt))
        org_context = await _attach_org_context(
            service,
            normalized=normalized,
            run_context=run_context,
            user_config=user_config,
        )
        self_model_context = await service.attach_self_model_context(
            user_id=user_id or "default_user",
            user_message=normalized.user_message,
            run_context=run_context,
        )

        current_stage = stages[1]
        await _emit_stage(service, stage=current_stage, status="started", run_context=run_context, session_id=session_id, user_id=user_id)
        tools = await stage_capability_discovery(
            service,
            run_input=run_input,
            normalized=normalized,
            run_context=run_context,
            user_config=user_config,
        )
        await _emit_stage(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"available_tools": len((tools.metadata or {}).get("registered_tools") or [])},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok", "enabled": tools.enabled}

        current_stage = stages[2]
        await _emit_stage(service, stage=current_stage, status="started", run_context=run_context, session_id=session_id, user_id=user_id)
        response = await _assemble_response(
            service,
            normalized=normalized,
            run_input=run_input,
            run_context=run_context,
            user_config=user_config,
            base_system_prompt=base_system_prompt,
            tools=tools,
        )
        outcome = _capability_outcome(response.response_data)
        await _emit_stage(
            service,
            stage=current_stage,
            status="finished",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"tool_call_count": len(outcome["calls"]), "mode": outcome["mode"]},
        )
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {
            "status": "degraded" if outcome["failed"] else "ok",
            "tool_call_count": len(outcome["calls"]),
        }

        current_stage = stages[3]
        await _emit_stage(service, stage=current_stage, status="started", run_context=run_context, session_id=session_id, user_id=user_id)
        feedback_hints: List[Dict[str, Any]] = []
        if service.memory_service and session_id and user_id:
            drain = getattr(service.memory_service, "drain_visibility_hints", None)
            if callable(drain):
                try:
                    feedback_hints = list(drain(session_id=session_id, user_id=user_id, limit=3) or [])
                except Exception:
                    feedback_hints = []
        memory_bundle = MemoryRecallBundle(
            recalled=outcome["memory_recalled"],
            reason="main_model_tool_call" if outcome["memory_recalled"] else "not_requested",
        )
        raw = dict(response.response_data)
        raw["memory_visibility"] = (
            build_memory_visibility(memory_bundle=memory_bundle, feedback_hints=feedback_hints)
            if _memory_visibility_enabled(user_config)
            else {"enabled": False, "notices": []}
        )
        raw["org_context"] = {
            "enabled": bool(org_context.get("enabled")),
            "recalled": bool(org_context.get("recalled")),
            "org_id": str(org_context.get("org_id") or ""),
            "audience": str(org_context.get("audience") or ""),
            "backend": str(org_context.get("backend") or ""),
            "items": list(org_context.get("items") or []),
        }
        raw["self_model"] = {
            "version": self_model_context.get("version"),
            "revision": self_model_context.get("revision"),
            "available": bool(self_model_context.get("prompt_text")),
        }
        state["stages"].append(current_stage)
        state["stage_status"][current_stage] = {"status": "ok", "response_status": response.status}
        raw["pipeline"] = state
        raw["mode"] = outcome["mode"]
        raw["prompt_policy"] = {
            "source": "main_model_control_loop",
            "decision_owner": "main_model",
            "tool_budget": int((tools.metadata or {}).get("tool_budget") or resolve_action_budget(user_config)),
        }
        raw["memory_recalled"] = outcome["memory_recalled"]
        raw["used_reasoning"] = outcome["used_reasoning"]
        raw["capability_state"] = {
            "memory": {"status": "ok" if outcome["memory_recalled"] else "skipped"},
            "reasoning": {"status": "ok" if outcome["used_reasoning"] else "skipped"},
            "tools": {
                "status": "degraded" if outcome["failed"] else ("ok" if outcome["calls"] else "skipped"),
                "call_count": len(outcome["calls"]),
            },
            "degraded": bool(outcome["failed"]),
            "degraded_stages": ["model_control_loop"] if outcome["failed"] else [],
        }
        raw["task_graph"] = build_task_graph_snapshot(
            stage_status=state["stage_status"],
            mode=outcome["mode"],
            response_status=response.status,
        )
        raw["context_budget"] = build_context_budget_snapshot(raw.get("prompt_assembly") or {})
        raw["orchestration"] = build_orchestration_snapshot(
            mode=outcome["mode"],
            used_reasoning=outcome["used_reasoning"],
        )
        await schedule_soul_evolution(
            service=service,
            user_id=user_id,
            user_config=user_config,
            user_message=normalized.user_message,
            assistant_message=response.content,
        )
        await _emit_stage(service, stage=current_stage, status="finished", run_context=run_context, session_id=session_id, user_id=user_id)
        return ConversationRunOutput(
            status=response.status,
            content=response.content,
            tool_call_id=raw.get("tool_call_id"),
            tool_name=raw.get("tool_name"),
            args=raw.get("args") if isinstance(raw.get("args"), dict) else None,
            raw=raw,
        )
    except Exception as exc:
        logger.exception("Conversation pipeline failed at {}: {}", current_stage, exc)
        await _emit_stage(
            service,
            stage=current_stage,
            status="failed",
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            payload={"error": str(exc)},
        )
        raise
