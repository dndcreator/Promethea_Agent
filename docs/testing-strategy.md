# Testing Strategy

This project uses layered testing to balance speed, confidence, and product realism.

## 1. Test Layers

### Layer A: Unit Tests
- Goal: verify local logic with deterministic inputs.
- Typical modules:
  - policy checks
  - model mappers
  - serialization contracts

### Layer B: Service Contract Tests
- Goal: verify service APIs and response shapes.
- Typical modules:
  - config service
  - tool service
  - workflow engine
  - protocol surface contracts

### Layer C: Business Journey Tests
- Goal: simulate realistic user-facing workflows across multiple services.
- Typical paths:
  - `chat -> tool confirmation -> resume`
  - `batch -> workflow.define -> workflow.start -> workspace artifacts`
  - `tools.list -> tool.call`
  - provider-dependent voice route boundaries when an audio transcription provider is configured

## 2. Why Business Journey Tests Matter

Pure unit tests can pass while user-facing flows fail due to:
- integration wiring issues
- session/state transition bugs
- policy or permission mismatches
- payload shape drift across boundaries

Business tests are designed to catch these issues early.

## 3. Current High-Value Journey Suites

- `tests/test_mvp_business_smoke.py`
- `tests/test_business_journeys.py`
- `tests/test_voice_routes.py` for experimental/provider-dependent voice API boundaries

## 4. Gate Recommendations

Before release, require:
1. Core contract tests passing.
2. Business journey suites passing.
3. Readiness endpoints healthy or explicitly acknowledged degradation.

## 5. CI Prioritization

Fast PR stage:
- unit + contract tests

Main branch stage:
- business journeys
- readiness/report generation

Pre-release stage:
- full test matrix + manual sanity checklist

## 6. Known Constraints

- External providers (OpenAI / ElevenLabs / Neo4j / MCP remote) should be mocked in CI.
- Local environment tests should avoid hard network requirements unless explicitly marked integration.
- DeepSeek-only configurations do not provide STT/audio transcription, so voice-input tests are not part of the supported preview smoke path unless an audio transcription provider is explicitly configured.

## 7. Test Artifact Policy

- Test artifacts are expected to be created under `.tmp/pytest-runtime/`.
- `tests/conftest.py` sets `TEMP`, `TMP`, `TMPDIR`, `PYTEST_DEBUG_TEMPROOT`, and `PROMETHEA_TEST_TMP_ROOT` to this runtime directory.
- `tests/run_all_tests.py` also uses `.tmp/pytest-runtime/runner/` for pytest `--basetemp`.
- On normal completion, pytest removes `.tmp/pytest-runtime/`.
- If a run is interrupted, the expected residue is a single `.tmp/pytest-runtime/` directory.
- Tests should not create new root-level `.pytest-*`, `tmp_*`, `_pytest_case_tmp`, or `_pytest_session_tmp` directories.
- Cleanup must not target runtime user data such as `config/users/`, uploaded files, `memory/`, `logs/`, or the L0 raw-log files `memory/raw_log.jsonl` and `memory/raw_log.state.json`.

## 8. Release-Focused Coverage

Recent release-focused regression tests cover:

- user file upload/search and RuntimeBlock-based chat attachment context
- stored-only behavior for image attachments without OCR text on text-only models
- chat route preservation of structured attachments without prompt-level merging
- enterprise `org_brain` configuration fields in the basic config view

Recommended targeted command:

```powershell
python -m pytest tests/test_files_routes.py tests/test_chat_routes_args_resilience.py tests/test_config_routes_contract.py -q
```

## 9. Next Expansion Targets

- Channel adapter end-to-end fixtures for major official channels.
- More negative-path tests for memory/reasoning degradation reason codes.
- Release-grade scenario replay packs for regression prevention.
