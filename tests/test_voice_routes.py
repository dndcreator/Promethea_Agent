"""Voice routes over real user settings and provider HTTP contracts."""
import json

import httpx
import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from gateway import user_secrets, voice_runtime
from gateway.http.routes import voice
from gateway.http.routes.auth import get_current_user_id

REAL_ASYNC_CLIENT = httpx.AsyncClient

@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", tmp_path / "users")
    monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / "missing.env")
    for user in ("alice", "bob"):
        user_secrets.update_user_secrets(user, {
            "VOICE__STT_PROVIDER": "openai", "VOICE__TTS_PROVIDER": "openai",
            "VOICE__STT_MODEL": "transcriber", "VOICE__TTS_MODEL": "speaker",
            "VOICE__STT_BASE_URL": "https://speech.invalid/v1", "VOICE__TTS_BASE_URL": "https://speech.invalid/v1",
            "VOICE__STT_API_KEY": user + "-stt-secret", "VOICE__TTS_API_KEY": user + "-tts-secret",
            "VOICE__TTS_VOICE": "alloy", "VOICE__SPEAK_REPLIES": "false",
        })
    requests = []
    response = {"code": 200, "body": b"ID3-test-audio", "mime": "audio/mpeg"}

    def provider(request):
        requests.append(request)
        if request.url.path.endswith("/transcriptions"):
            return httpx.Response(200, content=json.dumps(response.get("transcript", {"text": "hello", "language": "en"})), headers={"content-type": "application/json"})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "speaker"}, {"id": "transcriber"}]})
        return httpx.Response(response["code"], content=response["body"], headers={"Content-Type": response["mime"]})

    monkeypatch.setattr(voice_runtime.httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(provider), **kwargs))
    app = FastAPI()
    app.include_router(voice.router, prefix="/api")

    async def identity(x_test_user: str = Header(default="alice")):
        return x_test_user

    app.dependency_overrides[get_current_user_id] = identity
    with TestClient(app) as client:
        yield client, requests, response, app


def test_configured_is_not_a_claim_of_provider_health_and_never_contains_keys(configured):
    client, requests, _, _ = configured
    result = client.get("/api/voice/status")
    assert result.status_code == 200
    assert result.json()["stt"]["configured"] and result.json()["tts"]["configured"]
    assert requests == []
    assert "secret" not in result.text
    legacy = client.get("/api/voice/capabilities").json()
    assert legacy["voice"]["interaction_mode"] == "push_to_talk_turn"
    assert legacy["voice"]["streaming_output"] is False
    assert legacy["voice"]["defaults"]["tts_model"] == "speaker"


def test_real_speech_serialization_and_user_scoping(configured):
    client, requests, response, _ = configured
    response.update(body=b"RIFF-test-audio", mime="audio/wav")
    for user in ("alice", "bob"):
        result = client.post("/api/voice/tts", headers={"x-test-user": user}, json={"text": "hello", "format": "wav"})
        assert result.status_code == 200 and result.content == b"RIFF-test-audio"
        assert result.headers["content-type"] == "audio/wav"
        sent = requests[-1]
        assert sent.headers["authorization"] == "Bearer " + user + "-tts-secret"
        body = json.loads(sent.content)
        assert body["response_format"] == "wav" and "format" not in body
        assert body["model"] == "speaker" and body["voice"] == "alloy"
        assert result.headers["cache-control"] == "no-store"


def test_transcription_preserves_real_uploaded_type_and_model(configured):
    client, requests, _, _ = configured
    result = client.post("/api/voice/stt", files={"audio": ("recording.m4a", b"test-audio", "audio/mp4")})
    assert result.status_code == 200 and result.json()["stt"]["text"] == "hello"
    assert result.json()["user_id"] == "alice"
    sent = requests[-1]
    assert sent.headers["authorization"] == "Bearer alice-stt-secret"
    assert b"audio/mp4" in sent.content and b"recording.m4a" in sent.content
    assert b"transcriber" in sent.content
    assert b"alice-tts-secret" not in sent.content


@pytest.mark.parametrize("code,expected", [(401, "VOICE_PROVIDER_AUTH_FAILED"), (429, "VOICE_PROVIDER_RATE_LIMITED"), (500, "VOICE_PROVIDER_ERROR"), (302, "VOICE_PROVIDER_ERROR")])
def test_provider_failures_are_bounded_and_redacted(configured, code, expected):
    client, requests, response, _ = configured
    response.update(code=code, body=b"echoed credential: alice-tts-secret")
    result = client.post("/api/voice/tts", json={"text": "hello"})
    assert result.status_code >= 400
    assert result.json()["detail"]["code"] == expected
    assert "alice-tts-secret" not in result.text
    assert len(requests) == 1


def test_provider_cannot_mislabel_an_audio_format(configured):
    client, _, _, _ = configured
    assert client.post("/api/voice/tts", json={"text": "hello", "format": "wav"}).json()["detail"]["code"] == "VOICE_INVALID_AUDIO"


@pytest.mark.parametrize("failure,expected", [(httpx.ReadTimeout, "VOICE_PROVIDER_TIMEOUT"), (httpx.ConnectError, "VOICE_PROVIDER_UNAVAILABLE")])
def test_transport_failures_are_structured(configured, monkeypatch, failure, expected):
    client, _, _, _ = configured

    # Use the provider HTTP boundary, not the voice service implementation.
    def transport(request):
        raise failure("provider secrets must not escape", request=request)

    monkeypatch.setattr(voice_runtime.httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(transport), **kwargs))
    result = client.post("/api/voice/tts", json={"text": "hello"})
    assert result.status_code in {502, 504}
    assert result.json()["detail"]["code"] == expected
    assert "secrets" not in result.text


def test_invalid_audio_empty_input_and_limits_are_not_success(configured):
    client, requests, response, _ = configured
    response.update(body=b'{"error":"not audio"}', mime="application/json")
    assert client.post("/api/voice/tts", json={"text": "hello"}).json()["detail"]["code"] == "VOICE_INVALID_AUDIO"
    assert client.post("/api/voice/tts", json={"text": "x" * 4097}).status_code == 422
    assert client.post("/api/voice/stt", files={"audio": ("empty.wav", b"", "audio/wav")}).status_code == 400
    assert len(requests) == 1


def test_discovery_is_explicit_and_does_not_infer_audio_support_from_names(configured):
    client, requests, _, _ = configured
    result = client.post("/api/voice/models", json={"kind": "tts"})
    assert result.json()["models"] == ["speaker", "transcriber"]
    assert requests[-1].method == "GET"
    assert "speaker" == client.get("/api/voice/status").json()["tts"]["model"]


def test_endpoint_changes_cannot_reuse_an_unrelated_main_key(configured, monkeypatch):
    from config import config
    monkeypatch.setattr(config.api, "api_key", "MAIN-PRIVATE")
    monkeypatch.setattr(config.api, "base_url", "https://main.invalid/v1")
    user_secrets.update_user_secrets("new-user", {"VOICE__TTS_PROVIDER": "openai", "VOICE__TTS_MODEL": "local",
        "VOICE__TTS_BASE_URL": "http://localhost:9999/v1", "VOICE__TTS_VOICE": "local-voice"})
    endpoint = voice_runtime.settings_for("new-user")[0]["tts"]
    assert endpoint.api_key == "" and endpoint.base_url == "http://localhost:9999/v1"


def test_unauthenticated_cannot_use_speech_or_discover_accounts(configured):
    client, requests, _, app = configured
    app.dependency_overrides.clear()
    assert client.post("/api/voice/tts", json={"text": "hello"}).status_code == 401
    assert requests == []


def test_elevenlabs_format_and_auth_match_provider_contract(configured):
    client, requests, _, _ = configured
    user_secrets.update_user_secrets("alice", {"VOICE__TTS_PROVIDER": "elevenlabs",
        "VOICE__TTS_BASE_URL": "https://eleven.invalid", "VOICE__TTS_VOICE": "voice-id", "VOICE__TTS_MODEL": "multilingual"})
    result = client.post("/api/voice/tts", json={"text": "hello", "format": "mp3"})
    assert result.status_code == 200
    sent = requests[-1]
    assert sent.url.path == "/v1/text-to-speech/voice-id"
    assert sent.url.params["output_format"] == "mp3_44100_128"
    assert sent.headers["xi-api-key"] == "alice-tts-secret"
    assert "authorization" not in sent.headers


@pytest.mark.parametrize("mode", ["success", "tts_failure", "confirmation"])
def test_ptt_uses_actual_gateway_and_commits_history(configured, monkeypatch, tmp_path, mode):
    from tests.support.http_runtime import app_at
    from tests.support.runtime import ScriptedModel
    from gateway.tools.spec import SideEffectLevel
    actions = [{"action": "answer", "content": "Hello back"}]
    if mode == "confirmation":
        actions = [{"action": "tool_call", "tool_name": "workspace.write_file", "args": {"path": "output.txt", "content": "hello"}}]
    app, host = app_at(tmp_path, ScriptedModel(actions), monkeypatch)
    if mode == "confirmation":
        host.capability_service.tool_registry.resolve(tool_name="workspace.write_file", params={}).side_effect_level = SideEffectLevel.EXTERNAL_WRITE
    if mode == "tts_failure":
        configured[2].update(code=500)
    app.include_router(voice.router, prefix="/api")
    app.dependency_overrides[get_current_user_id] = lambda: "alice"
    user_secrets.update_user_secrets("alice", {"VOICE__STT_PROVIDER": "openai", "VOICE__STT_MODEL": "transcriber",
        "VOICE__STT_BASE_URL": "https://speech.invalid/v1", "VOICE__TTS_PROVIDER": "openai",
        "VOICE__TTS_MODEL": "speaker", "VOICE__TTS_BASE_URL": "https://speech.invalid/v1", "VOICE__TTS_VOICE": "alloy"})
    with TestClient(app) as client:
        result = client.post("/api/voice/ptt", files={"audio": ("input.webm", b"voice", "audio/webm")}, data={"session_id": "speech", "speak": "true"})
    assert result.status_code == 200, result.text
    assert result.json()["transcript"] == "hello"
    if mode == "confirmation":
        assert result.json()["status"] == "needs_confirmation"
        assert "tts" not in result.json()
        assert all(not request.url.path.endswith("/speech") for request in configured[1])
        assert host.message_manager.get_pending_confirmation("speech", user_id="alice") is not None
        return
    assert result.json()["turn"]["response"] == "Hello back"
    if mode == "tts_failure":
        assert result.json()["status"] == "success" and result.json()["tts_error"] == "VOICE_PROVIDER_ERROR"
        assert "tts" not in result.json()
    else:
        assert result.json()["tts"]["audio_base64"]
    messages = host.message_manager.get_messages("speech", user_id="alice")
    assert [row["content"] for row in messages] == ["hello", "Hello back"]


@pytest.mark.parametrize("body", [{"text": 12}, {"text": "hello", "duration": "not-a-duration"}, {"text": "hello", "duration": float("nan")}, ["unexpected"]])
def test_invalid_transcription_payload_is_a_safe_error(configured, body):
    client, _, response, _ = configured
    response['transcript'] = body
    result = client.post("/api/voice/stt", files={"audio": ("input.wav", b"audio", "audio/wav")})
    assert result.status_code == 502 and result.json()["detail"]["code"] == "VOICE_INVALID_RESPONSE"


def test_disabled_invalid_url_and_oversized_upload_fail_before_success(configured, monkeypatch):
    client, requests, _, _ = configured
    user_secrets.update_user_secrets("alice", {"VOICE__TTS_PROVIDER": "disabled"})
    assert client.post("/api/voice/tts", json={"text": "hello"}).json()["detail"]["code"] == "VOICE_DISABLED"
    user_secrets.update_user_secrets("alice", {"VOICE__TTS_PROVIDER": "openai", "VOICE__TTS_BASE_URL": "https://user:secret@speech.invalid/v1"})
    status = client.get("/api/voice/status").json()["tts"]
    assert not status["configured"] and status["base_url"] == ""
    assert client.post("/api/voice/models", json={"kind": "tts"}).status_code == 400
    assert not requests
    user_secrets.update_user_secrets("alice", {"VOICE__TTS_BASE_URL": "https://speech.invalid/v1"})
    monkeypatch.setattr(voice_runtime, "MAX_AUDIO_BYTES", 4)
    assert client.post("/api/voice/stt", files={"audio": ("large.wav", b"12345", "audio/wav")}).status_code == 413
