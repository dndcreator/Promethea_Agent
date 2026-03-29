# Release Checklist

Use this checklist before a release candidate is accepted.

## 1. Protocol and Surface

- [ ] `GET /api/ops/framework-check` returns `ok=true`.
- [ ] `GET /api/ops/surfaces` includes newly added endpoints.
- [ ] `GET /api/ops/protocol` reflects latest contract fields.

## 2. Health and Readiness

- [ ] `GET /api/status` returns expected service visibility.
- [ ] `GET /api/status/services` has no unexpected failed services.
- [ ] `GET /api/ops/readiness` is reviewed (`go/no-go` decision recorded).
- [ ] `GET /api/doctor` recommendations are reviewed and triaged.

## 3. Core Runtime

- [ ] Chat path works for standard text turns.
- [ ] Tool listing includes callable status and reasons.
- [ ] Workflow define/start/status paths work for linear and dependency-based runs.
- [ ] Memory and reasoning degraded paths expose machine-readable context where expected.

## 4. Voice Runtime

- [ ] `GET /api/voice/capabilities` matches actual behavior.
- [ ] `/api/voice/ptt` round-trip verified in local environment.
- [ ] ElevenLabs TTS configuration path validated when enabled.
- [ ] Unsupported provider behavior returns explicit 4xx errors.

## 5. Security and Governance

- [ ] Cross-user workspace and session access checks enforced.
- [ ] High-risk tools require confirmation where policy expects it.
- [ ] Audit and trace events present for core failure paths.

## 6. Testing

- [ ] Unit and contract tests pass.
- [ ] Business journey tests pass.
- [ ] Voice route tests pass.
- [ ] No unexplained test skips for critical suites.

## 7. Documentation

- [ ] Docs index updated (`docs/README.md`).
- [ ] Any new endpoint/tool/workflow behavior documented.
- [ ] Migration notes added for any behavior changes.

## 8. Release Decision

- [ ] Decision recorded: `GO` or `NO-GO`.
- [ ] If `NO-GO`, blockers listed with owner and ETA.
- [ ] If `GO`, monitored rollout plan prepared.

