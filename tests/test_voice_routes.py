from __future__ import annotations

import pytest
from fastapi import HTTPException

from gateway.http.routes import voice


class _FakeUpload:
    def __init__(self, data: bytes, *, filename: str = "voice.webm", content_type: str = "audio/webm") -> None:
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_voice_capabilities_declares_ptt_turn_mode(monkeypatch):
    monkeypatch.setattr(
        voice,
        "_get_voice_settings",
        lambda: voice.VoiceRuntimeSettings(
            stt_provider="openai",
            tts_provider="openai",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
        ),
    )
    out = await voice.get_voice_capabilities(user_id="u1")
    assert out["status"] == "success"
    assert out["voice"]["streaming_output"] is False
    assert out["voice"]["interaction_mode"] == "push_to_talk_turn"


@pytest.mark.asyncio
async def test_voice_stt_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setattr(
        voice,
        "_get_voice_settings",
        lambda: voice.VoiceRuntimeSettings(stt_provider="custom_stt"),
    )
    with pytest.raises(HTTPException) as ei:
        await voice.voice_stt(audio=_FakeUpload(b"abc"), user_id="u1")
    assert ei.value.status_code == 400
    assert "unsupported stt provider" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_voice_ptt_respects_stt_provider_gate(monkeypatch):
    monkeypatch.setattr(
        voice,
        "_get_voice_settings",
        lambda: voice.VoiceRuntimeSettings(stt_provider="custom_stt"),
    )
    with pytest.raises(HTTPException) as ei:
        await voice.voice_ptt(audio=_FakeUpload(b"abc"), user_id="u1")
    assert ei.value.status_code == 400
    assert "unsupported stt provider" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_voice_ptt_full_round_trip_with_optional_tts(monkeypatch):
    monkeypatch.setattr(
        voice,
        "_get_voice_settings",
        lambda: voice.VoiceRuntimeSettings(stt_provider="openai", tts_provider="openai"),
    )

    async def _fake_dispatch_stt(*, settings, filename, content_type, payload):
        _ = (settings, filename, content_type, payload)
        return voice.VoiceSTTResult(text="你好，帮我总结今天任务")

    async def _fake_voice_turn(request, user_id):
        _ = user_id
        return {"status": "success", "session_id": request.session_id or "s1", "response": "已整理完成"}

    async def _fake_dispatch_tts(req, settings):
        _ = (req, settings)
        return b"\x00\x01", "audio/mpeg"

    monkeypatch.setattr(voice, "_dispatch_stt", _fake_dispatch_stt)
    monkeypatch.setattr(voice, "voice_turn", _fake_voice_turn)
    monkeypatch.setattr(voice, "_dispatch_tts", _fake_dispatch_tts)

    out = await voice.voice_ptt(
        audio=_FakeUpload(b"dummy"),
        session_id="sess_1",
        wake_word=None,
        speak=True,
        user_id="u1",
    )
    assert out["status"] == "success"
    assert out["transcript"] == "你好，帮我总结今天任务"
    assert out["turn"]["response"] == "已整理完成"
    assert out["tts"]["mime"] == "audio/mpeg"
    assert isinstance(out["tts"]["audio_base64"], str) and out["tts"]["audio_base64"]


@pytest.mark.asyncio
async def test_voice_tts_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(
        voice,
        "_get_voice_settings",
        lambda: voice.VoiceRuntimeSettings(tts_provider="openai"),
    )
    req = voice.VoiceTTSRequest(text="hello", provider="unknown-provider")
    with pytest.raises(HTTPException) as ei:
        await voice.voice_tts(request=req, user_id="u1")
    assert ei.value.status_code == 400
    assert "unsupported tts provider" in str(ei.value.detail)
