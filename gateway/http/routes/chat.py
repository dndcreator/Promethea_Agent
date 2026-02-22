from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from gateway.protocol import EventType, RequestType

from ..dispatcher import dispatch_gateway_method, get_gateway_server
from ..schemas import ChatRequest, ChatResponse, ConfirmToolRequest
from .auth import get_current_user_id


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user_id)):
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

                    recent = message_manager.get_recent_messages(session_id, user_id=user_id)
                    messages = [{"role": m["role"], "content": m["content"]} for m in recent]
                    messages.append({"role": "user", "content": user_text})

                    user_config = None
                    base_system_prompt = ""
                    if gateway_server.config_service:
                        user_config = gateway_server.config_service.get_merged_config(user_id)
                        base_system_prompt = (
                            user_config.get("prompts", {}).get("Promethea_system_prompt", "")
                        )
                        custom_prompt = user_config.get("system_prompt")
                        agent_name = user_config.get("agent_name")
                        if custom_prompt:
                            base_system_prompt = custom_prompt
                        if agent_name:
                            base_system_prompt = (
                                base_system_prompt.replace("Promethea", agent_name).replace(
                                    "your assistant", agent_name
                                )
                            )

                    system_prompt = await gateway_server.conversation_service.build_system_prompt_with_memory(
                        query=user_text,
                        session_id=session_id,
                        user_id=user_id,
                        user_config=user_config,
                        base_system_prompt=base_system_prompt,
                    )
                    if system_prompt:
                        messages = [{"role": "system", "content": system_prompt}] + messages

                    full_text = ""
                    stream_failed = False
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
                        result = await gateway_server.conversation_service.run_chat_loop(
                            messages,
                            user_config=user_config,
                            session_id=session_id,
                            user_id=user_id,
                            tool_executor=lambda name, payload: gateway_server._execute_tool_for_chat(  # noqa: SLF001
                                name,
                                payload,
                                session_id=session_id,
                                user_id=user_id,
                                request_id=f"http_stream_{turn_id}",
                                connection_id=f"http_stream_{turn_id}",
                            ),
                        )
                        full_text = result.get("content", "")
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

                    if gateway_server.event_emitter and not stream_failed:
                        await gateway_server.event_emitter.emit(
                            EventType.INTERACTION_COMPLETED,
                            {
                                "session_id": session_id,
                                "user_id": user_id,
                                "channel": "web",
                                "user_input": user_text,
                                "assistant_output": full_text,
                            },
                        )

                    yield _sse({"type": "done", "session_id": session_id})
                except Exception as e:
                    message_manager.abort_turn(session_id, turn_id, user_id=user_id)
                    logger.error(f"chat stream failed: {e}")
                    yield _sse({"type": "error", "content": str(e)})

            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        payload = await dispatch_gateway_method(
            RequestType.CHAT,
            {
                "message": request.message,
                "session_id": request.session_id,
                "stream": False,
            },
            user_id=user_id,
        )
        return ChatResponse(
            response=payload.get("response", ""),
            session_id=payload.get("session_id"),
            status=payload.get("status", "success"),
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            args=payload.get("args"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat failed: {e}")


@router.post("/chat/confirm", response_model=ChatResponse)
async def confirm_tool(request: ConfirmToolRequest, user_id: str = Depends(get_current_user_id)):
    try:
        payload = await dispatch_gateway_method(
            RequestType.CHAT_CONFIRM,
            {
                "session_id": request.session_id,
                "tool_call_id": request.tool_call_id,
                "action": request.action,
            },
            user_id=user_id,
        )
        return ChatResponse(
            response=payload.get("response", ""),
            session_id=payload.get("session_id"),
            status=payload.get("status", "success"),
            tool_call_id=payload.get("tool_call_id"),
            tool_name=payload.get("tool_name"),
            args=payload.get("args"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat confirm failed: {e}")
        raise HTTPException(status_code=500, detail=f"chat confirm failed: {e}")
