from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MemoryStore(ABC):
    """Backend-neutral memory store contract."""

    @abstractmethod
    def is_ready(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_context(self, *, query: str, session_id: str, user_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def collect_recall_candidates(
        self,
        *,
        query: str,
        session_id: str,
        user_id: str,
        top_k: int = 8,
        mode: str = "fast",
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def export_mef(self, *, user_id: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def import_mef(self, payload: Dict[str, Any], *, merge: bool = True) -> Dict[str, Any]:
        raise NotImplementedError

