from __future__ import annotations

import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.params import Form as FormParam
from fastapi.responses import Response
from pydantic import BaseModel, Field

from gateway.protocol import RequestType
from gateway.public_contracts import VoiceCapabilities, VoiceDiscoveryRequest, VoiceModelList, VoiceTTSRequest, VoiceTranscription
from gateway import voice_runtime
from .auth import get_current_user_id
from ..dispatcher import dispatch_gateway_method

router = APIRouter()


class VoiceTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=64000)
    session_id: Optional[str] = None
    wake_word: Optional[str] = None


async def _invoke(operation):
    try:
        return await operation
    except voice_runtime.VoiceError as error:
        raise HTTPException(error.status, detail={"code": error.code, "message": error.code}) from None


async def _audio(upload):
    payload = await upload.read(voice_runtime.MAX_AUDIO_BYTES + 1)
    if not payload or len(payload) > voice_runtime.MAX_AUDIO_BYTES:
        raise HTTPException(413 if payload else 400, detail={"code": "VOICE_AUDIO_TOO_LARGE" if payload else "VOICE_EMPTY_AUDIO"})
    return payload


@router.get("/voice/status", response_model=VoiceCapabilities)
async def voice_status(user_id: str = Depends(get_current_user_id)):
    return voice_runtime.capabilities(user_id)


@router.get("/voice/capabilities")
async def get_voice_capabilities(user_id: str = Depends(get_current_user_id)):
    state = voice_runtime.capabilities(user_id)
    defaults = {
        "stt_provider": state.stt.provider, "stt_model": state.stt.model,
        "tts_provider": state.tts.provider, "tts_model": state.tts.model,
        "tts_voice": state.tts.voice, "tts_format": state.tts.format, "tts_speed": state.tts.speed,
        "openai_base_url": next((endpoint.base_url for endpoint in (state.stt, state.tts) if endpoint.provider == "openai"), ""),
        "elevenlabs_base_url": state.tts.base_url if state.tts.provider == "elevenlabs" else "",
    }
    return {"status": "success", "user_id": user_id, "voice": {
        "input": "audio+text", "wake_word": True, "streaming_output": False,
        "interaction_mode": "push_to_talk_turn", "stt": state.stt.configured, "tts": state.tts.configured,
        "providers": {"stt": ["openai"], "tts": ["openai", "elevenlabs"]},
        "defaults": defaults,
        "endpoints": {"stt": "/api/voice/stt", "tts": "/api/voice/tts", "turn": "/api/voice/turn", "ptt": "/api/voice/ptt"},
    }}


@router.post("/voice/models", response_model=VoiceModelList)
async def voice_models(request: VoiceDiscoveryRequest, user_id: str = Depends(get_current_user_id)):
    return VoiceModelList(models=await _invoke(voice_runtime.models(user_id, request.kind)))


@router.post("/voice/stt", response_model=VoiceTranscription)
async def voice_stt(audio: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    result = await _invoke(voice_runtime.transcribe(user_id, audio.filename or "voice.webm", audio.content_type or "audio/webm", await _audio(audio)))
    return VoiceTranscription(user_id=user_id, stt=result)


@router.post("/voice/tts")
async def voice_tts(request: VoiceTTSRequest, user_id: str = Depends(get_current_user_id)):
    audio, mime = await _invoke(voice_runtime.synthesize(user_id, request))
    return Response(content=audio, media_type=mime, headers={"Cache-Control": "no-store"})


@router.post("/voice/turn")
async def voice_turn(request: VoiceTurnRequest, user_id: str = Depends(get_current_user_id)):
    text, wake_word = request.text.strip(), (request.wake_word or "").strip()
    if not text:
        raise HTTPException(400, detail="text is required")
    if wake_word and wake_word.lower() not in text.lower():
        return {"status": "ignored", "user_id": user_id, "reason": "wake_word_not_detected"}
    payload = await dispatch_gateway_method(RequestType.CHAT, {"message": text, "session_id": request.session_id, "stream": False}, user_id=user_id)
    return {"status": "success", "mode": "voice_text_turn", "user_id": user_id, **payload}


def _form(value, default=None):
    return default if isinstance(value, FormParam) else value


@router.post("/voice/ptt")
async def voice_ptt(
    audio: UploadFile = File(...), session_id: Optional[str] = Form(default=None),
    wake_word: Optional[str] = Form(default=None), speak: bool = Form(default=True),
    tts_provider: Optional[str] = Form(default=None), tts_voice: Optional[str] = Form(default=None),
    tts_format: Optional[str] = Form(default=None), tts_speed: Optional[float] = Form(default=None),
    tts_stability: Optional[float] = Form(default=None), tts_similarity_boost: Optional[float] = Form(default=None),
    tts_style: Optional[float] = Form(default=None), tts_use_speaker_boost: Optional[bool] = Form(default=None),
    user_id: str = Depends(get_current_user_id),
):
    result = await voice_stt(audio=audio, user_id=user_id)
    if not result.stt.text:
        return {"status": "ignored", "user_id": user_id, "reason": "empty_transcript", "transcript": ""}
    turn = await voice_turn(VoiceTurnRequest(text=result.stt.text, session_id=_form(session_id), wake_word=_form(wake_word)), user_id)
    output = {"status": turn.get("status", "success"), "user_id": user_id, "transcript": result.stt.text, "stt": result.stt.model_dump(), "turn": turn}
    if _form(speak, True) and turn.get("status") == "success" and turn.get("response"):
        try:
            request = VoiceTTSRequest(text=turn["response"], provider=_form(tts_provider), voice=_form(tts_voice), format=_form(tts_format), speed=_form(tts_speed),
                stability=_form(tts_stability), similarity_boost=_form(tts_similarity_boost), style=_form(tts_style), use_speaker_boost=_form(tts_use_speaker_boost))
            raw, mime = await voice_runtime.synthesize(user_id, request)
            output["tts"] = {"mime": mime, "audio_base64": base64.b64encode(raw).decode("ascii")}
        except voice_runtime.VoiceError as error:
            output["tts_error"] = error.code
        except ValueError:
            output["tts_error"] = "VOICE_TEXT_TOO_LONG"
    return output




