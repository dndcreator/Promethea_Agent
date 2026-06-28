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
- [ ] Chat path works with attached text-like files (`txt/md/csv/json/docx/pdf`) and routes image attachments through the RuntimeBlock/vision-or-fallback path without inventing unavailable visual details.
- [ ] Tool listing includes callable status and reasons.
- [ ] Workflow define/start/status paths work for linear and dependency-based runs.
- [ ] Memory and reasoning degraded paths expose machine-readable context where expected.
- [ ] Enterprise Brain is hidden when `org_brain.enabled=false` and available after enabling, saving, and restarting.

## 4. Voice Runtime

- [ ] Release notes clearly state that voice input is not a supported preview feature.
- [ ] If voice endpoints remain enabled, `GET /api/voice/capabilities` matches actual experimental/provider-dependent behavior.
- [ ] DeepSeek-only configurations are documented as not providing STT/audio transcription.
- [ ] Optional `/api/voice/ptt` smoke is run only when an OpenAI-compatible audio transcription provider is configured.

## 5. Security and Governance

- [ ] Cross-user workspace and session access checks enforced.
- [ ] High-risk tools require confirmation where policy expects it.
- [ ] Audit and trace events present for core failure paths.

## 6. Testing

- [ ] Unit and contract tests pass.
- [ ] Business journey tests pass.
- [ ] Voice route tests pass when voice dependencies/providers are included in the local test profile; otherwise the unsupported-provider boundary is documented.
- [ ] Release-focused regression tests pass:
  - `tests/test_files_routes.py`
  - `tests/test_chat_routes_args_resilience.py`
  - `tests/test_config_routes_contract.py`
- [ ] Test artifacts are confined to `.tmp/pytest-runtime/`; no new root-level `.pytest-*`, `tmp_*`, `_pytest_case_tmp`, or `_pytest_session_tmp` directories are created.
- [ ] No unexplained test skips for critical suites.

## 7. Documentation

- [ ] Docs index updated (`docs/README.md`).
- [ ] Any new endpoint/tool/workflow behavior documented.
- [ ] UI endpoint map reflects the current Vite UI (`http://127.0.0.1:5173`) and current modal capabilities.
- [ ] Attachment/multimodal behavior is documented as RuntimeBlock-based native vision when supported, with OCR/text fallback otherwise.
- [ ] Migration notes added for any behavior changes.

## 8. Frontend

- [ ] `cd UI && npm run build` passes in a local Node environment.
- [ ] Manual UI smoke passes: login, chat, attach file to chat, global search, memory inspector, workflow inspector, settings save.
- [ ] Enterprise Brain UI visibility follows `org_brain.enabled`.
- [ ] Homepage implementation preserves required functional entrypoints from `docs/ui-overview.md`.

## 9. Release Decision

- [ ] Decision recorded: `GO` or `NO-GO`.
- [ ] If `NO-GO`, blockers listed with owner and ETA.
- [ ] If `GO`, monitored rollout plan prepared.
