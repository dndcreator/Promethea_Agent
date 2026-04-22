from __future__ import annotations

import pytest

from gateway.http.routes import files


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
