from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.tool_service import ToolInvocationContext


def _resolve_user_session(
    args: Dict[str, Any],
    ctx: Optional[ToolInvocationContext],
) -> tuple[str, str]:
    user_id = str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip() or "default_user"
    session_id = str((args or {}).get("session_id") or (ctx.session_id if ctx else "") or "default").strip() or "default"
    return user_id, session_id


class SessionRecentMessagesTool:
    tool_id = "session.recent_messages"
    name = "session.recent_messages"
    description = "Get recent messages in current session."
    official = True
    official_domain = "session"

    def __init__(self, *, message_manager: Any) -> None:
        self.message_manager = message_manager

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, session_id = _resolve_user_session(args, ctx)
        count = int((args or {}).get("count") or 20)
        count = max(1, min(count, 200))
        rows = self.message_manager.get_recent_messages(
            session_id,
            count=count,
            user_id=user_id,
        )
        return {"session_id": session_id, "user_id": user_id, "count": len(rows), "messages": rows}


class SessionInfoTool:
    tool_id = "session.info"
    name = "session.info"
    description = "Get summary info for a session."
    official = True
    official_domain = "session"

    def __init__(self, *, message_manager: Any) -> None:
        self.message_manager = message_manager

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, session_id = _resolve_user_session(args, ctx)
        info = self.message_manager.get_session_info(session_id, user_id=user_id)
        return {"ok": bool(info), "info": info}


class SessionListTool:
    tool_id = "session.list"
    name = "session.list"
    description = "List sessions for current user."
    official = True
    official_domain = "session"

    def __init__(self, *, message_manager: Any) -> None:
        self.message_manager = message_manager

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id = str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip() or "default_user"
        sessions = self.message_manager.get_all_sessions_info(user_id=user_id)
        rows = list((sessions or {}).values())
        rows = [x for x in rows if isinstance(x, dict)]
        rows.sort(key=lambda x: float(x.get("last_activity") or 0.0), reverse=True)
        return {"user_id": user_id, "count": len(rows), "sessions": rows}

