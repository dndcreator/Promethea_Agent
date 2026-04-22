from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_current_user_id
from gateway_integration import get_gateway_integration


router = APIRouter(prefix="/org-brain", tags=["org-brain"])


class OrgIngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    org_id: Optional[str] = None
    source_doc_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    audience: Optional[str] = None
    register_name: Optional[str] = Field(default=None, alias="register")
    use_llm: bool = True


class OrgRecallRequest(BaseModel):
    org_id: Optional[str] = None
    topic: str = Field(min_length=1)
    audience: Optional[str] = None
    context_type: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class OrgGraphRequest(BaseModel):
    org_id: Optional[str] = None
    topic: Optional[str] = None
    audience: Optional[str] = None
    limit_nodes: int = Field(default=200, ge=1, le=500)


def _decode_upload_to_text(filename: str, content: bytes, *, allowed_suffixes: Optional[set[str]] = None) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    allowed = set(allowed_suffixes or {".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"})
    if suffix and suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type: {suffix}",
        )
    if suffix in {".txt", ".md", ".markdown"}:
        return content.decode("utf-8", errors="ignore").strip()
    if suffix == ".json":
        raw = content.decode("utf-8", errors="ignore").strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return raw
    if suffix == ".csv":
        text = content.decode("utf-8", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        rows = [",".join([str(x).strip() for x in row]) for row in reader]
        return "\n".join([row for row in rows if row.strip()]).strip()
    if suffix == ".docx":
        try:
            from docx import Document  # type: ignore
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="docx upload requires python-docx dependency",
            ) from exc
        buffer = io.BytesIO(content)
        doc = Document(buffer)
        lines = [str(p.text or "").strip() for p in doc.paragraphs]
        return "\n".join([ln for ln in lines if ln]).strip()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="pdf upload requires pypdf dependency",
            ) from exc
        reader = PdfReader(io.BytesIO(content))
        lines = []
        for page in reader.pages:
            try:
                lines.append(str(page.extract_text() or "").strip())
            except Exception:
                continue
        return "\n".join([ln for ln in lines if ln]).strip()
    if suffix in {".txt", ".md", ".markdown", ".csv", ".json"} or not suffix:
        return content.decode("utf-8", errors="ignore").strip()
    raise HTTPException(
        status_code=400,
        detail=f"unsupported file type: {suffix or 'unknown'}",
    )


def _get_org_service():
    integration = get_gateway_integration()
    if not integration:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    gateway_server = integration.get_gateway_server()
    svc = getattr(gateway_server, "org_context_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Org context service not initialized")
    cfg_service = getattr(gateway_server, "config_service", None)
    return svc, cfg_service


def _resolve_org_id(
    *,
    request_org_id: Optional[str],
    merged_config: Optional[Dict[str, Any]],
) -> str:
    if request_org_id and str(request_org_id).strip():
        return str(request_org_id).strip()
    cfg = merged_config if isinstance(merged_config, dict) else {}
    org_cfg = cfg.get("org_brain") if isinstance(cfg.get("org_brain"), dict) else {}
    org_id = str(org_cfg.get("org_id") or "").strip()
    return org_id


@router.get("/status")
async def org_brain_status(current_user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    svc, config_service = _get_org_service()
    merged = config_service.get_merged_config(current_user_id) if config_service else {}
    profile = svc.resolve_org_profile(merged)
    connector = svc._resolve_connector() if hasattr(svc, "_resolve_connector") else None
    backend = "neo4j" if connector else "in_memory_fallback"
    notice = (
        None
        if backend == "neo4j"
        else "Org brain is in fallback mode; core enterprise capability is graph-structured knowledge on Neo4j."
    )
    return {
        "status": "success",
        "user_id": current_user_id,
        "org_brain": {
            "enabled": bool(profile.get("enabled")),
            "org_id": str(profile.get("org_id") or ""),
            "recall_priority": str(profile.get("recall_priority") or "blend"),
            "confirmation_queue": bool(profile.get("confirmation_queue")),
            "audience_default": str(profile.get("audience_default") or ""),
            "core_capability": "graph_structure",
            "backend": backend,
            "notice": notice,
        },
    }


@router.post("/ingest")
async def org_brain_ingest(
    request: OrgIngestRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_org_service()
    merged = config_service.get_merged_config(current_user_id) if config_service else {}
    profile = svc.resolve_org_profile(merged)
    org_id = _resolve_org_id(request_org_id=request.org_id, merged_config=merged)
    if not profile.get("enabled"):
        raise HTTPException(status_code=400, detail="org_brain is disabled for current user")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id is required")
    result = await svc.ingest_document(
        org_id=org_id,
        source_doc_id=request.source_doc_id,
        text=request.text,
        audience=request.audience,
        register=request.register_name,
        use_llm=bool(request.use_llm),
        user_config=merged,
    )
    return {"status": "success", "user_id": current_user_id, **result}


@router.post("/ingest-file")
async def org_brain_ingest_file(
    file: UploadFile = File(...),
    org_id: Optional[str] = Form(default=None),
    source_doc_id: Optional[str] = Form(default=None),
    audience: Optional[str] = Form(default=None),
    register_name: Optional[str] = Form(default=None, alias="register"),
    use_llm: bool = Form(default=True),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_org_service()
    merged = config_service.get_merged_config(current_user_id) if config_service else {}
    profile = svc.resolve_org_profile(merged)
    resolved_org_id = _resolve_org_id(request_org_id=org_id, merged_config=merged)
    if not profile.get("enabled"):
        raise HTTPException(status_code=400, detail="org_brain is disabled for current user")
    if not resolved_org_id:
        raise HTTPException(status_code=400, detail="org_id is required")
    filename = str(getattr(file, "filename", "") or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    max_upload_bytes = int(profile.get("max_upload_bytes") or 10 * 1024 * 1024)
    if len(raw) > max_upload_bytes:
        raise HTTPException(status_code=400, detail=f"file too large (>{max_upload_bytes} bytes)")
    allowed_suffixes = set(profile.get("allowed_suffixes") or [])
    text = _decode_upload_to_text(filename=filename, content=raw, allowed_suffixes=allowed_suffixes)
    if not text:
        raise HTTPException(status_code=400, detail="unable to extract text from file")
    doc_id = str(source_doc_id or Path(filename).stem or "upload_doc").strip()
    result = await svc.ingest_document(
        org_id=resolved_org_id,
        source_doc_id=doc_id,
        text=text,
        audience=audience,
        register=register_name,
        use_llm=bool(use_llm),
        user_config=merged,
    )
    return {
        "status": "success",
        "user_id": current_user_id,
        "filename": filename,
        "bytes": len(raw),
        "source_doc_id": doc_id,
        **result,
    }


@router.post("/recall")
async def org_brain_recall(
    request: OrgRecallRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_org_service()
    merged = config_service.get_merged_config(current_user_id) if config_service else {}
    profile = svc.resolve_org_profile(merged)
    org_id = _resolve_org_id(request_org_id=request.org_id, merged_config=merged)
    if not profile.get("enabled"):
        raise HTTPException(status_code=400, detail="org_brain is disabled for current user")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id is required")
    audience = request.audience or profile.get("audience_default") or ""
    context_type = str(request.context_type or profile.get("recall_context_type_default") or "writing")
    top_k = int(request.top_k or profile.get("recall_top_k_default") or 5)
    payload = await svc.recall_org_context(
        org_id=org_id,
        topic=request.topic,
        audience=str(audience),
        context_type=context_type,
        top_k=top_k,
        user_id=current_user_id,
        recall_priority=str(profile.get("recall_priority") or "blend"),
        summary_label=str(profile.get("summary_label") or "Organization context hints"),
        summary_max_items=int(profile.get("summary_max_items") or 8),
    )
    return {"status": "success", "user_id": current_user_id, **payload}


@router.post("/graph")
async def org_brain_graph(
    request: OrgGraphRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    svc, config_service = _get_org_service()
    merged = config_service.get_merged_config(current_user_id) if config_service else {}
    profile = svc.resolve_org_profile(merged)
    org_id = _resolve_org_id(request_org_id=request.org_id, merged_config=merged)
    if not profile.get("enabled"):
        raise HTTPException(status_code=400, detail="org_brain is disabled for current user")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id is required")
    payload = await svc.get_visual_graph(
        org_id=org_id,
        topic=str(request.topic or ""),
        audience=str(request.audience or ""),
        limit_nodes=int(request.limit_nodes or 200),
        user_id=current_user_id,
    )
    return {"status": "success", "user_id": current_user_id, **payload}
