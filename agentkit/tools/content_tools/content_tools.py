from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from agentkit.security.sandbox import get_sandbox_policy
from agentkit.tools.web_content import fetch_page


class ContentToolsService:
    """Content acquisition helpers: web fetch, PDF, and image utilities."""

    def __init__(self, workspace_root: str | None = None):
        self.name = "content_tools"
        root = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = root.resolve()
        self._sandbox = get_sandbox_policy()

    async def web_fetch(
        self,
        url: str,
        max_chars: int = 12000,
        timeout: int = 20,
        include_links: bool = False,
    ) -> Dict[str, Any]:
        if not url or not str(url).strip():
            raise ValueError("url is required")
        decision = self._sandbox.check_url(str(url).strip())
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked web_fetch: {decision.reason}")

        page = await fetch_page(str(url).strip(), policy=self._sandbox, timeout_s=max(1, min(int(timeout), 60)),
                                max_chars=max(200, min(int(max_chars), 200000)), include_links=include_links)
        # Retain the existing content-tool envelope; acquisition/extraction has one owner.
        content = page.pop("text")
        return {**page, "ok": True, "status_code": page["status"], "content": content}

    async def pdf_action(
        self,
        action: str = "extract_text",
        path: str = "",
        page: int = 0,
        max_pages: int = 5,
        max_chars: int = 12000,
    ) -> Dict[str, Any]:
        file_path = self._resolve_workspace_path(path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"pdf not found: {file_path}")

        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except Exception as e:
                raise RuntimeError("pypdf/PyPDF2 is required for pdf_action") from e

        reader = PdfReader(str(file_path))
        total_pages = len(reader.pages)

        if action == "metadata":
            meta = dict(reader.metadata or {})
            return {
                "ok": True,
                "path": str(file_path),
                "total_pages": total_pages,
                "metadata": {str(k): str(v) for k, v in meta.items()},
            }

        start_page = max(0, int(page))
        count = max(1, int(max_pages))
        end_page = min(total_pages, start_page + count)

        chunks: List[str] = []
        for idx in range(start_page, end_page):
            page_text = reader.pages[idx].extract_text() or ""
            if page_text:
                chunks.append(f"[Page {idx + 1}]\\n{page_text}")

        combined = "\\n\\n".join(chunks)
        return {
            "ok": True,
            "path": str(file_path),
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": max(start_page, end_page - 1),
            "content": combined[: max(200, int(max_chars))],
        }

    async def image_action(
        self,
        action: str = "metadata",
        path: str = "",
        max_chars: int = 8000,
    ) -> Dict[str, Any]:
        file_path = self._resolve_workspace_path(path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"image not found: {file_path}")

        try:
            from PIL import Image
        except Exception as e:
            raise RuntimeError("Pillow is required for image_action") from e

        with Image.open(file_path) as img:
            info = {
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
            }

        if action == "metadata":
            return {"ok": True, "path": str(file_path), "image": info}

        if action == "ocr":
            try:
                import pytesseract
                from PIL import Image
            except Exception as e:
                raise RuntimeError("pytesseract is required for OCR") from e

            with Image.open(file_path) as img:
                text = pytesseract.image_to_string(img)
            return {
                "ok": True,
                "path": str(file_path),
                "image": info,
                "text": (text or "")[: max(200, int(max_chars))],
            }

        raise ValueError(f"unsupported image action: {action}")

    def _resolve_workspace_path(self, path_str: str) -> Path:
        if not path_str:
            raise ValueError("path is required")
        path = Path(path_str)
        if not path.is_absolute():
            path = self.workspace_root / path
        path = path.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as e:
            raise PermissionError(f"path outside workspace is not allowed: {path}") from e
        decision = self._sandbox.check_path(str(path), intent="read", workspace_root=self.workspace_root)
        if not decision.allowed:
            raise PermissionError(f"sandbox blocked path access: {decision.reason}")
        return path


