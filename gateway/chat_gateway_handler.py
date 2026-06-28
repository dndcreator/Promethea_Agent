from __future__ import annotations

import inspect
import uuid
from typing import Any, Dict

from loguru import logger

from agentkit.mcp.tool_call import ToolConfirmationRequired, execute_tool_calls

from .protocol import ConversationRunInput, EventType, GatewayProtocol, GatewayResponse


async def handle_chat(self, connection, request):
    """Handle one chat turn in gateway control-plane."""
    try:
        if not self.message_manager:
            return GatewayProtocol.create_response(
                request.id, False, error="Message manager not initialized"
            )
        if not self.conversation_service:
            return GatewayProtocol.create_response(
                request.id, False, error="Conversation service not initialized"
            )

        requested_channel = str(request.params.get("channel") or "web").strip() or "web"
        adapter = self.channel_adapter_registry.get(requested_channel) or self.channel_adapter_registry.get("web")
        if adapter is None:
            return GatewayProtocol.create_response(
                request.id, False, error=f"channel adapter not found: {requested_channel}"
            )

        user_id = self._resolve_request_user_id(connection, request)
        raw_input = {
            "request_id": request.id,
            "trace_id": request.params.get("trace_id"),
            "session_id": request.params.get("session_id"),
            "message": request.params.get("message"),
            "requested_mode": request.params.get("requested_mode"),
            "requested_skill": request.params.get("requested_skill"),
            "metadata": request.params.get("metadata") or {},
            "attachments": request.params.get("attachments") or [],
            "runtime_blocks": request.params.get("runtime_blocks") or [],
            "user_id": request.params.get("user_id") or user_id,
            "sender_id": getattr(getattr(connection, "identity", None), "device_id", None),
        }
        identity = adapter.normalize_identity(raw_input)
        decision = adapter.permission_check(identity)
        if not decision.allowed:
            return GatewayProtocol.create_response(
                request.id, False, error=f"permission denied: {decision.reason}"
            )

        gateway_request = adapter.ingest_message(raw_input)
        user_id = gateway_request.user_id
        channel_id = str(gateway_request.channel_id or requested_channel)
        user_text = (gateway_request.input_text or "").strip()
        if not user_text:
            return GatewayProtocol.create_response(
                request.id, False, error="message is required"
            )

        session_id = gateway_request.session_id
        if session_id:
            if not self.message_manager.get_session(session_id, user_id=user_id):
                self.message_manager.create_session(session_id=session_id, user_id=user_id)
        else:
            session_id = self.message_manager.create_session(user_id=user_id)
            gateway_request.session_id = session_id

        run_context_payload = dict(request.params or {})
        run_context_payload["session_id"] = session_id
        run_context_payload["requested_mode"] = gateway_request.requested_mode
        run_context_payload["requested_skill"] = gateway_request.requested_skill
        run_context = self._build_run_context(
            request=request,
            session_id=session_id,
            user_id=user_id,
            channel_id=channel_id,
            input_payload=run_context_payload,
        )
        merged_for_skill = self.config_service.get_merged_config(user_id) if self.config_service else {}
        active_skill = self._apply_skill_runtime_context(
            run_context=run_context,
            requested_skill=gateway_request.requested_skill,
            user_config=merged_for_skill if isinstance(merged_for_skill, dict) else {},
        )
        if active_skill and active_skill.get("skill_id"):
            gateway_request.requested_skill = str(active_skill.get("skill_id"))

        if self.event_emitter:
            await self.event_emitter.emit(
                EventType.GATEWAY_RUN_STARTED,
                {
                    "request_id": request.id,
                    "trace_id": gateway_request.trace_id,
                    "session_id": session_id,
                    "user_id": user_id,
                },
            )
            await self.event_emitter.emit(
                EventType.CONVERSATION_RUN_STARTED,
                {
                    "request_id": request.id,
                    "trace_id": gateway_request.trace_id,
                    "session_id": session_id,
                    "user_id": user_id,
                },
            )

        turn_id = str(uuid.uuid4())
        began = self.message_manager.begin_turn(
            session_id=session_id,
            turn_id=turn_id,
            user_role="user",
            user_content=user_text,
            user_id=user_id,
        )
        if not began:
            return GatewayProtocol.create_response(
                request.id, False, error="failed to start turn"
            )

        try:
            prepared = await self.conversation_service.prepare_chat_turn(
                session_id=session_id,
                user_id=user_id,
                user_message=user_text,
                channel=channel_id,
                include_recent=True,
                run_context=run_context,
                attachments=request.params.get("attachments") or [],
                runtime_blocks=request.params.get("runtime_blocks") or [],
            )
        except TypeError:
            prepared = await self.conversation_service.prepare_chat_turn(
                session_id=session_id,
                user_id=user_id,
                user_message=user_text,
                channel=channel_id,
                include_recent=True,
                run_context=run_context,
            )
        messages = prepared["messages"]
        user_config = prepared["user_config"]

        tool_executor = lambda name, payload: self._execute_tool_for_chat(
            name,
            payload,
            session_id=session_id,
            user_id=user_id,
            request_id=request.id,
            connection_id=connection.connection_id,
            run_context=run_context,
            user_config=user_config,
        )
        tool_call_outcome: Dict[str, Any]
        run_conversation = getattr(self.conversation_service, "run_conversation", None)
        if callable(run_conversation):
            run_result = run_conversation(
                ConversationRunInput(
                    messages=messages,
                    user_config=user_config,
                    session_id=session_id,
                    user_id=user_id,
                    tool_executor=tool_executor,
                    run_context=run_context,
                    attachments=request.params.get("attachments") or [],
                    runtime_blocks=request.params.get("runtime_blocks") or [],
                )
            )
            run_result = await run_result if inspect.isawaitable(run_result) else run_result
            if isinstance(run_result, dict):
                tool_call_outcome = run_result
            else:
                raw_payload = getattr(run_result, "raw", None)
                if isinstance(raw_payload, dict):
                    tool_call_outcome = raw_payload
                else:
                    tool_call_outcome = {
                        "status": str(getattr(run_result, "status", "success") or "success"),
                        "content": str(getattr(run_result, "content", "") or ""),
                    }
        else:
            run_chat_loop = getattr(self.conversation_service, "run_chat_loop", None)
            if not callable(run_chat_loop):
                raise RuntimeError("conversation service missing run entrypoint")
            run_result = run_chat_loop(
                messages,
                user_config,
                session_id=session_id,
                user_id=user_id,
                tool_executor=tool_executor,
            )
            run_result = await run_result if inspect.isawaitable(run_result) else run_result
            tool_call_outcome = run_result if isinstance(run_result, dict) else {"status": "success", "content": ""}

        if tool_call_outcome.get("status") == "needs_confirmation":
            pending = dict(tool_call_outcome)
            pending["current_messages"] = messages
            pending["turn_id"] = turn_id
            self.message_manager.set_pending_confirmation(
                session_id, pending, user_id=user_id
            )
            payload = adapter.emit_response(
                {
                    "status": "needs_confirmation",
                    "session_id": session_id,
                    "tool_call_id": tool_call_outcome.get("tool_call_id"),
                    "tool_name": tool_call_outcome.get("tool_name"),
                    "args": tool_call_outcome.get("args"),
                    "response": f"Tool `{tool_call_outcome.get('tool_name')}` requires confirmation.",
                }
            )
            if self.event_emitter:
                await self.event_emitter.emit(
                    EventType.RESPONSE_SYNTHESIZED,
                    {
                        "request_id": request.id,
                        "trace_id": gateway_request.trace_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "status": "needs_confirmation",
                    },
                )
                await self.event_emitter.emit(
                    EventType.GATEWAY_RUN_FINISHED,
                    {
                        "request_id": request.id,
                        "trace_id": gateway_request.trace_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "status": "needs_confirmation",
                    },
                )
            return GatewayProtocol.create_response(request.id, True, payload)

        final_content = tool_call_outcome.get("content", "")
        committed = self.message_manager.commit_turn(
            session_id=session_id,
            turn_id=turn_id,
            assistant_content=final_content,
            user_id=user_id,
        )
        if not committed:
            return GatewayProtocol.create_response(
                request.id, False, error="failed to commit turn"
            )

        reasoning_meta = prepared.get("reasoning", {}) if isinstance(prepared, dict) else {}
        tree_id = reasoning_meta.get("tree_id") if isinstance(reasoning_meta, dict) else None
        if self.reasoning_service and tree_id:
            assessment = await self.reasoning_service.assess_outcome(
                tree_id=tree_id,
                assistant_output=final_content,
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
                self.message_manager.set_pending_confirmation(
                    session_id, pending, user_id=user_id
                )
                payload = adapter.emit_response(
                    {
                        "status": "needs_confirmation",
                        "session_id": session_id,
                        "tool_call_id": review_id,
                        "tool_name": "reasoning.success_label",
                        "args": pending["args"],
                        "response": final_content,
                    }
                )
                if self.event_emitter:
                    await self.event_emitter.emit(
                        EventType.RESPONSE_SYNTHESIZED,
                        {
                            "request_id": request.id,
                            "trace_id": gateway_request.trace_id,
                            "session_id": session_id,
                            "user_id": user_id,
                            "status": "needs_confirmation",
                        },
                    )
                    await self.event_emitter.emit(
                        EventType.GATEWAY_RUN_FINISHED,
                        {
                            "request_id": request.id,
                            "trace_id": gateway_request.trace_id,
                            "session_id": session_id,
                            "user_id": user_id,
                            "status": "needs_confirmation",
                        },
                    )
                return GatewayProtocol.create_response(request.id, True, payload)

        gateway_response = GatewayResponse(
            request_id=gateway_request.request_id,
            trace_id=gateway_request.trace_id,
            session_id=session_id,
            user_id=user_id,
            response_text=final_content,
            memory_write_summary=(
                dict(tool_call_outcome.get("memory_visibility") or {})
                if isinstance(tool_call_outcome.get("memory_visibility"), dict)
                else {}
            ),
            status="success",
        )
        payload = adapter.emit_response(gateway_response)
        if self.event_emitter:
            await self.event_emitter.emit(
                EventType.RESPONSE_SYNTHESIZED,
                {
                    "request_id": request.id,
                    "trace_id": gateway_request.trace_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": "success",
                },
            )
            await self.event_emitter.emit(
                EventType.GATEWAY_RUN_FINISHED,
                {
                    "request_id": request.id,
                    "trace_id": gateway_request.trace_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": "success",
                },
            )
        return GatewayProtocol.create_response(request.id, True, payload)
    except Exception as e:
        logger.error(f"Error handling chat: {e}")
        if self.event_emitter:
            await self.event_emitter.emit(
                EventType.GATEWAY_RUN_FINISHED,
                {
                    "request_id": request.id,
                    "session_id": request.params.get("session_id"),
                    "user_id": self._resolve_request_user_id(connection, request),
                    "status": "failed",
                    "error": str(e),
                },
            )
        return GatewayProtocol.create_response(request.id, False, error=str(e))


async def handle_chat_confirm(self, connection, request):
    """Handle tool-confirmation continuation for chat turn."""
    try:
        if not self.message_manager:
            return GatewayProtocol.create_response(
                request.id, False, error="Message manager not initialized"
            )
        if not self.conversation_service:
            return GatewayProtocol.create_response(
                request.id, False, error="Conversation service not initialized"
            )

        user_id = self._resolve_request_user_id(connection, request)
        session_id = request.params.get("session_id")
        tool_call_id = request.params.get("tool_call_id")
        action = request.params.get("action")
        if not session_id or not tool_call_id:
            return GatewayProtocol.create_response(
                request.id, False, error="session_id and tool_call_id are required"
            )

        run_context = self._build_run_context(
            request=request,
            session_id=session_id,
            user_id=user_id,
            channel_id=str(request.params.get("channel") or "web"),
            input_payload=request.params,
        )

        pending = self.message_manager.get_pending_confirmation(session_id, user_id=user_id)
        if not pending:
            return GatewayProtocol.create_response(
                request.id, False, error="no pending tool confirmation"
            )
        if pending.get("tool_call_id") != tool_call_id:
            return GatewayProtocol.create_response(
                request.id, False, error="tool_call_id mismatch"
            )

        confirmation_type = str(pending.get("confirmation_type", "tool")).strip().lower()
        if confirmation_type == "reasoning_outcome":
            if action not in {"approve", "reject"}:
                return GatewayProtocol.create_response(
                    request.id, False, error="action must be approve or reject"
                )
            approved = action == "approve"
            if not self.reasoning_service:
                return GatewayProtocol.create_response(
                    request.id, False, error="Reasoning service not initialized"
                )
            saved = self.reasoning_service.confirm_outcome(
                review_id=tool_call_id,
                approve=approved,
            )
            self.message_manager.clear_pending_confirmation(session_id, user_id=user_id)
            if approved:
                note = (
                    "Reasoning path marked as successful and saved as reusable template."
                    if saved
                    else "Marked as successful, but failed to save template."
                )
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {"status": "success", "trace_id": run_context.trace_id, "session_id": session_id, "response": note},
                )
            return GatewayProtocol.create_response(
                request.id,
                True,
                {
                    "status": "rejected",
                    "trace_id": run_context.trace_id,
                    "session_id": session_id,
                    "response": "Marked as not successful. Reasoning template was not saved.",
                },
            )

        if action == "reject":
            turn_id = pending.get("turn_id")
            if turn_id:
                self.message_manager.abort_turn(session_id, turn_id, user_id=user_id)
            self.message_manager.clear_pending_confirmation(session_id, user_id=user_id)
            return GatewayProtocol.create_response(
                request.id,
                True,
                {"status": "rejected", "trace_id": run_context.trace_id, "session_id": session_id, "response": "Tool execution rejected."},
            )
        if action != "approve":
            return GatewayProtocol.create_response(
                request.id, False, error="action must be approve or reject"
            )

        current_messages = pending.get("current_messages", [])
        turn_id = pending.get("turn_id")
        tool_result_blocks = []
        try:
            all_tool_calls = pending.get("pending_tool_calls", [])
            if not all_tool_calls:
                all_tool_calls = [
                    {
                        "name": pending.get("tool_name"),
                        "args": pending.get("args", {}),
                        "id": pending.get("tool_call_id"),
                    }
                ]

            if not self.mcp_manager:
                raise RuntimeError("mcp manager not initialized")
            tool_result_blocks = await execute_tool_calls(
                all_tool_calls,
                self.mcp_manager,
                session_id=session_id,
                approved_call_ids={tool_call_id},
                tool_executor=lambda name, payload: self._execute_tool_for_chat(
                    name,
                    payload,
                    session_id=session_id,
                    user_id=user_id,
                    request_id=request.id,
                    connection_id=connection.connection_id,
                    run_context=run_context,
                ),
            )
        except Exception as e:
            if isinstance(e, ToolConfirmationRequired):
                new_pending = {
                    "status": "needs_confirmation",
                    "tool_call_id": e.tool_call_id,
                    "tool_name": e.tool_name,
                    "args": e.tool_args,
                    "current_messages": current_messages,
                    "pending_tool_calls": e.all_tool_calls,
                    "content": pending.get("content", ""),
                    "turn_id": turn_id,
                }
                self.message_manager.set_pending_confirmation(
                    session_id, new_pending, user_id=user_id
                )
                return GatewayProtocol.create_response(
                    request.id,
                    True,
                    {
                        "status": "needs_confirmation",
                        "trace_id": run_context.trace_id,
                        "session_id": session_id,
                        "tool_call_id": e.tool_call_id,
                        "tool_name": e.tool_name,
                        "args": e.tool_args,
                        "response": f"Tool `{e.tool_name}` requires confirmation.",
                    },
                )
            logger.error(f"resume tool execution failed: {e}")
            tool_result_blocks = [{"type": "text", "text": f"tool execution error: {e}"}]

        tool_result_blocks.append(
            {"type": "text", "text": "User approved tool execution. Continue based on these results."}
        )
        observation_message = {"role": "user", "content": tool_result_blocks}

        messages = list(current_messages)
        messages.append({"role": "assistant", "content": pending.get("content", "")})
        messages.append(observation_message)

        user_config = None
        if self.config_service:
            user_config = self.config_service.get_merged_config(user_id)
        self.message_manager.clear_pending_confirmation(session_id, user_id=user_id)

        conversation_input = ConversationRunInput(
            messages=messages,
            user_config=user_config,
            session_id=session_id,
            user_id=user_id,
            run_context=run_context,
            tool_executor=lambda name, payload: self._execute_tool_for_chat(
                name,
                payload,
                session_id=session_id,
                user_id=user_id,
                request_id=request.id,
                connection_id=connection.connection_id,
                run_context=run_context,
                user_config=user_config,
            ),
        )
        await self._emit_gateway_event(
            event_type=EventType.CONVERSATION_RUN_STARTED,
            trace_id=run_context.trace_id,
            request_id=request.id,
            session_id=session_id,
            user_id=user_id,
            payload={"service": "conversation_service"},
            tags=["conversation"],
        )
        conversation_output = await self.conversation_service.run_conversation(conversation_input)
        if isinstance(conversation_output, dict):
            tool_call_outcome = conversation_output
        else:
            raw_payload = getattr(conversation_output, "raw", None)
            if isinstance(raw_payload, dict):
                tool_call_outcome = raw_payload
            else:
                tool_call_outcome = {
                    "status": str(getattr(conversation_output, "status", "success") or "success"),
                    "content": str(getattr(conversation_output, "content", "") or ""),
                }

        if tool_call_outcome.get("status") == "needs_confirmation":
            next_pending = dict(tool_call_outcome)
            next_pending["current_messages"] = messages
            next_pending["turn_id"] = turn_id
            self.message_manager.set_pending_confirmation(
                session_id, next_pending, user_id=user_id
            )
            return GatewayProtocol.create_response(
                request.id,
                True,
                {
                    "status": "needs_confirmation",
                    "trace_id": run_context.trace_id,
                    "session_id": session_id,
                    "tool_call_id": tool_call_outcome.get("tool_call_id"),
                    "tool_name": tool_call_outcome.get("tool_name"),
                    "args": tool_call_outcome.get("args"),
                    "response": f"Tool `{tool_call_outcome.get('tool_name')}` requires confirmation.",
                },
            )

        final_content = tool_call_outcome.get("content", "")
        if turn_id:
            committed = self.message_manager.commit_turn(
                session_id=session_id,
                turn_id=turn_id,
                assistant_content=final_content,
                user_id=user_id,
            )
            if not committed:
                return GatewayProtocol.create_response(
                    request.id, False, error="failed to commit confirmed turn"
                )
        else:
            self.message_manager.add_message(session_id, "assistant", final_content, user_id)

        return GatewayProtocol.create_response(
            request.id,
            True,
            {"status": "success", "trace_id": run_context.trace_id, "session_id": session_id, "response": final_content},
        )
    except Exception as e:
        logger.error(f"Error handling chat confirm: {e}")
        return GatewayProtocol.create_response(request.id, False, error=str(e))

