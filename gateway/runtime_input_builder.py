from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from .runtime_io import RuntimeBlock, normalize_runtime_blocks


def build_runtime_input_blocks(
    *,
    user_message: str,
    user_id: str,
    attachments: Optional[List[Dict[str, Any]]],
    runtime_blocks: Optional[List[Dict[str, Any]]],
    run_context: Optional[Any],
) -> List[RuntimeBlock]:
    blocks: List[RuntimeBlock] = [
        RuntimeBlock(
            source="user",
            role="request",
            modality="text",
            content=str(user_message or ""),
            metadata={"label": "User request"},
        )
    ]
    blocks.extend(normalize_runtime_blocks(runtime_blocks or []))
    if run_context is not None:
        existing = getattr(run_context, "runtime_blocks", None)
        if isinstance(existing, list):
            blocks.extend(normalize_runtime_blocks(existing))

    blocks.extend(build_attachment_blocks(user_id=user_id, attachments=attachments or []))
    return blocks


def build_attachment_blocks(
    *,
    user_id: str,
    attachments: List[Dict[str, Any]],
) -> List[RuntimeBlock]:
    if not attachments:
        return []
    try:
        from gateway.http.user_file_store import user_file_store
    except Exception as exc:
        logger.debug("Runtime input builder: user file store unavailable: {}", exc)
        return [
            RuntimeBlock(
                source="attachment",
                role="context",
                modality="text",
                content="Attachment metadata was provided, but the file store is unavailable.",
                metadata={"label": "Attachment unavailable"},
            )
        ]

    out: List[RuntimeBlock] = []
    for raw in attachments[:5]:
        if not isinstance(raw, dict):
            continue
        file_id = str(raw.get("file_id") or "").strip()
        entry = user_file_store.get_file(user_id=user_id, file_id=file_id)
        if not entry:
            out.append(
                RuntimeBlock(
                    source="attachment",
                    role="context",
                    modality="text",
                    content=f"Attachment `{file_id}` was referenced but not found.",
                    metadata={"file_id": file_id, "label": "Attachment unavailable"},
                )
            )
            continue

        filename = str(entry.get("filename") or file_id)
        modality = str(entry.get("modality") or "document")
        extracted_text = user_file_store.read_extracted_text(
            user_id=user_id,
            file_id=file_id,
            max_chars=12000,
        ).strip()
        base_meta = {
            "file_id": file_id,
            "filename": filename,
            "label": f"Attachment: {filename}",
            "text_extraction_status": entry.get("text_extraction_status"),
        }
        if modality == "image":
            out.append(_build_image_attachment_block(user_id, file_id, entry, base_meta, extracted_text))
            continue

        if extracted_text:
            out.append(
                RuntimeBlock(
                    source="attachment",
                    role="context",
                    modality="text",
                    content=extracted_text,
                    metadata=base_meta,
                )
            )
        else:
            out.append(
                RuntimeBlock(
                    source="attachment",
                    role="context",
                    modality="text",
                    content=(
                        f"Attachment `{filename}` is stored, but no extracted text is available. "
                        "Do not invent its contents."
                    ),
                    metadata=base_meta,
                )
            )
    return out


def _build_image_attachment_block(
    user_id: str,
    file_id: str,
    entry: Dict[str, Any],
    base_meta: Dict[str, Any],
    extracted_text: str,
) -> RuntimeBlock:
    from gateway.http.user_file_store import user_file_store

    image_payload = user_file_store.read_blob_b64(user_id=user_id, file_id=file_id)
    if image_payload:
        return RuntimeBlock(
            source="attachment",
            role="context",
            modality="image",
            content={
                "base64": image_payload.get("base64"),
                "content_type": image_payload.get("content_type") or entry.get("content_type") or "image/png",
            },
            metadata={**base_meta, "extracted_text": extracted_text},
        )
    if extracted_text:
        return RuntimeBlock(
            source="attachment",
            role="context",
            modality="text",
            content=extracted_text,
            metadata=base_meta,
        )
    return RuntimeBlock(
        source="attachment",
        role="context",
        modality="image",
        content={},
        metadata=base_meta,
    )
