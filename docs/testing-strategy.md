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
  - capability service
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

### Browser Test Target

The browser suite includes source fixtures at `UI/tests/message-content.html` as
well as the actual application shell. Run the complete suite against a Vite
**development server**; the production build deliberately excludes these test
pages. Pointing fixture tests at `vite preview` loads the SPA fallback instead
and produces misleading failures. Always set the URL explicitly:

```powershell
# Terminal 1, from UI/; choose another port if occupied.
npm run dev -- --host 127.0.0.1 --port 5186 --strictPort

# Terminal 2, from the project root, using the project virtual environment.
$env:CANVAS_TEST_BROWSER_CHANNEL = 'msedge'
$env:PROMETHEA_UI_TEST_URL = 'http://127.0.0.1:5186'
python -m pytest -q
```

`msedge` selects an installed Edge browser. A configured browser must be installed;
this acceptance run should not download dependencies or enable
`PROMETHEA_LIVE_TEST` against real accounts/desktops. Separately run the UI
production build and inspect production-shell flows. Browser API fixtures must
follow current public response shapes, including an empty array for a deployment
with no enabled messaging channels. Inject failures at the intended operation,
not by assuming that the first global config request belongs to Settings.

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

- Operator-owned live acceptance for bot/application channels, beyond the existing local protocol and delivery fixtures.
- More negative-path tests for memory/reasoning degradation reason codes.
- Release-grade scenario replay packs for regression prevention.

## 10. Manual Business Acceptance

Use a dedicated test account. Automated suites use synthetic models/providers;
passing them does not validate a live provider, search quality, or the operator's
database connection. Do not switch memory backends during the first acceptance
pass. Keep the sandbox enabled and use disposable workspace files, not real
trading accounts or valuable host documents.

Before starting, wait for `/health` to identify a ready Gateway and inspect
`/api/health/memory`. Configure the model through the normal settings. Canvas
authoring requires `self_evolve.enabled=true` and an installed Playwright browser;
on Windows, `SELF_EVOLVE__BROWSER_CHANNEL=msedge` selects an installed Edge.

| Scenario | Acceptance Check |
|---|---|
| Sign in, open an old conversation, create a new one | Session contents and language remain correct; no stuck preparation state. |
| Ask a simple question, then a workspace file creation/read task | Ordinary chat does not invoke unnecessary tools; actual outputs match committed observations and files. |
| Request an approval-gated action and reject it; retry and approve | Rejection executes nothing and preserves conversation access; approval executes the intended batch once. |
| Search and follow a source | Workbench shows actual queried/fetched sources and usable links; distinguish provider/network failures from fabricated success. |
| State a durable preference, open a new conversation, then contradict it | Inspect actual recall and any review proposal; compatible facts should not be mistaken for conflicts. Never confirm replacement without reading the candidate. |
| Create a small form/calculator in Canvas; type without blurring, refresh after saves, retain and reopen | Inputs persist, calculations work, rapid edits do not corrupt revisions, and retained apps survive reopening. Test a newly generated app: old retained artifacts intentionally keep their bundled renderer. |
| Start a multi-step Workflow; pause/resume and restart the Gateway | Run identity, completed steps and artifacts remain traceable; no claim of exactly-once remote effects across a hard crash. |
| Explicitly bind a run to an owned Task and inspect Gap state | Public Task data retains requirements; checked assertions and inferred resolutions stay distinct. Ordinary unbound chat gaps are transient. |
| Use guest chat, then sign in and switch accounts | Guest conversation stays transient and cannot access tools, personal memory or files; accounts cannot read each other's state. |
| Inspect Metrics with known, missing and explicit zero model rates | Unknown/partial costs must not appear as a zero or complete total; cached tokens use the matching tariff and refreshing prices does not reprice old calls. Use the deployment settings in `docs/configuration.md`, not sample prices. |
| Enable Ambient with a bounded focus, interact, then disable it | Observe real autonomous runs and scoped expressions; dismissed choices do not imply tool approval, and disabled authority cannot start further actions. Runtime must stay running. |
| Open a generated component app, inspect/change its state, then close it | Semantic snapshots match actual stored values and revisions; stale interactions fail; closed/expired views become unknown, not inferred user intent. Custom undeclared apps are not claimed to be semantically understood. |
| Keep a Canvas open through a note, choice, response and updated note | Expressions mount beside the intended component, do not duplicate into chat, retain edits and update in place. Wrong-app/stale-definition expressions disappear; feedback does not approve tools or mutate app state. |
| Move from the composer to Canvas, its input and an artifact preview | Only the active region reports focus; component attention includes the correct app/definition. Inspect the model-call manifest to confirm actual file excerpts and prioritized semantics, not just collection logs. |
| Bind a configured messaging platform, send text, reject a sensitive operation, then unlink | Replies enter the correct owned conversation; rejection executes nothing; duplicate callbacks do not rerun the model; queued work loses authority after unlink. Complete the platform-specific checks in `docs/channels/README.md`. |

For API acceptance, create a Task with `POST /api/tasks`, then send its `task_id`
with `POST /api/chat` or `client.runs.run/stream`. Query `GET /api/tasks/{task_id}`
before and after restart. Another account must not read or mutate that Task.
An approval issued before a task objective change, pause, or execution lease
replacement must not execute the old action; resume/replan through the current
Task lifecycle instead.

Record failures with the input, expected/actual behavior, UI language, provider,
memory backend, session/task identity and approximate time. Redact secrets. Inspect
work products, not only assistant wording or tool-success counters. Live model
quality, optional multimodal providers, and full task token savings need this
manual pass; deterministic tests do not establish them.
