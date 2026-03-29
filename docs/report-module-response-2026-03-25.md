# Report Response by Module (2026-03-25)

This document maps report observations to concrete engineering actions in current codebase.

## 1. Gateway Integration and Service Wiring

Report focus:
- Risk of official tool registration order causing partial tool visibility.

Assessment:
- Valid concern historically.
- Current code includes post-wiring re-registration in `gateway_integration.py`, which closes init-order gaps.

Action:
- Confirmed second-pass registration remains in place after memory/reasoning/workflow initialization.

Residual risk:
- If future boot flow bypasses `GatewayIntegration.inject_dependencies`, this guarantee can regress.

## 2. Config Defaults and New-User Baseline

Report focus:
- Default runtime not fully enabled by default.

Assessment:
- Core defaults already mostly enabled in `config/default.json`.
- Some fallback code paths still treated missing fields as disabled.

Action completed:
- `gateway/reasoning_service.py`: missing `reasoning.enabled` now defaults to `True`; `moirai_auto_start` defaulted to `True` in normalization.
- `gateway/http/routes/config.py`: basic-view fallback defaults for `memory.enabled` and `reasoning.enabled` switched to `True`.
- `gateway/http/routes/ops.py`: capability fallback values for memory/reasoning switched to `True`.

Residual risk:
- Environment-specific dependency unavailability (Neo4j/MCP/provider) still causes degraded runtime, as expected.

## 3. Voice Runtime and ElevenLabs

Report focus:
- Voice route consistency and provider behavior.

Assessment:
- STT/TTS provider handling needed stricter route parity.

Action completed:
- `/voice/stt` and `/voice/ptt` now share provider-gated STT dispatch.
- Unknown TTS provider now returns explicit 400.
- Capabilities now declare turn-based truthfully: `streaming_output=false`, `interaction_mode=push_to_talk_turn`.

Current implementation boundary:
- ElevenLabs is implemented for TTS only.
- STT currently OpenAI provider path.

## 4. Protocol Surface and Client Decoupling

Report focus:
- Ensure protocol routes are exposed and authoritative.

Assessment:
- `/api/ops/*` contract/discovery stack is in place and usable.

Action completed:
- Added docs to make protocol-first integration explicit:
  - `docs/api-reference.md`
  - `docs/cli-reference.md`

Residual risk:
- Clients hardcoding routes instead of discovery endpoints may still drift over time.

## 5. Testing Strategy and Business Realism

Report focus:
- Unit-heavy tests need more business-like path coverage.

Assessment:
- Direction is correct.

Action completed:
- Added/kept route-level voice tests (`tests/test_voice_routes.py`).
- Updated config route contract test to current minimal/basic view behavior.
- Added default-fallback tests:
  - `tests/test_config_route_contract.py`
  - `tests/test_reasoning_service.py`

Environment blocker:
- Current shell session has no accessible Python/pytest executable (`python`, `py`, `pytest` unavailable in PATH), so run result cannot be confirmed in this session.

## 6. Documentation Shape (Open-source Style)

Action completed:
- Added and linked docs for external developer onboarding and protocol consumption:
  - `docs/api-reference.md`
  - `docs/cli-reference.md`
- Normalized externally-facing wording from MVP-centric labels to v1 baseline in core docs.

## 7. Objective Conclusion

- Report direction is generally valid on runtime truthfulness, default behavior, and integration clarity.
- Current project is close to production-usable in architecture; remaining risk is mostly in environment-dependent runtime readiness and CI execution coverage.
- The highest practical next step is to restore deterministic test execution in your local/anaconda environment and gate releases on those route/business smoke suites.
