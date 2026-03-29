# Voice Runtime Guide

This document describes what is implemented today for voice interaction and how to configure it safely.

## 1. Current Scope

Promethea voice is implemented as turn-based Push-To-Talk (PTT), not full duplex realtime conversation.

Implemented endpoints:
- `GET /api/voice/capabilities`
- `POST /api/voice/stt`
- `POST /api/voice/tts`
- `POST /api/voice/turn`
- `POST /api/voice/ptt`

Implemented clients:
- Web UI PTT button (`UI/voice.js`)
- CLI subcommands (`promethea voice ...`)

## 2. Provider Matrix

### STT
- Supported provider: `openai`
- Route behavior:
  - `voice.stt` and `voice.ptt` both enforce provider gating.
  - Unsupported `VOICE__STT_PROVIDER` returns `400`.

### TTS
- Supported providers:
  - `openai`
  - `elevenlabs`
- Unknown provider returns `400`.

## 3. ElevenLabs Notes

ElevenLabs is used for TTS only.

Required configuration:
- `VOICE__ELEVENLABS_API_KEY` (preferred), or `VOICE__API_KEY`
- A valid voice id:
  - `VOICE__VOICE`, or
  - request field `voice`

Optional tuning fields:
- `stability`
- `similarity_boost`
- `style`
- `use_speaker_boost`

## 4. Environment Variables

Common:
- `VOICE__PROVIDER`, `VOICE__MODEL`, `VOICE__VOICE`, `VOICE__FORMAT`, `VOICE__SPEED`

STT:
- `VOICE__STT_PROVIDER` (default `openai`)
- `VOICE__STT_MODEL` (default `gpt-4o-mini-transcribe`)

TTS:
- `VOICE__TTS_PROVIDER` (default `openai`)
- `VOICE__TTS_MODEL` (default `gpt-4o-mini-tts`)
- `VOICE__TTS_VOICE` (default `alloy`)
- `VOICE__TTS_FORMAT` (default `mp3`)
- `VOICE__TTS_SPEED` (default `1.0`)

OpenAI credentials:
- `VOICE__API_KEY` or `API__API_KEY`
- `VOICE__BASE_URL` / `VOICE__OPENAI_BASE_URL` / `API__BASE_URL`

ElevenLabs credentials:
- `VOICE__ELEVENLABS_API_KEY` (preferred), or `VOICE__API_KEY`
- `VOICE__ELEVENLABS_BASE_URL` (default `https://api.elevenlabs.io`)

## 5. Request Flows

### Text voice turn (`/voice/turn`)
1. Accept text + optional wake word.
2. If wake word is set but not matched, return `status=ignored`.
3. Dispatch `chat` through gateway protocol.
4. Return chat payload with `mode=voice_text_turn`.

### PTT flow (`/voice/ptt`)
1. Read uploaded audio.
2. STT transcription (provider-gated).
3. Call `/voice/turn` with transcript.
4. Optionally synthesize TTS of assistant response.
5. Return transcript + turn result + optional base64 audio.

## 6. Product Truths

- `streaming_output` in capabilities is currently `false`.
- Interaction mode is `push_to_talk_turn`.
- Full realtime voice session is not implemented yet.

## 7. Test Coverage

Voice route tests:
- `tests/test_voice_routes.py`

Covers:
- capabilities contract
- unsupported provider handling
- PTT round-trip simulation
- TTS provider validation

