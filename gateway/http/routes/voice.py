from __future__ import annotations

import asyncio
import base64
import os
from typing import Optional

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field

from gateway.protocol import RequestType

from .auth import get_current_user_id
from ..dispatcher import dispatch_gateway_method


router = APIRouter()


class VoiceTurnRequest(BaseModel):
    text: str
    session_id: Optional[str] = None
    wake_word: Optional[str] = None


class VoiceTTSRequest(BaseModel):
    text: str
    provider: Optional[str] = None  # openai | elevenlabs
    voice: Optional[str] = None
    format: str = Field(default="mp3")
    speed: Optional[float] = None
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    use_speaker_boost: Optional[bool] = None


class VoiceSTTResult(BaseModel):
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None


class VoiceRuntimeSettings(BaseModel):
    stt_provider: str = "openai"
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_provider: str = "openai"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    tts_format: str = "mp3"
    tts_speed: float = 1.0
    openai_base_url: str = "https://api.openai.com/v1"
    elevenlabs_base_url: str = "https://api.elevenlabs.io"



def _read_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        value = value.strip()
        if value:
            return value
    return ""


def _read_float(default: float, *names: str) -> float:
    value = _read_env(*names)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _default_tts_model(provider: str) -> str:
    return "eleven_turbo_v2_5" if provider == "elevenlabs" else "gpt-4o-mini-tts"


def _get_voice_settings() -> VoiceRuntimeSettings:
    # Compact aliases for simpler setup:
    # VOICE__PROVIDER/VOICE__MODEL/VOICE__VOICE/VOICE__FORMAT/VOICE__SPEED
    tts_provider = _read_env("VOICE__PROVIDER", "VOICE__TTS_PROVIDER").lower() or "openai"
    tts_model = _read_env("VOICE__MODEL", "VOICE__TTS_MODEL") or _default_tts_model(tts_provider)
    return VoiceRuntimeSettings(
        stt_provider=_read_env("VOICE__STT_PROVIDER").lower() or "openai",
        stt_model=_read_env("VOICE__STT_MODEL") or "gpt-4o-mini-transcribe",
        tts_provider=tts_provider,
        tts_model=tts_model,
        tts_voice=_read_env("VOICE__VOICE", "VOICE__TTS_VOICE") or "alloy",
        tts_format=_read_env("VOICE__FORMAT", "VOICE__TTS_FORMAT").lower() or "mp3",
        tts_speed=_read_float(1.0, "VOICE__SPEED", "VOICE__TTS_SPEED"),
        openai_base_url=_read_env("VOICE__BASE_URL", "VOICE__OPENAI_BASE_URL", "API__BASE_URL") or "https://api.openai.com/v1",
        elevenlabs_base_url=_read_env("VOICE__ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io",
    )


def _get_openai_api_key() -> str:
    api_key = _read_env("VOICE__API_KEY", "API__API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="VOICE__API_KEY or API__API_KEY is required for voice openai provider")
    return api_key


def _get_elevenlabs_api_key() -> str:
    api_key = _read_env("VOICE__ELEVENLABS_API_KEY", "VOICE__API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="VOICE__ELEVENLABS_API_KEY or VOICE__API_KEY is required for elevenlabs provider")
    return api_key


def _detect_mime(audio_format: str) -> str:
    fmt = (audio_format or "mp3").lower()
    if fmt in {"mp3", "mpeg"}:
        return "audio/mpeg"
    if fmt in {"wav", "pcm"}:
        return "audio/wav"
    if fmt in {"ogg", "opus"}:
        return "audio/ogg"
    return "application/octet-stream"


def _call_openai_stt_sync(*, settings: VoiceRuntimeSettings, filename: str, content_type: str, payload: bytes) -> VoiceSTTResult:
    api_key = _get_openai_api_key()
    url = settings.openai_base_url.rstrip("/") + "/audio/transcriptions"
    files = {"file": (filename or "voice.webm", payload, content_type or "audio/webm")}
    data = {"model": settings.stt_model}
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"stt provider error: {response.text[:300]}")
    body = response.json()
    text = str(body.get("text") or "").strip()
    return VoiceSTTResult(text=text, language=body.get("language"), duration_seconds=body.get("duration"))


def _call_openai_tts_sync(*, settings: VoiceRuntimeSettings, req: VoiceTTSRequest) -> tuple[bytes, str]:
    api_key = _get_openai_api_key()
    url = settings.openai_base_url.rstrip("/") + "/audio/speech"
    payload = {
        "model": settings.tts_model,
        "voice": (req.voice or settings.tts_voice),
        "input": req.text,
        "format": req.format or settings.tts_format,
        "speed": req.speed if req.speed is not None else settings.tts_speed,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=180)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"tts provider error: {response.text[:300]}")
    audio_format = payload["format"]
    return response.content, _detect_mime(audio_format)


def _call_elevenlabs_tts_sync(*, settings: VoiceRuntimeSettings, req: VoiceTTSRequest) -> tuple[bytes, str]:
    api_key = _get_elevenlabs_api_key()
    voice_id = (req.voice or settings.tts_voice or "").strip()
    if not voice_id:
        raise HTTPException(status_code=400, detail="tts voice is required for elevenlabs provider")

    model_id = (settings.tts_model or "eleven_turbo_v2_5").strip()
    output_format = (req.format or settings.tts_format or "mp3").strip().lower()
    url = settings.elevenlabs_base_url.rstrip("/") + f"/v1/text-to-speech/{voice_id}/stream"

    voice_settings = {}
    if req.stability is not None:
        voice_settings["stability"] = req.stability
    if req.similarity_boost is not None:
        voice_settings["similarity_boost"] = req.similarity_boost
    if req.style is not None:
        voice_settings["style"] = req.style
    if req.use_speaker_boost is not None:
        voice_settings["use_speaker_boost"] = req.use_speaker_boost

    payload = {
        "text": req.text,
        "model_id": model_id,
    }
    if voice_settings:
        payload["voice_settings"] = voice_settings

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    response = requests.post(
        url,
        headers=headers,
        params={"output_format": output_format},
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"elevenlabs tts error: {response.text[:300]}")
    return response.content, _detect_mime(output_format)


async def _dispatch_tts(req: VoiceTTSRequest, settings: VoiceRuntimeSettings) -> tuple[bytes, str]:
    provider = (req.provider or settings.tts_provider or "openai").strip().lower()
    if provider == "elevenlabs":
        return await asyncio.to_thread(_call_elevenlabs_tts_sync, settings=settings, req=req)
    return await asyncio.to_thread(_call_openai_tts_sync, settings=settings, req=req)


@router.get("/voice/capabilities")
async def get_voice_capabilities(user_id: str = Depends(get_current_user_id)):
    settings = _get_voice_settings()
    return {
        "status": "success",
        "user_id": user_id,
        "voice": {
            "input": "audio+text",
            "wake_word": True,
            "streaming_output": True,
            "stt": True,
            "tts": True,
            "providers": {
                "stt": ["openai"],
                "tts": ["openai", "elevenlabs"],
            },
            "defaults": settings.model_dump(),
            "endpoints": {
                "stt": "/api/voice/stt",
                "tts": "/api/voice/tts",
                "turn": "/api/voice/turn",
                "ptt": "/api/voice/ptt",
            },
        },
    }


@router.post("/voice/stt")
async def voice_stt(
    audio: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    settings = _get_voice_settings()
    if settings.stt_provider != "openai":
        raise HTTPException(status_code=400, detail="only openai stt provider is currently supported")

    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty audio payload")

    result = await asyncio.to_thread(
        _call_openai_stt_sync,
        settings=settings,
        filename=audio.filename or "voice.webm",
        content_type=audio.content_type or "audio/webm",
        payload=payload,
    )
    return {
        "status": "success",
        "user_id": user_id,
        "stt": result.model_dump(),
    }


@router.post("/voice/tts")
async def voice_tts(
    request: VoiceTTSRequest,
    user_id: str = Depends(get_current_user_id),
):
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    settings = _get_voice_settings()
    audio_bytes, mime = await _dispatch_tts(request, settings)
    return Response(content=audio_bytes, media_type=mime)


@router.post("/voice/turn")
async def voice_turn(request: VoiceTurnRequest, user_id: str = Depends(get_current_user_id)):
    text = (request.text or "").strip()
    wake_word = (request.wake_word or "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    if wake_word and wake_word.lower() not in text.lower():
        return {
            "status": "ignored",
            "user_id": user_id,
            "reason": "wake_word_not_detected",
        }

    payload = await dispatch_gateway_method(
        RequestType.CHAT,
        {
            "message": text,
            "session_id": request.session_id,
            "stream": False,
        },
        user_id=user_id,
    )
    return {
        "status": "success",
        "mode": "voice_text_turn",
        "user_id": user_id,
        **payload,
    }


@router.post("/voice/ptt")
async def voice_ptt(
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
    wake_word: Optional[str] = Form(default=None),
    speak: bool = Form(default=True),
    tts_provider: Optional[str] = Form(default=None),
    tts_voice: Optional[str] = Form(default=None),
    tts_format: str = Form(default="mp3"),
    tts_speed: Optional[float] = Form(default=None),
    tts_stability: Optional[float] = Form(default=None),
    tts_similarity_boost: Optional[float] = Form(default=None),
    tts_style: Optional[float] = Form(default=None),
    tts_use_speaker_boost: Optional[bool] = Form(default=None),
    user_id: str = Depends(get_current_user_id),
):
    settings = _get_voice_settings()

    audio_payload = await audio.read()
    if not audio_payload:
        raise HTTPException(status_code=400, detail="empty audio payload")

    stt = await asyncio.to_thread(
        _call_openai_stt_sync,
        settings=settings,
        filename=audio.filename or "voice.webm",
        content_type=audio.content_type or "audio/webm",
        payload=audio_payload,
    )
    transcript = (stt.text or "").strip()
    if not transcript:
        return {
            "status": "ignored",
            "user_id": user_id,
            "reason": "empty_transcript",
            "transcript": "",
        }

    turn = await voice_turn(
        VoiceTurnRequest(text=transcript, session_id=session_id, wake_word=wake_word),
        user_id=user_id,
    )

    out = {
        "status": "success",
        "user_id": user_id,
        "transcript": transcript,
        "stt": stt.model_dump(),
        "turn": turn,
    }

    if speak and str(turn.get("status")) == "success":
        assistant_text = str(turn.get("response") or "").strip()
        if assistant_text:
            tts_req = VoiceTTSRequest(
                text=assistant_text,
                provider=tts_provider,
                voice=tts_voice,
                format=tts_format,
                speed=tts_speed,
                stability=tts_stability,
                similarity_boost=tts_similarity_boost,
                style=tts_style,
                use_speaker_boost=tts_use_speaker_boost,
            )
            try:
                audio_bytes, mime = await _dispatch_tts(tts_req, settings)
                out["tts"] = {
                    "mime": mime,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                }
            except Exception as e:
                logger.warning("voice ptt tts failed: {}", e)
                out["tts_error"] = str(e)

    return out




