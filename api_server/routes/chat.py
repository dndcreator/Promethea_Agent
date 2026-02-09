from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger

from ..schemas import ChatResponse, ConfirmToolRequest
from ..user_manager import user_manager
from ..message_manager import message_manager
from .. import state
from .auth import get_current_user_id
from agentkit.mcp.tool_call import execute_tool_calls, ToolConfirmationRequired


router = APIRouter()


@router.post("/chat/confirm")
async def confirm_tool(request: ConfirmToolRequest, user_id: str = Depends(get_current_user_id)):
    """处理工具执行确认"""
    session_id = request.session_id
    pending = message_manager.get_pending_confirmation(session_id)

    if not pending:
        raise HTTPException(status_code=400, detail="没有待确认的工具调用")

    if pending["tool_call_id"] != request.tool_call_id:
        raise HTTPException(status_code=400, detail="工具调用ID不匹配")

    if request.action == "reject":
        message_manager.clear_pending_confirmation(session_id)
        return {"status": "rejected", "message": "已拒绝执行"}

    if request.action == "approve":
        current_messages = pending["current_messages"]

        # 1. 恢复执行：调用 execute_tool_calls 并传入批准的 ID
        # 这样可以确保：
        # - 被批准的工具会被执行（通过 approved_call_ids 白名单）
        # - 同批次的其他安全工具也会被执行
        # - 同批次的其他不安全工具会再次触发 ToolConfirmationRequired 异常（链式确认）

        tool_result_blocks = []
        try:
            # 从 pending 状态中恢复所有待执行的工具列表
            all_tool_calls = pending.get("pending_tool_calls", [])
            if not all_tool_calls:
                # 兼容旧数据（虽然理论上不会有）
                all_tool_calls = [
                    {
                        "name": pending["tool_name"],
                        "args": pending["args"],
                        "id": pending["tool_call_id"],
                    }
                ]

            tool_result_blocks = await execute_tool_calls(
                all_tool_calls,
                state.mcp_manager,
                session_id=session_id,
                approved_call_ids={request.tool_call_id},
            )

        except Exception as e:
            # 检查是否是新的确认请求（链式确认）
            if isinstance(e, ToolConfirmationRequired):
                # 再次挂起状态
                new_pending = {
                    "status": "needs_confirmation",
                    "tool_call_id": e.tool_call_id,
                    "tool_name": e.tool_name,
                    "args": e.args,
                    "current_messages": current_messages,
                    "pending_tool_calls": e.all_tool_calls,
                    "content": pending["content"],
                }
                message_manager.set_pending_confirmation(session_id, new_pending)

                return ChatResponse(
                    response=f"执行工具 {e.tool_name} 需要您的确认。",
                    session_id=session_id,
                    status="needs_confirmation",
                    tool_call_id=e.tool_call_id,
                    tool_name=e.tool_name,
                    args=e.args,
                )

            # 其他错误
            logger.error(f"恢复执行工具失败: {e}")
            tool_result_blocks = [{"type": "text", "text": f"执行出错: {str(e)}"}]

        # 2. 构建 Observation 消息
        observation_message = {
            "role": "user",
            "content": tool_result_blocks,
        }
        tool_result_blocks.append(
            {
                "type": "text",
                "text": "\n(用户已确认并执行) 请根据以上结果继续。",
            }
        )

        # 3. 恢复消息历史
        messages = current_messages
        messages.append({"role": "assistant", "content": pending["content"]})
        messages.append(observation_message)

        # 4. 继续对话循环
        user_config = user_manager.get_user_config(user_id)
        message_manager.clear_pending_confirmation(session_id)

        tool_call_outcome = await state.conversation.run_chat_loop(
            messages, user_config, session_id=session_id
        )

        # 处理结果（如果再次需要确认，返回新的确认信息）
        if tool_call_outcome.get("status") == "needs_confirmation":
            message_manager.set_pending_confirmation(session_id, tool_call_outcome)
            return ChatResponse(
                response=f"执行工具 {tool_call_outcome['tool_name']} 需要您的确认。",
                session_id=session_id,
                status="needs_confirmation",
                tool_call_id=tool_call_outcome.get("tool_call_id"),
                tool_name=tool_call_outcome.get("tool_name"),
                args=tool_call_outcome.get("args"),
            )

        final_content = tool_call_outcome.get("content", "")

        # 记录最后的助手回复
        message_manager.add_message(session_id, "assistant", final_content, user_id)

        return ChatResponse(
            response=final_content, session_id=session_id, status="success"
        )
