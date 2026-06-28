from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
import uuid


@dataclass
class RuntimeBlock:
    """Canonical material passed into or produced by the LLM I/O hub."""

    source: str
    role: str
    modality: str
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    block_id: str = field(default_factory=lambda: f"rb_{uuid.uuid4().hex}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "source": self.source,
            "role": self.role,
            "modality": self.modality,
            "content": self.content,
            "metadata": dict(self.metadata or {}),
        }


def runtime_block_from_dict(value: Dict[str, Any]) -> RuntimeBlock:
    return RuntimeBlock(
        block_id=str(value.get("block_id") or f"rb_{uuid.uuid4().hex}"),
        source=str(value.get("source") or "unknown"),
        role=str(value.get("role") or "context"),
        modality=str(value.get("modality") or "text"),
        content=value.get("content"),
        metadata=dict(value.get("metadata") or {}),
    )


def normalize_runtime_blocks(values: Iterable[Any]) -> List[RuntimeBlock]:
    blocks: List[RuntimeBlock] = []
    for value in values or []:
        if isinstance(value, RuntimeBlock):
            blocks.append(value)
        elif isinstance(value, dict):
            blocks.append(runtime_block_from_dict(value))
    return blocks


def model_supports_vision(*, model: str = "", user_config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = user_config if isinstance(user_config, dict) else {}
    explicit = cfg.get("vision_enabled")
    if explicit is None and isinstance(cfg.get("api"), dict):
        explicit = cfg["api"].get("vision_enabled")
    if explicit is not None:
        return bool(explicit)

    model_name = str(model or cfg.get("model") or "").strip().lower()
    if not model_name and isinstance(cfg.get("api"), dict):
        model_name = str(cfg["api"].get("model") or "").strip().lower()
    if not model_name:
        return False

    vision_markers = (
        "gpt-4o",
        "gpt-4.1",
        "gpt-5",
        "vision",
        "vl",
        "qwen-vl",
        "gemini",
        "claude-3",
        "claude-sonnet",
        "claude-opus",
    )
    text_only_markers = ("deepseek-chat", "deepseek-reasoner", "text-embedding")
    if any(marker in model_name for marker in text_only_markers):
        return False
    return any(marker in model_name for marker in vision_markers)


class ContextCompiler:
    """Compile RuntimeBlocks into provider-compatible chat message content."""

    def compile_user_content(
        self,
        *,
        user_text: str,
        blocks: Iterable[RuntimeBlock],
        vision_enabled: bool,
    ) -> Any:
        text_parts: List[str] = []
        image_parts: List[Dict[str, Any]] = []
        base_text = str(user_text or "").strip()
        if base_text:
            text_parts.append(base_text)

        for block in normalize_runtime_blocks(blocks):
            if block.role not in {"request", "context", "observation"}:
                continue
            if block.source == "user" and block.role == "request":
                continue
            if block.modality == "image":
                image_url = self._extract_image_url(block.content)
                if image_url and vision_enabled:
                    image_parts.append({"type": "image_url", "image_url": {"url": image_url}})
                    caption = self._format_image_caption(block)
                    if caption:
                        text_parts.append(caption)
                else:
                    text_parts.append(self._format_unavailable_image(block, vision_enabled=vision_enabled))
                continue
            rendered = self.render_text_block(block)
            if rendered:
                text_parts.append(rendered)

        joined_text = "\n\n".join(part for part in text_parts if str(part).strip()).strip()
        if not image_parts:
            return joined_text

        content: List[Dict[str, Any]] = []
        if joined_text:
            content.append({"type": "text", "text": joined_text})
        content.extend(image_parts)
        return content

    @staticmethod
    def render_text_block(block: RuntimeBlock) -> str:
        label = str((block.metadata or {}).get("label") or block.source or "context").strip()
        if block.modality == "structured":
            return f"[{label}]\n{block.content}"
        text = str(block.content or "").strip()
        if not text:
            return ""
        return f"[{label}]\n{text}"

    @staticmethod
    def _extract_image_url(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, dict):
            return ""
        url = str(content.get("url") or "").strip()
        if url:
            return url
        b64 = str(content.get("base64") or content.get("content_b64") or "").strip()
        if not b64:
            return ""
        mime = str(content.get("mime_type") or content.get("content_type") or "image/png").strip() or "image/png"
        if b64.startswith("data:image/"):
            return b64
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _format_image_caption(block: RuntimeBlock) -> str:
        name = str((block.metadata or {}).get("filename") or (block.metadata or {}).get("file_id") or "image").strip()
        text = str((block.metadata or {}).get("extracted_text") or "").strip()
        if text:
            return f"[Image attachment: {name}]\nExtracted text/OCR fallback:\n{text}"
        return f"[Image attachment: {name}]\nUse the attached image block as visual context."

    @staticmethod
    def _format_unavailable_image(block: RuntimeBlock, *, vision_enabled: bool) -> str:
        name = str((block.metadata or {}).get("filename") or (block.metadata or {}).get("file_id") or "image").strip()
        reason = "current model is not vision-capable" if not vision_enabled else "image bytes are unavailable"
        text = str((block.metadata or {}).get("extracted_text") or "").strip()
        if text:
            return f"[Image attachment: {name}]\nVision unavailable ({reason}); OCR/text fallback:\n{text}"
        return (
            f"[Image attachment unavailable to model: {name}] {reason}. "
            "Do not invent visual details; ask the user to switch to a vision-capable model or provide text."
        )


def blocks_debug(blocks: Iterable[RuntimeBlock]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for block in normalize_runtime_blocks(blocks):
        payload = block.to_dict()
        content = payload.get("content")
        if isinstance(content, str) and len(content) > 240:
            payload["content"] = content[:237] + "..."
        elif isinstance(content, dict):
            payload["content"] = {
                k: ("<omitted>" if k in {"base64", "content_b64", "url"} else v)
                for k, v in content.items()
            }
        out.append(payload)
    return out
