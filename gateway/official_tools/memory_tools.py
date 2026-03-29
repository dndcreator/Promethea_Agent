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


class MemoryGetContextTool:
    tool_id = "memory.get_context"
    name = "memory.get_context"
    description = "Recall memory context for a query."
    official = True
    official_domain = "memory"

    def __init__(self, *, memory_service: Any) -> None:
        self.memory_service = memory_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        query = str((args or {}).get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        user_id, session_id = _resolve_user_session(args, ctx)
        context = await self.memory_service.get_context(
            query=query,
            session_id=session_id,
            user_id=user_id,
            run_context=None,
        )
        return {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "context": str(context or ""),
            "context_length": len(str(context or "")),
        }


class MemoryListEntriesTool:
    tool_id = "memory.list_entries"
    name = "memory.list_entries"
    description = "List memory entries for current user."
    official = True
    official_domain = "memory"

    def __init__(self, *, memory_service: Any) -> None:
        self.memory_service = memory_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, session_id = _resolve_user_session(args, ctx)
        scope = str((args or {}).get("scope") or "all")
        query = str((args or {}).get("query") or "")
        limit = int((args or {}).get("limit") or 100)
        limit = max(1, min(limit, 500))
        include_archived = bool((args or {}).get("include_archived", False))
        out = self.memory_service.list_entries(
            user_id=user_id,
            scope=scope,
            session_id=session_id,
            query=query,
            limit=limit,
            include_archived=include_archived,
        )
        return out


class MemoryCreateEntryTool:
    tool_id = "memory.create_entry"
    name = "memory.create_entry"
    description = "Create a memory entry manually."
    official = True
    official_domain = "memory"

    def __init__(self, *, memory_service: Any) -> None:
        self.memory_service = memory_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        content = str((args or {}).get("content") or "").strip()
        if not content:
            raise ValueError("content is required")
        user_id, session_id = _resolve_user_session(args, ctx)
        memory_type = str((args or {}).get("memory_type") or "preference").strip().lower()
        source_layer = str((args or {}).get("source_layer") or "direct").strip().lower()
        return self.memory_service.create_entry(
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            session_id=session_id,
            source_layer=source_layer,
        )


class MemorySummarizeSessionTool:
    tool_id = "memory.summarize_session"
    name = "memory.summarize_session"
    description = "Trigger session memory summarization."
    official = True
    official_domain = "memory"

    def __init__(self, *, memory_service: Any) -> None:
        self.memory_service = memory_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, session_id = _resolve_user_session(args, ctx)
        incremental = bool((args or {}).get("incremental", False))
        return await self.memory_service.summarize_session(
            session_id=session_id,
            user_id=user_id,
            incremental=incremental,
        )


class MemoryRecallRunsTool:
    tool_id = "memory.recall_runs"
    name = "memory.recall_runs"
    description = "Inspect recent memory recall runs."
    official = True
    official_domain = "memory"

    def __init__(self, *, memory_service: Any) -> None:
        self.memory_service = memory_service

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        user_id, session_id = _resolve_user_session(args, ctx)
        limit = int((args or {}).get("limit") or 20)
        limit = max(1, min(limit, 100))
        rows = self.memory_service.list_recall_runs(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        return {"count": len(rows), "runs": rows}

