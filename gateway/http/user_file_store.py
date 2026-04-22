from __future__ import annotations

import csv
import io
import json
import os
import base64
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


class UserFileStore:
    def __init__(self, root_dir: str = "config/users") -> None:
        self.root_dir = Path(root_dir)
        self.allowed_suffixes = {".txt", ".md", ".markdown", ".csv", ".json", ".docx", ".pdf"}
        self.max_upload_bytes = 15 * 1024 * 1024

    def _user_root(self, user_id: str) -> Path:
        return self.root_dir / str(user_id) / "files"

    def _index_path(self, user_id: str) -> Path:
        return self._user_root(user_id) / "index.json"

    def _blob_dir(self, user_id: str) -> Path:
        return self._user_root(user_id) / "blob"

    def _text_dir(self, user_id: str) -> Path:
        return self._user_root(user_id) / "text"

    def _decode_to_text(self, *, filename: str, content: bytes) -> str:
        suffix = Path(str(filename or "")).suffix.lower()
        if suffix and suffix not in self.allowed_suffixes:
            raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix}")

        if suffix in {".txt", ".md", ".markdown"} or not suffix:
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
                return raw
            return raw
        if suffix == ".csv":
            text = content.decode("utf-8", errors="ignore")
            rows = csv.reader(io.StringIO(text))
            joined = [",".join([str(cell).strip() for cell in row]) for row in rows]
            return "\n".join([line for line in joined if line.strip()]).strip()
        if suffix == ".docx":
            try:
                from docx import Document  # type: ignore
            except Exception as exc:
                raise HTTPException(status_code=400, detail="docx upload requires python-docx dependency") from exc
            doc = Document(io.BytesIO(content))
            lines = [str(p.text or "").strip() for p in doc.paragraphs]
            return "\n".join([ln for ln in lines if ln]).strip()
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore
            except Exception as exc:
                raise HTTPException(status_code=400, detail="pdf upload requires pypdf dependency") from exc
            reader = PdfReader(io.BytesIO(content))
            lines: List[str] = []
            for page in reader.pages:
                try:
                    lines.append(str(page.extract_text() or "").strip())
                except Exception:
                    continue
            return "\n".join([ln for ln in lines if ln]).strip()
        raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix or 'unknown'}")

    def _load_index(self, user_id: str) -> Dict[str, Any]:
        path = self._index_path(user_id)
        if not path.exists():
            return {"items": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            return {"items": items}
        except Exception:
            return {"items": []}

    def _save_index(self, user_id: str, items: List[Dict[str, Any]]) -> None:
        _atomic_write_json(self._index_path(user_id), {"items": items})

    def save_upload(
        self,
        *,
        user_id: str,
        filename: str,
        content: bytes,
        content_type: str = "",
        session_id: str = "",
    ) -> Dict[str, Any]:
        raw_name = str(filename or "").strip()
        if not raw_name:
            raise HTTPException(status_code=400, detail="filename is required")
        if not content:
            raise HTTPException(status_code=400, detail="empty file")
        if len(content) > self.max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"file too large (>{self.max_upload_bytes} bytes)")

        suffix = Path(raw_name).suffix.lower()
        if suffix and suffix not in self.allowed_suffixes:
            raise HTTPException(status_code=400, detail=f"unsupported file type: {suffix}")
        text = self._decode_to_text(filename=raw_name, content=content)

        file_id = f"f_{uuid.uuid4().hex}"
        stored_name = f"{file_id}{suffix}"
        blob_path = self._blob_dir(user_id) / stored_name
        text_path = self._text_dir(user_id) / f"{file_id}.txt"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(content)
        text_path.write_text(text, encoding="utf-8")

        ts = int(time.time())
        entry = {
            "file_id": file_id,
            "filename": raw_name,
            "stored_name": stored_name,
            "bytes": len(content),
            "content_type": str(content_type or ""),
            "uploaded_at": ts,
            "session_id": str(session_id or ""),
            "text_chars": len(text),
        }
        index = self._load_index(user_id)
        items = [entry] + [item for item in index.get("items", []) if isinstance(item, dict)]
        self._save_index(user_id, items)
        return entry

    def list_files(self, *, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        index = self._load_index(user_id)
        items = [item for item in index.get("items", []) if isinstance(item, dict)]
        return items[: max(1, int(limit))]

    def search_files(self, *, user_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        q = str(query or "").strip().lower()
        if not q:
            return self.list_files(user_id=user_id, limit=limit)

        index = self._load_index(user_id)
        rows: List[Dict[str, Any]] = []
        for item in index.get("items", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("filename") or "")
            file_id = str(item.get("file_id") or "")
            text_path = self._text_dir(user_id) / f"{file_id}.txt"
            text = ""
            if text_path.exists():
                try:
                    text = text_path.read_text(encoding="utf-8")
                except Exception:
                    text = ""
            hay = f"{name}\n{text}".lower()
            pos = hay.find(q)
            if pos < 0:
                continue
            snippet_start = max(0, pos - 80)
            snippet_end = min(len(hay), pos + len(q) + 120)
            snippet = hay[snippet_start:snippet_end].replace("\n", " ").strip()
            payload = dict(item)
            payload["snippet"] = snippet
            rows.append(payload)
            if len(rows) >= max(1, int(limit)):
                break
        return rows

    def get_stats(self, *, user_id: str) -> Dict[str, Any]:
        items = self._load_index(user_id).get("items", [])
        if not isinstance(items, list):
            items = []
        total_bytes = sum(int(x.get("bytes") or 0) for x in items if isinstance(x, dict))
        return {
            "total_files": len(items),
            "total_bytes": total_bytes,
        }

    def get_global_stats(self) -> Dict[str, Any]:
        total_files = 0
        total_bytes = 0
        total_users = 0
        base = self.root_dir
        if not base.exists():
            return {"total_files": 0, "total_bytes": 0, "total_users": 0}
        for user_dir in base.iterdir():
            if not user_dir.is_dir():
                continue
            stats = self.get_stats(user_id=user_dir.name)
            if int(stats.get("total_files") or 0) > 0:
                total_users += 1
            total_files += int(stats.get("total_files") or 0)
            total_bytes += int(stats.get("total_bytes") or 0)
        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_users": total_users,
        }

    def export_user_bundle(
        self,
        *,
        user_id: str,
        include_content: bool = False,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        rows = self.list_files(user_id=user_id, limit=limit)
        items: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            file_id = str(item.get("file_id") or "")
            text_path = self._text_dir(user_id) / f"{file_id}.txt"
            if text_path.exists():
                try:
                    item["text"] = text_path.read_text(encoding="utf-8")
                except Exception:
                    item["text"] = ""
            if include_content:
                stored_name = str(item.get("stored_name") or "")
                blob_path = self._blob_dir(user_id) / stored_name
                if blob_path.exists():
                    try:
                        item["content_b64"] = base64.b64encode(blob_path.read_bytes()).decode("ascii")
                    except Exception:
                        item["content_b64"] = ""
            items.append(item)
        return {
            "items": items,
            "stats": self.get_stats(user_id=user_id),
            "include_content": bool(include_content),
        }

    def import_user_bundle(
        self,
        *,
        user_id: str,
        bundle: Dict[str, Any],
        merge: bool = True,
    ) -> Dict[str, Any]:
        rows = bundle.get("items") if isinstance(bundle.get("items"), list) else []
        imported = 0
        skipped = 0
        existing_names = {str(x.get("filename") or "") for x in self.list_files(user_id=user_id, limit=5000)}
        for row in rows:
            if not isinstance(row, dict):
                continue
            filename = str(row.get("filename") or "").strip()
            if not filename:
                skipped += 1
                continue
            if merge and filename in existing_names:
                skipped += 1
                continue
            payload = b""
            b64 = str(row.get("content_b64") or "")
            if b64:
                try:
                    payload = base64.b64decode(b64.encode("ascii"), validate=False)
                except Exception:
                    payload = b""
            if not payload:
                payload = str(row.get("text") or "").encode("utf-8")
            if not payload:
                skipped += 1
                continue
            try:
                self.save_upload(
                    user_id=user_id,
                    filename=filename,
                    content=payload,
                    content_type=str(row.get("content_type") or ""),
                    session_id=str(row.get("session_id") or ""),
                )
                imported += 1
                existing_names.add(filename)
            except Exception:
                skipped += 1
        return {"imported_files": imported, "skipped_files": skipped}


user_file_store = UserFileStore()
