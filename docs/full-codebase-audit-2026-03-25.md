# Promethea Full Codebase Audit (2026-03-25)

Scope:
- Gateway / HTTP / WS / Memory / Reasoning / Tool / Workflow / Voice / CLI / UI / docs / tests.
- Static engineering audit with immediate patching of high-value inconsistencies.

## 1. Audit Method

1. Full-repo marker scan (`TODO/FIXME/stub/NotImplemented/pass`) to locate risk hotspots.
2. Contract scan on protocol/ops/status/readiness/voice routes.
3. Business-flow review of gateway request paths:
   - `chat`
   - `chat.confirm`
   - `batch`
   - `workflow.*`
   - `tool.*`
   - `voice.*`
4. Test realism pass focused on end-to-end business journeys.
5. Documentation completeness pass against open-source project conventions.

## 2. Key Findings and Actions

### A. Voice Contract vs Real Behavior Mismatch

Finding:
- Voice capabilities reported `streaming_output=true`, but runtime is turn-based PTT.

Action:
- Updated capabilities to:
  - `streaming_output=false`
  - `interaction_mode=push_to_talk_turn`

Files:
- `gateway/http/routes/voice.py`

### B. STT Provider Gate Inconsistency

Finding:
- `/voice/stt` validated provider, but `/voice/ptt` directly called OpenAI STT path.

Action:
- Introduced `_dispatch_stt(...)` with provider gating.
- Reused it in both `/voice/stt` and `/voice/ptt`.
- Unsupported providers now return explicit `400`.

Files:
- `gateway/http/routes/voice.py`

### C. TTS Provider Validation Hardening

Finding:
- Unknown TTS providers silently fell back to OpenAI behavior.

Action:
- Added explicit validation in `_dispatch_tts(...)`.
- Unknown provider now returns `400`.

Files:
- `gateway/http/routes/voice.py`

### D. Business-Realistic Voice Coverage Missing

Finding:
- Voice routes had no dedicated high-value route-level tests.

Action:
- Added `tests/test_voice_routes.py` for:
  - capability contract correctness
  - unsupported STT/TTS provider behavior
  - PTT round-trip simulation (STT -> turn -> optional TTS)

Files:
- `tests/test_voice_routes.py`

### E. Documentation Completeness Gap

Finding:
- Existing docs are strong technically but lacked a single open-source-style index and release/testing operational docs.

Action:
- Added documentation suite:
  - `docs/README.md`
  - `docs/voice-runtime.md`
  - `docs/testing-strategy.md`
  - `docs/release-checklist.md`
- Updated root README to include readiness endpoint + docs hub link.

Files:
- `docs/README.md`
- `docs/voice-runtime.md`
- `docs/testing-strategy.md`
- `docs/release-checklist.md`
- `README.md`

## 3. Differential Positioning Check

Preserved:
- Local assistant experience remains first-class.
- Runtime-as-infrastructure abstraction remains exposed via protocol/ops/status surfaces.
- Memory + reasoning + workflow + tool governance remains core differentiation.

Not changed:
- No reduction of advanced capabilities.
- No UI capability rollback.
- No narrowing of protocol surface.

## 4. Remaining Work (Recommended Next Iteration)

1. Normalize reason-code contracts in memory/reasoning skip/fallback branches.
2. Reduce/retire `_run_async_blocking` fallback bridge where async path is already canonical.
3. Expand channel/plugin end-to-end fixtures beyond adapter contracts.
4. Add CI release-readiness artifact generation from tests + `/api/ops/readiness`.

## 5. Audit Confidence

- High confidence on protocol/voice/runtime path correctness for patched areas.
- Medium confidence on full-runtime execution in this environment due to local test runner availability constraints.

