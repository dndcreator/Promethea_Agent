from pydantic import BaseModel, Field
import time
from typing import Dict, List, Optional
import logging
import uuid

try:
    # pydantic v2
    from pydantic import field_validator
except Exception:  # pragma: no cover
    field_validator = None

from .session_store import SessionStorage

logger = logging.getLogger(__name__)


def _model_to_dict(model: BaseModel) -> Dict:
    """Convert a Pydantic model to dict for both v1 and v2."""
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class Message(BaseModel):
    role: str
    content: str


class Session(BaseModel):
    """
    Session model.
    - Use Unix epoch seconds; frontend can render via new Date(ts * 1000)
    - For legacy monotonic timestamps written by older versions, we reset
      them to current wall-clock time on load.
    """

    created_at: float = Field(default_factory=time.time)
    last_activity: float = Field(default_factory=time.time)
    title: str = "New Chat"
    agent_type: str = "default"
    messages: List[Message] = Field(default_factory=list)

    pending_confirmation: Optional[Dict] = None
    pending_turns: Dict[str, Dict] = Field(default_factory=dict)
    completed_turn_ids: List[str] = Field(default_factory=list)

    if field_validator:

        @field_validator("created_at", "last_activity", mode="before")
        @classmethod
        def _coerce_epoch_seconds(cls, v):
            """Normalize timestamps to Unix epoch seconds."""
            try:
                if v is None:
                    return time.time()
                v = float(v)
            except Exception:
                return time.time()

            # Treat very small values as legacy monotonic timestamps and reset them.
            if v < 1_000_000_000:
                return time.time()
            return v
    

class MessageManager:
    """Manage chat sessions/messages and integrate with the memory system."""

    def __init__(self):
        # In-memory session cache (with persistence to disk).
        self.session_store = SessionStorage()
        self.session: Dict[str, Session] = {}
        
        # Load persisted sessions from disk if any.
        try:
            saved_sessions = self.session_store.load_all()
            self.session.update(saved_sessions)
            if saved_sessions:
                logger.info(f"Loaded {len(saved_sessions)} sessions from disk")
        except Exception as e:
            logger.warning(f"Failed to load sessions from disk: {e}")
        
        # Configure maximum history length per session.
        try:
            from config import config

            self.max_history_rounds = config.api.max_history_rounds
            self.max_messages_per_session = self.max_history_rounds * 2
        except ImportError:
            self.max_history_rounds = 10
            self.max_messages_per_session = 20
            logger.warning("Failed to load config, using default history limits")
        
        # Attach memory system (if available via plugin registration).
        self.memory_adapter = None
        try:
            from core.services import get_memory_service

            self.memory_adapter = get_memory_service()
            if self.memory_adapter and self.memory_adapter.is_enabled():
                logger.info("Memory system enabled and attached to MessageManager")
            else:
                logger.info("Memory system is disabled")
        except ImportError:
            logger.debug(
                "Core services module not installed, skip memory-system integration"
            )
        except Exception as e:
            logger.warning(f"Memory system initialization failed: {e}")

    _SESSION_KEY_SEP = "::"

    def _normalize_user_id(self, user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip()
        return uid or "default_user"

    def _make_session_key(self, session_id: str, user_id: Optional[str]) -> str:
        return f"{self._normalize_user_id(user_id)}{self._SESSION_KEY_SEP}{session_id}"

    def _split_session_key(self, key: str):
        if self._SESSION_KEY_SEP in key:
            user_id, session_id = key.split(self._SESSION_KEY_SEP, 1)
            return user_id, session_id
        return None, key

    def _resolve_session_key(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        if user_id is not None:
            key = self._make_session_key(session_id, user_id)
            if key in self.session:
                return key
            # compatibility: legacy unscoped sessions are treated as default_user
            if self._normalize_user_id(user_id) == "default_user" and session_id in self.session:
                return session_id
            return None
        # backward compatibility for legacy unscoped callers
        return session_id if session_id in self.session else None

    def generate_session_id(self) -> str:
        """Generate a new session ID."""
        return str(uuid.uuid4())

    @staticmethod
    def _generate_session_title(text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return "New Chat"
        one_line = " ".join(raw.split())
        return one_line[:40] + ("..." if len(one_line) > 40 else "")
    
    def create_session(
        self,
        session_id: Optional[str] = None,
        user_id: str = "default_user",
    ) -> str:
        """Create a new session."""
        if not session_id:
            session_id = self.generate_session_id()
        
        key = self._make_session_key(session_id, user_id)
        self.session[key] = Session()
        logger.info(f"Created new session {session_id}")

        self.session_store.save_all(self.session)
        return session_id
    
    def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Get full session info (excluding pending confirmations)."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            return None
        session = self.session.get(key)
        if not session:
            return None
        return {
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "title": session.title,
            "agent_type": session.agent_type,
            "messages": [_model_to_dict(m) for m in session.messages],
        }
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "default_user",
        sync_memory: bool = True,
    ) -> bool:
        """Append a message to a session and optionally sync to memory."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return False
        
        session = self.session[key]
        session.messages.append(Message(role=role, content=content))
        session.last_activity = time.time()

        if len(session.messages) > self.max_messages_per_session:
            session.messages = session.messages[-self.max_messages_per_session :]
        
        logger.debug(f"Session {session_id} new message: {role} - {content[:50]}...")

        self.session_store.save_all(self.session)
        
        # Sync to memory system asynchronously (if enabled) to avoid blocking main flow.
        if sync_memory and self.memory_adapter and self.memory_adapter.is_enabled():
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None, 
                    self._sync_to_memory, 
                    session_id,
                    role,
                    content,
                    user_id,
                )
                logger.debug(f"Triggered async memory sync for session {session_id}")
            except Exception as e:
                logger.warning(f"Memory system sync trigger failed: {e}")

        return True

    def begin_turn(
        self,
        session_id: str,
        turn_id: str,
        user_role: str,
        user_content: str,
        user_id: str = "default_user",
    ) -> bool:
        """
        Begin a conversation turn (stored as pending, without writing to final
        message list yet).

        Idempotent for the same (session_id, turn_id, user_content, user_id).
        """
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return False
        if not turn_id:
            logger.warning("begin_turn missing turn_id")
            return False

        session = self.session[key]
        if turn_id in session.completed_turn_ids:
            return True
        existing = session.pending_turns.get(turn_id)
        if existing:
            # Idempotent retry: same turn_id is allowed only for the same payload.
            same_content = (
                existing.get("user_role") == user_role
                and existing.get("user_content") == user_content
                and existing.get("user_id") == user_id
            )
            return same_content

        session.pending_turns[turn_id] = {
            "user_role": user_role,
            "user_content": user_content,
            "user_id": user_id,
            "started_at": time.time(),
        }
        if not session.messages and (not session.title or session.title == "New Chat"):
            session.title = self._generate_session_title(user_content)
        session.last_activity = time.time()
        self.session_store.save_all(self.session)
        return True

    def commit_turn(
        self,
        session_id: str,
        turn_id: str,
        assistant_content: str,
        user_id: str = "default_user",
    ) -> bool:
        """
        Commit a turn: write user + assistant messages into the final message
        list exactly once for the given (session_id, turn_id).
        """
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return False
        if not turn_id:
            logger.warning("commit_turn missing turn_id")
            return False

        session = self.session[key]
        if turn_id in session.completed_turn_ids:
            return True

        turn = session.pending_turns.pop(turn_id, None)
        if not turn:
            logger.warning(f"commit_turn pending turn not found: {session_id}:{turn_id}")
            return False

        session.messages.append(
            Message(role=turn.get("user_role", "user"), content=turn.get("user_content", ""))
        )
        session.messages.append(
            Message(role="assistant", content=assistant_content or "")
        )
        session.last_activity = time.time()

        if len(session.messages) > self.max_messages_per_session:
            session.messages = session.messages[-self.max_messages_per_session :]

        session.completed_turn_ids.append(turn_id)
        if len(session.completed_turn_ids) > 1000:
            session.completed_turn_ids = session.completed_turn_ids[-1000:]

        self.session_store.save_all(self.session)

        # Keep memory graph consistent with turn-based write path.
        if self.memory_adapter and self.memory_adapter.is_enabled():
            import asyncio

            user_role = turn.get("user_role", "user")
            user_content = turn.get("user_content", "")
            assistant_content_safe = assistant_content or ""
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None,
                    self._sync_to_memory,
                    session_id,
                    user_role,
                    user_content,
                    user_id,
                )
                loop.run_in_executor(
                    None,
                    self._sync_to_memory,
                    session_id,
                    "assistant",
                    assistant_content_safe,
                    user_id,
                )
                logger.debug(f"Triggered memory sync from commit_turn for session {session_id}")
            except Exception as e:
                logger.warning(f"Memory sync trigger from commit_turn failed: {e}")
        return True

    def abort_turn(
        self,
        session_id: str,
        turn_id: str,
        user_id: str = "default_user",
    ) -> bool:
        """Abort a pending turn without committing user/assistant messages."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            return False
        session = self.session[key]
        if turn_id in session.pending_turns:
            session.pending_turns.pop(turn_id, None)
            session.last_activity = time.time()
            self.session_store.save_all(self.session)
            return True
        return False
    
    def _sync_to_memory(self, session_id: str, role: str, content: str, user_id: str = "default_user"):
        """Background sync: write to memory system and trigger maintenance tasks."""
        try:
            if not self.memory_adapter or not self.memory_adapter.is_enabled():
                return

            # 1. Append to hot-layer memory.
            try:
                self.memory_adapter.add_message(session_id, role, content, user_id)
            except Exception as e:
                logger.warning(f"Memory system add_message failed: {e}")

            # 2. Trigger maintenance logic (e.g. clustering/summarization/decay).
            try:
                if hasattr(self.memory_adapter, "on_message_saved"):
                    self.memory_adapter.on_message_saved(session_id, role, user_id)
            except Exception as e:
                logger.warning(f"Memory system maintenance trigger failed: {e}")

            logger.debug(f"Memory system sync completed: {session_id}")
        except Exception as e:
            logger.warning(f"Memory system internal processing failed: {e}")
    
    def get_messages(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """Get all messages in a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return []
        session = self.session.get(key)
        return [_model_to_dict(m) for m in session.messages]
    
    def get_recent_messages(
        self,
        session_id: str,
        count: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """Get the last N messages in a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return []
        if count is None:
            count = self.max_messages_per_session
        messages = self.get_messages(session_id, user_id=user_id)
        return messages[-count:] if messages else []
    
    def build_conversation(
        self, 
        session_id: str, 
        system_prompt: str,
        current_message: str,
        include_history: bool = True,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """Build a message list for an LLM call."""
        messages: List[Dict] = []
        messages.append({"role": "system", "content": system_prompt})

        if include_history:
            recent_messages = self.get_recent_messages(session_id, user_id=user_id)
            messages.extend(recent_messages)
        
        messages.append({"role": "user", "content": current_message})
        return messages
    
    def get_session_info(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Get summary info for a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if not key:
            logger.warning(f"Session not found: {session_id}")
            return None
        session = self.session.get(key)
        owner_user_id, raw_session_id = self._split_session_key(key)
        last_msg_preview = (
            session.messages[-1].content[:100] + "..." if session.messages else ""
        )
        return {
            "session_id": raw_session_id,
            "user_id": owner_user_id or "default_user",
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "title": session.title,
            "message_count": len(session.messages),
            "conversation_rounds": len(session.messages) // 2,
            "agent_type": session.agent_type,
            "max_history_rounds": self.max_history_rounds,
            "last_message": last_msg_preview,
        }
    
    def get_all_sessions_info(self, user_id: Optional[str] = None) -> Dict[str, Dict]:
        """Get info for all sessions, optionally filtered by user."""
        sessions_info: Dict[str, Dict] = {}
        for sid in self.session.keys():
            owner_user_id, raw_session_id = self._split_session_key(sid)
            if user_id is not None:
                expected = self._normalize_user_id(user_id)
                actual = owner_user_id or "default_user"
                if actual != expected:
                    continue
            sessions_info[sid] = self.get_session_info(
                raw_session_id if owner_user_id is not None else sid,
                user_id=owner_user_id if owner_user_id is not None else "default_user",
            )
        return sessions_info

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if key in self.session:
            del self.session[key]
            logger.info(f"Deleted session: {session_id}")
            self.session_store.save_all(self.session)
            return True
        return False
    
    def clear_all_sessions(self) -> int:
        """Clear all sessions and return the number removed."""
        count = len(self.session)
        self.session.clear()
        logger.info(f"Cleared all sessions: {count}")
        self.session_store.save_all(self.session)
        return count
    
    def cleanup_old_sessions(self, max_age_hours: int = 0) -> int:
        """
        Remove inactive sessions older than max_age_hours.

        Set max_age_hours <= 0 to disable time-based cleanup.
        Returns the number of removed sessions.
        """
        if max_age_hours <= 0:
            return 0

        current_time = time.time()
        expired_session_ids: List[str] = []

        for session_id, session in list(self.session.items()):
            if current_time - session.last_activity > max_age_hours * 3600:
                expired_session_ids.append(session_id)

        for session_id in expired_session_ids:
            del self.session[session_id]
        
        if expired_session_ids:
            logger.info(f"Removed expired sessions: {len(expired_session_ids)}")
            self.session_store.save_all(self.session)
        return len(expired_session_ids)

    def set_pending_confirmation(
        self,
        session_id: str,
        confirmation_data: Dict,
        user_id: Optional[str] = None,
    ) -> bool:
        """Store pending tool confirmation data for a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if key in self.session:
            self.session[key].pending_confirmation = confirmation_data
            self.session_store.save_all(self.session)
            return True
        return False

    def get_pending_confirmation(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """Get the current pending tool-call confirmation state for a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if key in self.session:
            return self.session[key].pending_confirmation
        return None

    def clear_pending_confirmation(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ):
        """Clear pending tool-call confirmation state for a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if key in self.session:
            self.session[key].pending_confirmation = None
            self.session_store.save_all(self.session)

    def set_agent_type(
        self,
        session_id: str,
        agent_type: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Set the agent type bound to a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        if key in self.session:
            self.session[key].agent_type = agent_type
            return True
        return False

    def get_agent_type(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Get the agent type bound to a session."""
        key = self._resolve_session_key(session_id, user_id=user_id)
        session = self.session.get(key) if key else None
        return session.agent_type if session else None


# Global singleton instance for convenient imports.
message_manager = MessageManager()

