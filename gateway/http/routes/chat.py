from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from gateway.protocol import EventType, RequestType

from ..dispatcher import dispatch_gateway_method, get_gateway_server
from ..schemas import ChatRequest, ChatResponse, ConfirmToolRequest
from .auth import get_current_user_id


router = APIRouter()


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


def _emit_interaction_completed_async(gateway_server, payload: dict) -> None:
    event_emitter = getattr(gateway_server, "event_emitter", None)
    if not event_emitter:
        return

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


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    try:
        if request.stream:
            gateway_server = get_gateway_server()
            if not gateway_server.message_manager:
                raise HTTPException(status_code=503, detail="Message manager not initialized")
            if not gateway_server.conversation_service:
                raise HTTPException(status_code=503, detail="Conversation service not initialized")

            user_text = (request.message or "").strip()
            if not user_text:
                raise HTTPException(status_code=400, detail="message is required")

            def _sse(payload: dict) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            async def _stream():
                session_id = request.session_id
                message_manager = gateway_server.message_manager
                turn_id = uuid.uuid4().hex
                try:
                    if session_id:
                        if not message_manager.get_session(session_id, user_id=user_id):
                            message_manager.create_session(session_id=session_id, user_id=user_id)
                    else:
                        session_id = message_manager.create_session(user_id=user_id)

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
                        )
                    )
                    discovered_tree_id = None
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
                    stream_failed = False
                    run_chat_loop_result = {}
                    async for chunk in gateway_server.conversation_service.call_llm_stream(
                        messages, user_config=user_config, user_id=user_id
                    ):
                        if isinstance(chunk, str) and chunk.startswith("[error]"):
                            stream_failed = True
                            break
                        if chunk:
                            full_text += chunk
                            yield _sse({"type": "text", "content": chunk})

                    if stream_failed:
                        run_chat_loop_result = await gateway_server.conversation_service.run_chat_loop(
                            messages,
                            user_config=user_config,
                            session_id=session_id,
                            user_id=user_id,
                            tool_executor=lambda name, payload: gateway_server._execute_tool_for_chat(
                                name,
                                payload,
                                session_id=session_id,
                                user_id=user_id,
                                request_id=f"http_stream_{turn_id}",
                                connection_id=f"http_stream_{turn_id}",
                            ),
                        )
                        full_text = run_chat_loop_result.get("content", "")
                        if full_text:
                            yield _sse({"type": "text", "content": full_text})

                    committed = message_manager.commit_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        assistant_content=full_text,
                        user_id=user_id,
                    )
                    if not committed:
                        yield _sse({"type": "error", "content": "failed to commit turn"})
                        return

                    if isinstance(run_chat_loop_result, dict):
                        memory_write_summary = _summarize_memory_visibility(
                            run_chat_loop_result.get("memory_visibility")
                        )
                    if not memory_write_summary:
                        memory_service = getattr(gateway_server.conversation_service, "memory_service", None)
                        drain = getattr(memory_service, "drain_visibility_hints", None) if memory_service else None
                        if callable(drain) and session_id and user_id:
                            try:
                                rows = list(drain(session_id=session_id, user_id=user_id, limit=3) or [])
                                if rows:
                                    memory_write_summary = {
                                        "enabled": True,
                                        "recalled": False,
                                        "recall_notice": "",
                                        "write_notice": "",
                                        "review_notice": "",
                                        "notices": [],
                                        "feedback_hints": rows,
                                    }
                            except Exception:
                                memory_write_summary = None

                    done_payload = {"type": "done", "session_id": session_id}
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
                    if not stream_failed:
                        _emit_interaction_completed_async(
                            gateway_server,
                            {
                                "session_id": session_id,
                                "user_id": user_id,
                                "channel": "web",
                                "user_input": user_text,
                                "assistant_output": full_text,
                            },
                        )
                except Exception as e:
                    message_manager.abort_turn(session_id, turn_id, user_id=user_id)
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
                },
                user_id=gateway_request.user_id,
                request=raw_request,
            )
            mapped = adapter.emit_response(payload)

        return ChatResponse(
            response=mapped.get("response", ""),
            session_id=mapped.get("session_id"),
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







