from __future__ import annotations

from typing import Any, Dict, Optional

from gateway.capability_service import ToolInvocationContext
from gateway.tools.schema import boolean, input_object, integer, text


def _resolve_user_session(
    args: Dict[str, Any],
    ctx: Optional[ToolInvocationContext],
) -> tuple[str, str]:
    user_id = str((args or {}).get("user_id") or (ctx.user_id if ctx else "") or "default_user").strip() or "default_user"
    session_id = str((args or {}).get("session_id") or (ctx.session_id if ctx else "") or "default").strip() or "default"
    return user_id, session_id


class MemoryGetContextTool:
    input_schema = input_object({"query": text()}, required=("query",))
    tool_id = "memory.get_context"
    side_effect_level = "read_only"
    name = "memory.get_context"
    description = "Recall memory context for a query."
    domain = "memory"
    presentation = {
        "kind": "memory",
        "title": "Recall memory",
        "title_i18n": {"zh": "回忆", "en": "Recall memory"},
        "subject_arg": "query",
        "references": [{"kind": "memory", "arg": "query"}],
    }

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

    @staticmethod
    def result_summary(result: Any) -> str:
        if not isinstance(result, dict):
            return "Memory recall completed"
        context = " ".join(str(result.get("context") or "").split())
        if context:
            return context[:420]
        return "No relevant memory was recalled"

    @staticmethod
    def result_metadata(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        return {
            "kind": "memory_recall",
            "query": str(result.get("query") or ""),
            "context_length": int(result.get("context_length") or 0),
        }


class MemoryListEntriesTool:
    input_schema = input_object(
        {"scope": text(), "query": text(), "limit": integer(minimum=1, maximum=500), "include_archived": boolean()}
    )
    tool_id = "memory.list_entries"
    side_effect_level = "read_only"
    name = "memory.list_entries"
    description = "List memory entries for current user."
    domain = "memory"

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
    input_schema = input_object(
        {"content": text(), "memory_type": text(), "source_layer": text()},
        required=("content",),
    )
    tool_id = "memory.create_entry"
    side_effect_level = "workspace_write"
    name = "memory.create_entry"
    description = "Create a memory entry manually."
    domain = "memory"

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
    input_schema = input_object({"incremental": boolean()})
    tool_id = "memory.summarize_session"
    side_effect_level = "workspace_write"
    name = "memory.summarize_session"
    description = "Trigger session memory summarization."
    domain = "memory"

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
    input_schema = input_object({"limit": integer(minimum=1, maximum=100)})
    tool_id = "memory.recall_runs"
    side_effect_level = "read_only"
    name = "memory.recall_runs"
    description = "Inspect recent memory recall runs."
    domain = "memory"

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
        return {
            "ok": True,
            "available": True,
            "scope": {"user_id": user_id, "session_id": session_id},
            "count": len(rows),
            "runs": rows,
        }
