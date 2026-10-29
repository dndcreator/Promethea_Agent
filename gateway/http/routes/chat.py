from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from gateway.action.models import resolve_action_budget
from gateway.protocol import EventType, RequestType
from gateway.public_contracts import RunSteerRequest, RunSteerResponse

from ..dispatcher import dispatch_gateway_method, get_gateway_server
from ..schemas import ChatRequest, ChatResponse, ConfirmToolRequest
from .auth import get_current_user_id


router = APIRouter()


@router.post("/chat/{session_id}/steer", response_model=RunSteerResponse)
async def steer_chat(session_id: str, command: RunSteerRequest, user_id: str = Depends(get_current_user_id)):
    service = get_gateway_server().conversation_service
    if service is None:
        raise HTTPException(status_code=503, detail="Conversation service not initialized")
    try:
        return await service.steer_turn(session_id=session_id, user_id=user_id, turn_id=command.conversation_turn_id,
                                        message_id=command.message_id, message=command.message)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


def _normalize_tool_args(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        try:
            if all(isinstance(item, (list, tuple)) and len(item) == 2 for item in value):
                return {str(k): v for k, v in value}
        except Exception:
            pass
        return {"_args_list": list(value)}
    return {"_arg": value}


def _summarize_memory_visibility(value):
    if not isinstance(value, dict):
        return None
    enabled = bool(value.get("enabled"))
    notices = value.get("notices")
    feedback_hints = value.get("feedback_hints")
    return {
        "enabled": enabled,
        "recalled": bool(value.get("recalled")),
        "recall_notice": str(value.get("recall_notice") or ""),
        "write_notice": str(value.get("write_notice") or ""),
        "review_notice": str(value.get("review_notice") or ""),
        "notices": [str(x) for x in (notices or []) if str(x).strip()],
        "feedback_hints": list(feedback_hints or []),
    }


def _emit_interaction_completed_async(gateway_server, payload: dict):
    event_emitter = getattr(gateway_server, "event_emitter", None)
    if not event_emitter:
        return None

    task = asyncio.create_task(
        event_emitter.emit(EventType.INTERACTION_COMPLETED, payload)
    )

    def _log_background_failure(done_task: asyncio.Task) -> None:
        try:
            exc = done_task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            logger.error(f"background interaction.completed failed: {exc}")

    task.add_done_callback(_log_background_failure)
    return task


def _drain_memory_visibility(gateway_server, *, session_id: str, user_id: str, limit: int = 3):
    memory_service = getattr(getattr(gateway_server, "conversation_service", None), "memory_service", None)
    drain = getattr(memory_service, "drain_visibility_hints", None) if memory_service else None
    if not callable(drain) or not session_id or not user_id:
        return None
    try:
        rows = list(drain(session_id=session_id, user_id=user_id, limit=limit) or [])
    except Exception:
        return None
    if not rows:
        return None
    return {
        "enabled": True,
        "recalled": False,
        "recall_notice": "",
        "write_notice": "",
        "review_notice": "",
        "notices": [],
        "feedback_hints": rows,
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        attachments = [
            item.model_dump(exclude_none=True, exclude_defaults=True)
            for item in request.attachments
        ]
        if request.stream:
            gateway_server = get_gateway_server()
            if not gateway_server.message_manager:
                raise HTTPException(status_code=503, detail="Message manager not initialized")
            if not gateway_server.conversation_service:
                raise HTTPException(status_code=503, detail="Conversation service not initialized")

            user_text = (request.message or "").strip()
            if not user_text:
                raise HTTPException(status_code=400, detail="message is required")

            async def _stream():
                session_id = request.session_id
                message_manager = gateway_server.message_manager
                turn_id = uuid.uuid4().hex
                request_id = f"http_stream_{turn_id}"
                stream_seq = 0

                def _sse(payload: dict) -> str:
                    nonlocal stream_seq
                    stream_seq += 1
                    event_type = str(payload.get("type") or "message")
                    event_id = f"{request_id}:{stream_seq}"
                    body = dict(payload)
                    body.setdefault("event_id", event_id)
                    body.setdefault("event_type", event_type)
                    body.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
                    body.setdefault("seq", stream_seq)
                    body.setdefault("request_id", request_id)
                    body.setdefault("source", "gateway.http.chat")
                    if request.task_id:
                        body.setdefault("task_id", request.task_id)
                    return (
                        f"id: {event_id}\n"
                        f"event: {event_type}\n"
                        f"data: {json.dumps(body, ensure_ascii=False)}\n\n"
                    )

                try:
                    if session_id:
                        if not message_manager.get_session(session_id, user_id=user_id):
                            message_manager.create_session(session_id=session_id, user_id=user_id)
                    else:
                        session_id = message_manager.create_session(user_id=user_id)
                    run_params = {
                        "message": user_text,
                        "session_id": session_id,
                        "stream": True,
                        "requested_mode": request.requested_mode,
                        "requested_skill": request.requested_skill,
                        "requested_workflow": request.requested_workflow,
                        "task_id": request.task_id,
                        "metadata": dict(request.metadata or {}),
                        "attachments": attachments,
                    }
                    run_context = gateway_server._build_run_context(
                        request=SimpleNamespace(id=request_id, params=run_params),
                        session_id=session_id,
                        user_id=user_id,
                        channel_id="web",
                        input_payload=run_params,
                    )
                    run_context.conversation_turn_id = turn_id
                    merged_config = (
                        gateway_server.config_service.get_merged_config(user_id)
                        if gateway_server.config_service
                        else {}
                    )
                    gateway_server._apply_skill_runtime_context(
                        run_context=run_context,
                        requested_skill=request.requested_skill,
                        user_config=merged_config if isinstance(merged_config, dict) else {},
                    )
                    yield _sse({
                        "type": "session_started",
                        "session_id": session_id,
                        "conversation_turn_id": turn_id,
                    })

                    began = message_manager.begin_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        user_role="user",
                        user_content=user_text,
                        user_id=user_id,
                    )
                    if not began:
                        yield _sse({"type": "error", "content": "failed to start turn"})
                        return

                    prepared_task = asyncio.create_task(
                        gateway_server.conversation_service.prepare_chat_turn(
                            session_id=session_id,
                            user_id=user_id,
                            user_message=user_text,
                            channel="web",
                            include_recent=True,
                            run_context=run_context,
                            attachments=attachments,
                        )
                    )
                    discovered_tree_id = None
                    yield _sse(
                        {
                            "type": "reasoning_meta",
                            "session_id": session_id,
                            "status": "preparing",
                            "message": "Preparing runtime context and capabilities.",
                        }
                    )
                    while not prepared_task.done():
                        reasoning_service = gateway_server.reasoning_service
                        if reasoning_service and session_id:
                            try:
                                active_rows = reasoning_service.list_runtime_trees(
                                    user_id=user_id,
                                    session_id=session_id,
                                    include_pending=False,
                                    limit=5,
                                ).get("items", [])
                            except Exception:
                                active_rows = []
                            for row in active_rows:
                                tree_id = str((row or {}).get("tree_id", "") or "")
                                if not tree_id:
                                    continue
                                if discovered_tree_id == tree_id:
                                    continue
                                discovered_tree_id = tree_id
                                yield _sse(
                                    {
                                        "type": "reasoning_meta",
                                        "tree_id": tree_id,
                                        "session_id": session_id,
                                        "status": (row or {}).get("status"),
                                    }
                                )
                                break
                        await asyncio.sleep(0.2)
                    prepared = await prepared_task
                    messages = prepared["messages"]
                    user_config = prepared["user_config"]
                    prompt_policy = prepared.get("prompt_policy", {}) if isinstance(prepared, dict) else {}
                    tool_budget = int(
                        (prepared.get("execution_budget") or {}).get("tool_budget")
                        or (prompt_policy.get("tool_budget") if isinstance(prompt_policy, dict) else 0)
                        or resolve_action_budget(user_config)
                    )
                    reasoning_meta = prepared.get("reasoning", {}) if isinstance(prepared, dict) else {}
                    tree_id = reasoning_meta.get("tree_id") if isinstance(reasoning_meta, dict) else None
                    if tree_id and tree_id != discovered_tree_id:
                        yield _sse(
                            {
                                "type": "reasoning_meta",
                                "tree_id": tree_id,
                                "session_id": session_id,
                                "mode": reasoning_meta.get("mode"),
                                "status": reasoning_meta.get("status"),
                            }
                        )

                    full_text = ""
                    memory_write_summary = None
                    output_queue: asyncio.Queue = asyncio.Queue()
                    stream_finished = object()

                    async def _publish_answer_delta(delta) -> None:
                        if isinstance(delta, dict):
                            await output_queue.put((str(delta.get("type") or "text"), delta))
                        elif delta:
                            await output_queue.put(("text", {"operation": "delta", "content": delta}))

                    async def _publish_reasoning_delta(payload: Dict[str, Any]) -> None:
                        if payload:
                            await output_queue.put(("reasoning", dict(payload)))

                    action_task = asyncio.create_task(
                        gateway_server.conversation_service.run_chat_loop(
                            messages,
                            user_config=user_config,
                            session_id=session_id,
                            user_id=user_id,
                            run_context=run_context,
                            max_recursion=tool_budget,
                            output_sink=_publish_answer_delta,
                            tool_executor=lambda name, payload: gateway_server._execute_tool_for_chat(
                                name,
                                payload,
                                session_id=session_id,
                                user_id=user_id,
                                request_id=request_id,
                                connection_id=request_id,
                                run_context=run_context,
                                user_config=user_config,
                            ),
                            reasoning_sink=_publish_reasoning_delta,
                        )
                    )
                    action_task.add_done_callback(lambda _task: output_queue.put_nowait(stream_finished))
                    streamed_text = ""
                    try:
                        while True:
                            try:
                                item = await asyncio.wait_for(output_queue.get(), timeout=15)
                            except asyncio.TimeoutError:
                                yield ": keep-alive\n\n"
                                continue
                            if item is stream_finished:
                                break
                            event_type, event_payload = item
                            if event_type == "text":
                                update = dict(event_payload)
                                text = str(update.get("content") or "")
                                streamed_text = text if update.get("operation") == "replace" else streamed_text + text
                                yield _sse({"type": "text", **update})
                            elif event_type == "steering":
                                yield _sse({"type": "steering", "conversation_turn_id": turn_id, **event_payload})
                            else:
                                yield _sse({
                                    "type": "reasoning",
                                    "conversation_turn_id": turn_id,
                                    **dict(event_payload),
                                })
                        run_chat_loop_result = await action_task
                    finally:
                        if not action_task.done():
                            action_task.cancel()
                            await asyncio.gather(action_task, return_exceptions=True)
                    full_text = str(run_chat_loop_result.get("content") or "")

                    run_status = str(run_chat_loop_result.get("status") or "success").lower()
                    if run_status not in {"success", "ok", "completed", "needs_confirmation"}:
                        error = run_chat_loop_result.get("error")
                        message_manager.abort_turn(
                            session_id, turn_id, user_id=user_id,
                            error=error if isinstance(error, dict) else {"message": str(error or "agent run failed")},
                            reasoning_tree_id=tree_id,
                            reasoning_steps=list(run_chat_loop_result.get("reasoning_steps") or []),
                        )
                        detail = error.get("message") if isinstance(error, dict) else str(error or "agent run failed")
                        yield _sse({"type": "error", "session_id": session_id, "content": detail, "error_detail": {"code": (error or {}).get("code", "RUN_FAILED") if isinstance(error, dict) else "RUN_FAILED", "message": detail}})
                        return

                    confirmation_payload = None
                    if isinstance(run_chat_loop_result, dict) and run_chat_loop_result.get("status") == "needs_confirmation":
                        pending = dict(run_chat_loop_result)
                        pending.setdefault("current_messages", messages)
                        pending["turn_id"] = turn_id
                        pending["reasoning_tree_id"] = tree_id
                        message_manager.set_pending_confirmation(
                            session_id,
                            pending,
                            user_id=user_id,
                        )
                        confirmation_payload = {
                            "status": "needs_confirmation",
                            "tool_call_id": run_chat_loop_result.get("tool_call_id"),
                            "tool_name": run_chat_loop_result.get("tool_name"),
                            "args": _normalize_tool_args(run_chat_loop_result.get("args")),
                        }
                        full_text = ""

                    if full_text and not streamed_text:
                        yield _sse({"type": "text", "content": full_text})
                    elif full_text.startswith(streamed_text) and len(full_text) > len(streamed_text):
                        yield _sse({"type": "text", "content": full_text[len(streamed_text) :]})
                    elif full_text != streamed_text:
                        yield _sse({"type": "text", "operation": "replace", "content": full_text})

                    if confirmation_payload:
                        yield _sse({"type": "done", "session_id": session_id, **confirmation_payload})
                        return

                    committed = message_manager.commit_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        assistant_content=full_text,
                        user_id=user_id,
                        reasoning_tree_id=tree_id,
                        reasoning_steps=list(run_chat_loop_result.get("reasoning_steps") or []),
                        agent_message_ids=run_chat_loop_result.get("agent_message_ids"),
                    )
                    if not committed:
                        yield _sse({"type": "error", "content": "failed to commit turn"})
                        return

                    if isinstance(run_chat_loop_result, dict):
                        memory_write_summary = _summarize_memory_visibility(
                            run_chat_loop_result.get("memory_visibility")
                        )
                    interaction_context = []
                    try:
                        interaction_context = message_manager.get_recent_messages(
                            session_id,
                            count=6,
                            user_id=user_id,
                        )
                    except Exception:
                        interaction_context = []
                    interaction_task = _emit_interaction_completed_async(
                        gateway_server,
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "channel": "web",
                            "user_input": user_text,
                            "assistant_output": full_text,
                            "interaction_context": interaction_context,
                            "attachments": attachments,
                        },
                    )
                    if interaction_task is not None:
                        try:
                            await asyncio.wait_for(asyncio.shield(interaction_task), timeout=0.8)
                        except asyncio.TimeoutError:
                            pass
                        except Exception:
                            pass

                    if not memory_write_summary:
                        memory_write_summary = _drain_memory_visibility(
                            gateway_server,
                            session_id=session_id,
                            user_id=user_id,
                            limit=3,
                        )

                    done_payload = {
                        "type": "done",
                        "session_id": session_id,
                        "conversation_turn_id": turn_id,
                        "content": full_text,
                    }
                    if confirmation_payload:
                        done_payload.update(confirmation_payload)
                    if memory_write_summary:
                        done_payload["memory_write_summary"] = memory_write_summary
                        done_payload["memory_visibility"] = memory_write_summary
                    if gateway_server.reasoning_service and tree_id:
                        assessment = await gateway_server.reasoning_service.assess_outcome(
                            tree_id=tree_id,
                            assistant_output=full_text,
                            user_config=user_config,
                            user_id=user_id,
                            allow_human_review=True,
                        )
                        if assessment.get("status") == "needs_confirmation":
                            review_id = assessment.get("review_id")
                            pending = {
                                "confirmation_type": "reasoning_outcome",
                                "status": "needs_confirmation",
                                "tool_call_id": review_id,
                                "tool_name": "reasoning.success_label",
                                "args": {
                                    "question": "Was the previous answer successful?",
                                    "judge_outcome": assessment.get("outcome", "unsure"),
                                    "judge_confidence": assessment.get("confidence", 0.0),
                                    "judge_reason": assessment.get("reason", ""),
                                },
                                "turn_id": None,
                            }
                            message_manager.set_pending_confirmation(
                                session_id, pending, user_id=user_id
                            )
                            done_payload.update(
                                {
                                    "status": "needs_confirmation",
                                    "tool_call_id": review_id,
                                    "tool_name": "reasoning.success_label",
                                    "args": pending["args"],
                                    "tree_id": tree_id,
                                }
                            )
                        else:
                            done_payload["tree_id"] = tree_id

                    yield _sse(done_payload)
                except asyncio.CancelledError:
                    message_manager.abort_turn(session_id, turn_id, user_id=user_id)
                    raise
                except Exception as e:
                    message_manager.abort_turn(session_id, turn_id, user_id=user_id, error={"code": "RUN_FAILED", "message": str(e)})
                    logger.error(f"chat stream failed: {e}")
                    yield _sse({"type": "error", "content": str(e)})

            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        gateway_server = get_gateway_server()
        adapter_registry = getattr(gateway_server, "channel_adapter_registry", None)
        adapter = adapter_registry.get("http_api") if adapter_registry else None
        if adapter is None:
            payload = await dispatch_gateway_method(
                RequestType.CHAT,
                {
                    "message": request.message,
                    "session_id": request.session_id,
                    "stream": False,
                    "requested_mode": request.requested_mode,
                    "requested_skill": request.requested_skill,
                    "requested_workflow": request.requested_workflow,
                    "task_id": request.task_id,
                    "metadata": dict(request.metadata or {}),
                    "attachments": attachments,
                },
                user_id=user_id,
                request=raw_request,
            )
            mapped = payload
        else:
            gateway_request = adapter.ingest_message(
                {
                    "request_id": f"http_{uuid.uuid4().hex}",
                    "session_id": request.session_id,
                    "message": request.message,
                    "user_id": user_id,
                    "attachments": attachments,
                    "requested_mode": request.requested_mode,
                    "requested_skill": request.requested_skill,
                    "requested_workflow": request.requested_workflow,
                    "task_id": request.task_id,
                    "metadata": dict(request.metadata or {}),
                }
            )
            perm = adapter.permission_check(adapter.normalize_identity({"user_id": user_id}))
            if not perm.allowed:
                raise HTTPException(status_code=403, detail=f"permission denied: {perm.reason}")
            payload = await dispatch_gateway_method(
                RequestType.CHAT,
                {
                    "message": gateway_request.input_text,
                    "session_id": gateway_request.session_id,
                    "stream": False,
                    "channel": gateway_request.channel_id,
                    "requested_mode": request.requested_mode,
                    "requested_skill": request.requested_skill,
                    "requested_workflow": request.requested_workflow,
                    "task_id": request.task_id,
                    "metadata": dict(request.metadata or {}),
                    "attachments": attachments,
                },
                user_id=gateway_request.user_id,
                request=raw_request,
            )
            mapped = adapter.emit_response(payload)

        return ChatResponse(
            response=mapped.get("response", ""),
            session_id=mapped.get("session_id"),
            run_id=mapped.get("run_id"),
            request_id=mapped.get("request_id"),
            trace_id=mapped.get("trace_id"),
            status=mapped.get("status", "success"),
            tool_call_id=mapped.get("tool_call_id"),
            tool_name=mapped.get("tool_name"),
            args=_normalize_tool_args(mapped.get("args")),
            memory_write_summary=_summarize_memory_visibility(mapped.get("memory_write_summary")),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")

@router.post("/chat/confirm", response_model=ChatResponse)
async def confirm_tool(
    request: ConfirmToolRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        payload = await dispatch_gateway_method(
            RequestType.CHAT_CONFIRM,
            {
                "session_id": request.session_id,
                "tool_call_id": request.tool_call_id,
                "action": request.action,
            },
            user_id=user_id,
            request=raw_request,
        )
        return ChatResponse(
            response=payload.get("response", ""),
            session_id=payload.get("session_id"),
            status=payload.get("status", "success"),
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            args=_normalize_tool_args(payload.get("args")),
            memory_write_summary=_summarize_memory_visibility(payload.get("memory_write_summary")),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat confirm failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat confirm failed: {e}")







