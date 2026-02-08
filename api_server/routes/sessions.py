from __future__ import annotations

from fastapi import APIRouter, HTTPException
import logging

from ..message_manager import message_manager


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/sessions")
async def list_sessions():
    try:
        sessions_info = message_manager.get_all_sessions_info()

        sessions = []
        for sid, info in sessions_info.items():
            if info:
                sessions.append(info)
        sessions.sort(key=lambda x: x.get("last_activity", 0), reverse=True)

        return {"status": "success", "sessions": sessions, "total": len(sessions_info)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    try:
        session_info = message_manager.get_session(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")

        messages = message_manager.get_messages(session_id)

        return {
            "status": "success",
            "session_id": session_id,
            "session_info": session_info,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(e)}")

