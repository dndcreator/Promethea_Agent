from __future__ import annotations

from typing import Optional, Tuple


def normalize_user_id(user_id: Optional[str]) -> str:
    uid = str(user_id or "default_user").strip()
    return uid or "default_user"


def user_node_id(user_id: Optional[str]) -> str:
    uid = normalize_user_id(user_id)
    return uid if uid.startswith("user_") else f"user_{uid}"


def scoped_session_id(session_id: str, user_id: Optional[str]) -> str:
    """
    Build a user-scoped logical session id for memory graph.
    """
    return f"{normalize_user_id(user_id)}::{session_id}"


def session_node_id(session_id: str, user_id: Optional[str]) -> str:
    return f"session_{scoped_session_id(session_id, user_id)}"


def resolve_owned_session_id(connector, session_id: str, user_id: Optional[str]) -> Optional[str]:
    """
    Resolve session id owned by current user.
    Return logical session id (without `session_` prefix):
    - scoped id first
    - legacy raw id fallback
    """
    if not connector:
        return scoped_session_id(session_id, user_id)

    uid = user_node_id(user_id)
    scoped = scoped_session_id(session_id, user_id)
    candidates = [f"session_{scoped}", f"session_{session_id}"]
    try:
        rows = connector.query(
            """
            MATCH (s:Session)-[:OWNED_BY]->(u:User {id: $user_node_id})
            WHERE s.id IN $candidate_ids
            RETURN s.id AS id
            LIMIT 1
            """,
            {
                "user_node_id": uid,
                "candidate_ids": candidates,
            },
        )
        if not rows:
            return None
        sid = str(rows[0].get("id") or "")
        if sid.startswith("session_"):
            return sid[len("session_") :]
        return sid
    except Exception:
        return None


def ensure_session_owned(connector, session_id: str, user_id: Optional[str]) -> Tuple[bool, str]:
    """
    Returns:
    - owned: whether user owns this session in memory graph
    - resolved_session_id: owned scoped/legacy session id when owned,
      otherwise default scoped id for future writes
    """
    resolved = resolve_owned_session_id(connector, session_id, user_id)
    if resolved:
        return True, resolved
    return False, scoped_session_id(session_id, user_id)
