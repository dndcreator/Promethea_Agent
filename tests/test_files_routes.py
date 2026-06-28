from __future__ import annotations

import pytest

from gateway.http.routes import files
from gateway.http.user_file_store import UserFileStore


class _FakeUpload:
    def __init__(self, data: bytes, *, filename: str = "notes.txt", content_type: str = "text/plain") -> None:
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_upload_user_file_returns_entry(monkeypatch):
    monkeypatch.setattr(
        files.user_file_store,
        "save_upload",
        lambda **kwargs: {
            "file_id": "f_1",
            "filename": kwargs.get("filename"),
            "session_id": kwargs.get("session_id"),
        },
    )
    out = await files.upload_user_file(
        file=_FakeUpload(b"hello", filename="memo.txt"),
        session_id="s1",
        user_id="u1",
    )
    assert out["status"] == "success"
    assert out["file"]["file_id"] == "f_1"
    assert out["file"]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_list_user_files_supports_search(monkeypatch):
    monkeypatch.setattr(
        files.user_file_store,
        "search_files",
        lambda **kwargs: [{"file_id": "f_2", "filename": "policy.txt", "snippet": "risk policy"}],
    )
    out = await files.list_user_files(q="policy", limit=10, user_id="u1")
    assert out["status"] == "success"
    assert out["total"] == 1
    assert out["files"][0]["file_id"] == "f_2"


def test_user_file_store_builds_chat_attachment_context(tmp_path):
    store = UserFileStore(root_dir=str(tmp_path))
    entry = store.save_upload(
        user_id="u1",
        filename="notes.txt",
        content=b"launch checklist and enterprise graph notes",
        content_type="text/plain",
        session_id="s1",
    )

    context = store.build_chat_attachment_context(
        user_id="u1",
        attachments=[{"file_id": entry["file_id"]}],
    )

    assert context["unsupported"] == []
    assert context["items"][0]["filename"] == "notes.txt"
    assert "enterprise graph notes" in context["context_text"]


def test_user_file_store_image_without_ocr_is_stored_only(tmp_path):
    store = UserFileStore(root_dir=str(tmp_path))
    entry = store.save_upload(
        user_id="u1",
        filename="diagram.png",
        content=b"not a real image but still stored as upload bytes",
        content_type="image/png",
        session_id="s1",
    )

    assert entry["modality"] == "image"
    assert entry["text_extraction_status"] == "empty_or_unsupported"

    context = store.build_chat_attachment_context(
        user_id="u1",
        attachments=[{"file_id": entry["file_id"]}],
    )

    assert context["items"] == []
    assert context["unsupported"][0]["reason"] == "no_extracted_text"
    assert "unavailable to model" in context["context_text"]
