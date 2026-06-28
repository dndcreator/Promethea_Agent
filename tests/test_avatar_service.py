from pathlib import Path

import pytest
from fastapi import HTTPException

from gateway.avatar_service import AvatarService
from gateway.http.routes import avatar


class _FakeUpload:
    def __init__(self, data: bytes, *, filename: str, content_type: str) -> None:
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def test_avatar_service_stores_user_scoped_image_and_replaces_previous_asset(tmp_path: Path):
    service = AvatarService(root_dir=str(tmp_path))

    first = service.save_upload(
        user_id="u1",
        filename="first.png",
        content=b"png-one",
        content_type="image/png",
    )
    first_path = service.get_asset_path(user_id="u1", avatar_id=first["avatar_id"])
    assert first_path is not None
    assert first_path.read_bytes() == b"png-one"

    second = service.save_upload(
        user_id="u1",
        filename="second.webm",
        content=b"video-two",
        content_type="video/webm",
    )
    assert second["kind"] == "video"
    assert service.get_asset_path(user_id="u1", avatar_id=first["avatar_id"]) is None
    assert not first_path.exists()
    assert service.get_asset_path(user_id="u1", avatar_id=second["avatar_id"]).read_bytes() == b"video-two"


def test_avatar_service_rejects_unsupported_upload(tmp_path: Path):
    service = AvatarService(root_dir=str(tmp_path))

    with pytest.raises(HTTPException) as exc:
        service.save_upload(user_id="u1", filename="model.vrm", content=b"vrm")

    assert exc.value.status_code == 400
    assert "unsupported avatar type" in str(exc.value.detail)


def test_avatar_service_toggle_and_clear(tmp_path: Path):
    service = AvatarService(root_dir=str(tmp_path))
    saved = service.save_upload(user_id="u1", filename="avatar.jpg", content=b"jpg")

    disabled = service.set_enabled(user_id="u1", enabled=False)
    assert disabled["enabled"] is False
    assert service.get_asset_path(user_id="u1", avatar_id=saved["avatar_id"]) is not None

    cleared = service.clear(user_id="u1")
    assert cleared["kind"] == "none"
    assert service.get_asset_path(user_id="u1", avatar_id=saved["avatar_id"]) is None


@pytest.mark.asyncio
async def test_upload_avatar_route_returns_manifest(monkeypatch):
    monkeypatch.setattr(
        avatar.avatar_service,
        "save_upload",
        lambda **kwargs: {"avatar_id": "avatar_1", "kind": "image", "filename": kwargs["filename"]},
    )

    out = await avatar.upload_avatar(
        file=_FakeUpload(b"image", filename="portrait.png", content_type="image/png"),
        user_id="u1",
    )

    assert out["status"] == "success"
    assert out["avatar"]["avatar_id"] == "avatar_1"
    assert out["avatar"]["filename"] == "portrait.png"


@pytest.mark.asyncio
async def test_update_current_avatar_route_toggles_enabled(monkeypatch):
    monkeypatch.setattr(
        avatar.avatar_service,
        "set_enabled",
        lambda **kwargs: {"avatar_id": "avatar_1", "enabled": kwargs["enabled"]},
    )

    out = await avatar.update_current_avatar(
        request=avatar.AvatarEnabledRequest(enabled=False),
        user_id="u1",
    )

    assert out["avatar"]["enabled"] is False
