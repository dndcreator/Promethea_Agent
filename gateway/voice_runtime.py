"""User-scoped speech provider I/O; conversation decisions remain in Core."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from gateway.public_contracts import VoiceCapabilities, VoiceEndpointStatus, VoiceSTTResult, VoiceTTSRequest
from gateway.user_secrets import _resolve_value, load_user_secrets, resolve_llm_runtime_settings

MAX_AUDIO_BYTES = 24 * 1024 * 1024
MIME_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg", "aac": "audio/aac", "flac": "audio/flac", "pcm": "audio/pcm"}


class VoiceError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class SpeechEndpoint:
    provider: str
    model: str
    base_url: str
    api_key: str = field(default="", repr=False)
    voice: str = ""
    format: str = "mp3"
    speed: float = 1

    def public(self, kind):
        try:
            parsed = urlsplit(self.base_url)
            parsed.port  # Validate malformed ports before creating a provider request.
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not (parsed.username or parsed.password or parsed.query or parsed.fragment) and not any(char.isspace() for char in self.base_url)
        except ValueError:
            parsed, valid_url = urlsplit(""), False
        safe_url = self.base_url if valid_url else ""
        reason = "disabled" if self.provider == "disabled" else "unsupported_provider" if self.provider not in ({"openai"} if kind == "stt" else {"openai", "elevenlabs"}) else "endpoint_required" if not self.base_url else "invalid_endpoint" if not valid_url else "model_required" if not self.model else "voice_required" if kind == "tts" and not self.voice else None
        return VoiceEndpointStatus(provider=self.provider, model=self.model, base_url=safe_url, voice=self.voice, format=self.format, speed=self.speed, configured=reason is None, api_key_configured=bool(self.api_key), reason=reason)


def settings_for(user_id: str):
    values = load_user_secrets(user_id, ensure=False)
    read = lambda key: _resolve_value(values, "VOICE__" + key)
    main = resolve_llm_runtime_settings(user_id)
    common_url = read("BASE_URL") or read("OPENAI_BASE_URL")
    endpoints = {}
    for kind in ("stt", "tts"):
        prefix = kind.upper()
        provider = (read(prefix + "_PROVIDER") or (read("PROVIDER") if kind == "tts" else "") or "disabled").lower()
        if provider == "openai-compatible":
            provider = "openai"
        base = read(prefix + "_BASE_URL") or (read("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io" if provider == "elevenlabs" else common_url or main.get("base_url", ""))
        key = read(prefix + "_API_KEY")
        if provider == "elevenlabs":
            key = key or read("ELEVENLABS_API_KEY") or (read("API_KEY") if read("PROVIDER") == "elevenlabs" else "")
        # Never forward a main/common key to a different explicitly selected endpoint.
        elif not key:
            if base.rstrip("/") == (common_url or main.get("base_url", "")).rstrip("/"):
                key = read("API_KEY")
            if not key and base.rstrip("/") == str(main.get("base_url") or "").rstrip("/"):
                key = main.get("api_key", "")
        model = read(prefix + "_MODEL") or (read("MODEL") if kind == "tts" else "")
        voice = read("TTS_VOICE") or read("VOICE") or ("alloy" if provider == "openai" else "")
        fmt = (read("TTS_FORMAT") or read("FORMAT") or "mp3").lower()
        try:
            speed = float(read("TTS_SPEED") or read("SPEED") or "1")
            if not 0.25 <= speed <= 4:
                raise ValueError()
        except ValueError:
            speed = 1
        endpoints[kind] = SpeechEndpoint(provider, model, base, key, voice, fmt, speed)
    return endpoints, read("SPEAK_REPLIES").lower() == "true"


def capabilities(user_id):
    endpoints, speak = settings_for(user_id)
    return VoiceCapabilities(stt=endpoints["stt"].public("stt"), tts=endpoints["tts"].public("tts"), speak_replies=speak)


def endpoint_for(user_id, kind):
    endpoint = settings_for(user_id)[0][kind]
    status = endpoint.public(kind)
    if not status.configured:
        raise VoiceError("VOICE_" + str(status.reason).upper())
    return endpoint


async def request(endpoint, method, path, *, limit=MAX_AUDIO_BYTES, **kwargs):
    headers = {"xi-api-key": endpoint.api_key} if endpoint.provider == "elevenlabs" else {"Authorization": "Bearer " + endpoint.api_key} if endpoint.api_key else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=False) as client:
            async with client.stream(method, endpoint.base_url.rstrip("/") + path, headers=headers, **kwargs) as response:
                if response.status_code in {401, 403}:
                    raise VoiceError("VOICE_PROVIDER_AUTH_FAILED", 502)
                if response.status_code == 429:
                    raise VoiceError("VOICE_PROVIDER_RATE_LIMITED", 429)
                if not 200 <= response.status_code < 300:
                    raise VoiceError("VOICE_PROVIDER_ERROR", 502)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise VoiceError("VOICE_RESPONSE_TOO_LARGE", 502)
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "").split(";", 1)[0]
    except httpx.TimeoutException:
        raise VoiceError("VOICE_PROVIDER_TIMEOUT", 504) from None
    except httpx.InvalidURL:
        raise VoiceError("VOICE_INVALID_ENDPOINT") from None
    except httpx.HTTPError:
        raise VoiceError("VOICE_PROVIDER_UNAVAILABLE", 502) from None


def parse_json(payload):
    try:
        return json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise VoiceError("VOICE_INVALID_RESPONSE", 502) from None


async def transcribe(user_id, filename, content_type, payload):
    endpoint = endpoint_for(user_id, "stt")
    if not payload:
        raise VoiceError("VOICE_EMPTY_AUDIO")
    if len(payload) > MAX_AUDIO_BYTES:
        raise VoiceError("VOICE_AUDIO_TOO_LARGE", 413)
    raw, _ = await request(endpoint, "POST", "/audio/transcriptions", limit=1024 * 1024,
                           data={"model": endpoint.model, "response_format": "json"}, files={"file": (filename, payload, content_type)})
    body = parse_json(raw)
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise VoiceError("VOICE_INVALID_RESPONSE", 502)
    try:
        return VoiceSTTResult(text=body["text"].strip(), language=body.get("language"), duration_seconds=body.get("duration"))
    except ValidationError:
        raise VoiceError("VOICE_INVALID_RESPONSE", 502) from None


async def synthesize(user_id, req: VoiceTTSRequest):
    endpoint = endpoint_for(user_id, "tts")
    if req.provider and req.provider not in {endpoint.provider, "openai-compatible" if endpoint.provider == "openai" else endpoint.provider}:
        raise VoiceError("VOICE_PROVIDER_OVERRIDE_REQUIRES_CONFIGURATION")
    if not req.text.strip():
        raise VoiceError("VOICE_EMPTY_TEXT")
    fmt, voice = req.format or endpoint.format, req.voice or endpoint.voice
    if fmt not in MIME_TYPES:
        raise VoiceError("VOICE_INVALID_FORMAT")
    if endpoint.provider == "elevenlabs":
        body = {"text": req.text, "model_id": endpoint.model}
        controls = {key: getattr(req, key) for key in ("stability", "similarity_boost", "style", "use_speaker_boost") if getattr(req, key) is not None}
        if controls:
            body["voice_settings"] = controls
        output = {"mp3": "mp3_44100_128", "wav": "wav_44100", "pcm": "pcm_44100", "opus": "opus_48000_64"}.get(fmt)
        if not output:
            raise VoiceError("VOICE_INVALID_FORMAT")
        raw, mime = await request(endpoint, "POST", "/v1/text-to-speech/" + quote(voice, safe=""), json=body, params={"output_format": output})
    else:
        raw, mime = await request(endpoint, "POST", "/audio/speech", json={"model": endpoint.model, "voice": voice, "input": req.text, "response_format": fmt, "speed": req.speed or endpoint.speed})
    if not raw or (mime and not mime.startswith(("audio/", "application/octet-stream"))):
        raise VoiceError("VOICE_INVALID_AUDIO", 502)
    expected = MIME_TYPES[fmt]
    aliases = {"audio/x-wav": "audio/wav", "audio/mp3": "audio/mpeg", "audio/x-flac": "audio/flac", "audio/opus": "audio/ogg"}
    if mime and mime != "application/octet-stream" and aliases.get(mime, mime) != expected:
        raise VoiceError("VOICE_INVALID_AUDIO", 502)
    return raw, expected


async def models(user_id, kind):
    endpoint = settings_for(user_id)[0][kind]
    # Discovery may precede choosing a model, but never uses a caller-supplied URL/key.
    if endpoint.provider not in {"openai", "elevenlabs"}:
        raise VoiceError("VOICE_UNSUPPORTED_PROVIDER")
    if endpoint.public(kind).reason in {"invalid_endpoint", "endpoint_required"}:
        raise VoiceError("VOICE_INVALID_ENDPOINT")
    raw, _ = await request(endpoint, "GET", "/v1/models" if endpoint.provider == "elevenlabs" else "/models", limit=1024 * 1024)
    value = parse_json(raw)
    rows = value if isinstance(value, list) else value.get("data", []) if isinstance(value, dict) else []
    if not isinstance(rows, list):
        raise VoiceError("VOICE_INVALID_RESPONSE", 502)
    return list(dict.fromkeys(str(row.get("model_id") or row.get("id")) for row in rows if isinstance(row, dict) and (row.get("model_id") or row.get("id")) and (endpoint.provider != "elevenlabs" or row.get("can_do_text_to_speech"))))[:256]
