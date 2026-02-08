from __future__ import annotations

from fastapi import APIRouter, HTTPException
import logging

from ..schemas import FollowUpRequest
from ..message_manager import message_manager
from .. import state


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/followup")
async def handle_followup(request: FollowUpRequest):
    """处理气泡追问（手动选中文本）"""
    try:
        templates = {
            "why": "为什么说「{text}」？请用100字以内简短解释推理依据和前提。",
            "risk": "「{text}」有什么潜在的坑或代价？请用100字以内诚实说明。",
            "alternative": "除了「{text}」，还有什么替代方案？请用100字以内列举2-3个方案并简要对比。",
        }

        if request.query_type == "custom" and request.custom_query:
            user_query = f"{request.custom_query}\n\n相关内容：「{request.selected_text}」"
        else:
            user_query = templates.get(request.query_type, templates["why"]).format(text=request.selected_text[:100])

        # 最近 6 条消息 = 3 轮对话
        messages = []
        recent_messages = message_manager.get_recent_messages(request.session_id, count=6)
        if recent_messages:
            messages = [{"role": msg["role"], "content": msg["content"]} for msg in recent_messages]

        messages.append({"role": "user", "content": user_query})

        response = await state.conversation.call_llm(messages)

        return {"status": "success", "response": response.get("content", ""), "query": user_query}

    except Exception as e:
        logger.error(f"追问处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"追问处理失败: {str(e)}")

