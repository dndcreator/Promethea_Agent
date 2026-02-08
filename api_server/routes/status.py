from __future__ import annotations

from fastapi import APIRouter

from .. import state


router = APIRouter()


@router.get("/status")
async def get_status():
    """获取服务状态"""
    # 检查记忆系统状态（通过插件注册表获取）
    memory_status = False
    try:
        from core.services import get_memory_service

        adapter = get_memory_service()
        if adapter:
            memory_status = adapter.is_enabled()
    except Exception:
        pass

    return {"status": "running", "conversation_ready": state.conversation is not None, "memory_active": memory_status}

