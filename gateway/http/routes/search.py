from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from ..dispatcher import get_gateway_server
from ..user_file_store import user_file_store
from .auth import get_current_user_id


router = APIRouter()


@router.get("/search")
async def unified_search(
    q: str,
    limit_sessions: int = 20,
    limit_files: int = 20,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")

    gateway_server = get_gateway_server()
    message_manager = getattr(gateway_server, "message_manager", None)
    if message_manager is None:
        raise HTTPException(status_code=503, detail="Message manager not initialized")

    sessions: List[Dict[str, Any]] = []
    if hasattr(message_manager, "list_sessions"):
        sessions = list(
            message_manager.list_sessions(
                user_id=user_id,
                query=query,
                pinned_only=False,
                limit=max(1, min(int(limit_sessions), 100)),
            )
        )
    files = user_file_store.search_files(
        user_id=user_id,
        query=query,
        limit=max(1, min(int(limit_files), 100)),
    )
    return {
        "status": "success",
        "query": query,
        "results": {
            "sessions": sessions,
            "files": files,
        },
        "totals": {
            "sessions": len(sessions),
            "files": len(files),
        },
    }
