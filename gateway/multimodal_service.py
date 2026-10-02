from __future__ import annotations

import json
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ModelEndpoint:
    api_key: str
    base_url: str
    model: str
    source: str = "main"


class MultimodalService:
    """Resolve multimodal model routing without moving conversation policy out of Core."""

    def __init__(self) -> None:
        self._unsupported: Dict[Tuple[str, str], Set[str]] = {}
        self._lock = RLock()

    @staticmethod
    def detect_modalities(messages: Iterable[Dict[str, Any]]) -> Set[str]:
        modalities: Set[str] = set()
        for message in messages or []:
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type in {"image", "image_url", "input_image"}:
                    modalities.add("image")
                elif part_type in {"audio", "input_audio"}:
                    modalities.add("audio")
                elif part_type in {"video", "input_video"}:
                    modalities.add("video")
        return modalities

    def is_known_unsupported(self, endpoint: ModelEndpoint, modalities: Set[str]) -> bool:
        if not modalities:
            return False
        key = (endpoint.base_url.rstrip("/").lower(), endpoint.model.lower())
        with self._lock:
            return bool(modalities.intersection(self._unsupported.get(key, set())))

    def mark_unsupported(self, endpoint: ModelEndpoint, modalities: Set[str]) -> None:
        if not modalities:
            return
        key = (endpoint.base_url.rstrip("/").lower(), endpoint.model.lower())
        with self._lock:
            self._unsupported.setdefault(key, set()).update(modalities)

    @staticmethod
    def is_unsupported_modality_error(error: Exception) -> bool:
        status = getattr(error, "status_code", None)
        if status not in {400, 415, 422}:
            return False
        body = getattr(error, "body", None)
        fragments: List[str] = [str(error)]
        if body is not None:
            try:
                fragments.append(json.dumps(body, ensure_ascii=False, default=str))
            except Exception:
                fragments.append(str(body))
        text = " ".join(fragments).lower()
        modality_terms = ("image", "vision", "audio", "video", "multimodal", "image_url", "input_image")
        unsupported_terms = (
            "not support",
            "unsupported",
            "doesn't support",
            "does not accept",
            "invalid content type",
            "invalid modality",
        )
        return any(term in text for term in modality_terms) and any(term in text for term in unsupported_terms)

    @staticmethod
    def strip_unsupported_parts(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        for raw in messages or []:
            message = dict(raw)
            content = message.get("content")
            if isinstance(content, list):
                text_parts = [
                    part
                    for part in content
                    if isinstance(part, dict) and str(part.get("type") or "").lower() == "text"
                ]
                message["content"] = text_parts if text_parts else ""
            cleaned.append(message)
        return cleaned

    @staticmethod
    def dedicated_endpoint(settings: Optional[Dict[str, Any]]) -> Optional[ModelEndpoint]:
        values = settings if isinstance(settings, dict) else {}
        model = str(values.get("model") or "").strip()
        if not model:
            return None
        return ModelEndpoint(
            api_key=str(values.get("api_key") or ""),
            base_url=str(values.get("base_url") or ""),
            model=model,
            source="multimodal",
        )


multimodal_service = MultimodalService()
