# Testing Strategy

Promethea separates Runtime correctness from model quality. Deterministic tests
must not require paid models, personal memory or host-desktop interaction.
See [the audit and coverage matrix](testing-audit.md) for retained risks and
[tests/README.md](../tests/README.md) for the entry point.

## Layers And Ownership

| Layer | Purpose | Actual Boundary |
| --- | --- | --- |
| Unit | Deterministic contracts, policy, state transitions, data transformations | Explicit file list in `tests/evaluation/suites.json`; mixed files stay integration |
| Module integration | Cross-service contracts, ownership, approvals, persistence and recovery | Existing service tests plus `tests/integration/test_runtime_journeys.py`; model outputs scripted at the model boundary |
| Intelligent behavior | Model decisions, extraction, recall relevance, situation and initiative | Versioned `tests/evaluation/behavior.json`, run independently of normal product operation |
| System | HTTP/authentication, streaming, actual artifacts and process restart | `tests/system/` composes real routes/services; isolated source snapshot for TCP/restart |
| Browser | Real React rendering, interactions, races and disclosure | Existing Playwright tests mostly use API fixtures; not real-provider E2E |
| Live acceptance | Operator-owned deployment/provider checks and real business tasks | Explicit opt-in only; no automatic credentials or personal data |

Tests at different boundaries are not duplicates merely because they concern
the same capability. A new regression should fail on the original defect and
assert observable facts, not just a successful response. Replace the external
model/network boundary when needed; do not replace the whole service whose
behavior the test claims to verify.

## Deterministic Execution

Install the existing project development dependencies (`pip install -e ".[dev]"`).
Use Node 22 or later for the existing UI strip-types test command.

```powershell
python tests/run_all_tests.py                         # default: unit
python tests/run_all_tests.py --suite critical --repeat 3 --timeout 300
python tests/run_all_tests.py --suite integration
python tests/run_all_tests.py --suite system
python tests/run_all_tests.py --suite full --coverage --timeout 600
python tests/run_all_tests.py --suite full --output .tmp/evaluations/current --compare .tmp/evaluations/before/junit.xml
python -m pytest -q tests/test_memory_regressions.py   # focused file
```

The timeout covers all repetitions. A failed repetition remains a failure even
if the next attempt passes. Exit-code failures, missing JUnit reports, expected
failures and optional skips are recorded separately. A timeout terminates only
the runner's owned child process tree. `--file` without an explicit suite runs
that file regardless of layer; an explicitly selected layer still filters it.
The generic runner does not instrument provider calls and reports their count
as unknown; only the behavior runner meters its own model boundary.

`critical/contracts/smoke/core/business` are risk filters, not additional layers.
Release preflight runs full once instead of repeating overlapping profiles.
Two strict xfails expose known keyword-recommendation diagnostic defects
(`runtime_status`, `graph_relations`); they are not a general-Agent quality
score and must not be silently counted as passes.

CI runs Python on three operating systems, SDK generation/typecheck/tests,
React lint/tests/build and a bounded Chromium source-fixture smoke. Changes to
CI configuration are not evidence of a successful remote CI run.

## Behavior Evaluation

The initial corpus has 22 versioned cases covering direct/tool actions,
unsupported capabilities, recovery, cross-turn updates, memory extraction and
Gate semantics, SQLite recall/isolation, current/stale observations and bounded
Ambient behavior. Cases include positive, negative, boundary and curated
historical failures. They contain synthetic data, not personal logs.

```powershell
python scripts/run_evaluations.py --mode validate
# Real local recall; no model endpoint needed and no paid calls:
python scripts/run_evaluations.py --mode live --group retrieval --repeat 3

# After explicitly configuring evaluation-only credentials:
python scripts/run_evaluations.py --mode live --group action --repeat 3 --max-calls 40 --max-tokens 80000 --deadline 300
```

Only explicit `PROMETHEA_EVAL_AGENT_BASE_URL`, `PROMETHEA_EVAL_AGENT_API_KEY`,
and `PROMETHEA_EVAL_AGENT_MODEL` are accepted. Product credentials are not
inherited. Live evaluations copy whitelisted source and evaluation assets into
a disposable directory, without `.env`, user stores, logs or downloaded models.
Real services operate on synthetic per-case storage. No new product loop or
production policy exists in the evaluator. The classification adapter calls
production extraction/verification/Gate; retrieval currently calls the real
SQLite store and adapter, not Neo4j or embedding quality.

Defaults: 3 trials, 30 shared model admissions, 16,000 reported tokens, 800 output
tokens per call, 180 seconds total, 60 seconds per case, stop after 3 failures.
Select one group and set its budget explicitly; default limits need not fit all
22 cases. There are no hidden provider retries. Failed API admissions consume
call budget. Missing usage stops further calls and leaves cost unknown.
Input reservations use a conservative text-byte estimate, not a provider quote.

Optional `--max-cost-usd` requires explicit agent/Judge
`PROMETHEA_EVAL_<ROLE>_INPUT_USD_PER_MILLION` and
`PROMETHEA_EVAL_<ROLE>_OUTPUT_USD_PER_MILLION`. These are operator-supplied
flat text tariffs, not invoices or cache pricing. Reports never invent prices.

### Independent Judge

`judge.json` v2 defines separate task-outcome and behavior axes, plus dimensions,
blocker diagnosis and evidence references. There is no combined verdict:
`task_outcome = completed/incomplete/unverifiable`,
`behavior = correct/incorrect/insufficient_evidence`.
`task_fulfillment` belongs only to the task axis; it cannot make an otherwise
correct boundary response behaviorally wrong. Known incomplete reasons require
Runtime-owned evidence, not an assistant claim or missing observations alone.
Unknown reasons stay `unknown`. Group reports count both axes separately.
Hard failures in ownership, permissions, files or persistence cannot be
overruled by semantic scores. The Agent's own claims are never the final grade.
No Judge calls occur during ordinary product use or deterministic tests.

Three calibration seeds were approved by the project owner on 2026-10-28
(Beijing). Their v2 translations preserve verified output, false success and
insufficient desktop evidence separately. On 2026-10-29 the owner approved the
two-axis policy; a fourth synthetic fixture instantiates the Runtime-confirmed
unavailable capability rule: task incomplete, behavior correct. Its metadata
explicitly distinguishes policy approval from individual fixture review. The
no-evidence seed remains unverifiable/insufficient evidence with unknown cause.
These are minimal seeds, not a representative gold dataset or proof of accuracy.

Configure separate `PROMETHEA_EVAL_JUDGE_BASE_URL/API_KEY/MODEL` and add
`--judge`. An identical tested model/endpoint is refused. Every invocation
first runs each reviewed calibration case three times, requiring at least
90% accuracy, 90% repeat agreement and zero false passes. Invalid evidence IDs,
missing dimensions and contradictory axes are rejected. Calibration votes and
separate task/behavior confusion matrices are recorded. False behavioral passes
and false task completions both disqualify a Judge. Human-reviewed labels
alone do not enable scores: the configured Judge must actually pass calibration.
Expand human labels and inspect disagreements before trusting release scores.
CLI acceptance compares the two axes against case expectations, defaulting to
completed/correct. A negative capability-boundary case explicitly expects
incomplete/correct: that regression can pass without counting the task as
completed. Unexpected uncertainty remains unresolved, not a semantic pass.
Unjudged cases remain unmeasured, not semantic passes. Hard failures remain
failures even when a Judge diagnoses correct behavior under a capability limit.
Judge parsing/provider failures are evaluation errors, not an Agent behavior
label, and do not overwrite an already computed hard-check result.

### Comparison And Regression Records

Reports include case/rubric/calibration hashes, source hash and Git revision,
model identities, trials, failure types, elapsed time, calls, known tokens and
known/unknown cost. Group hard-check rates have Wilson intervals; correlated
trials and tiny corpora do not establish broad statistical significance.

`--compare <behavior.json>` requires the same mode, corpus, rubric, cases,
repetitions and complete runs. It reports differences, not an automatic claim
of improvement. Unjudged semantic quality remains `not_measured`.
`--mode replay --records <behavior.json>` reruns evidence checks (and optional
independent Judge), not the Agent: replay cannot show that new Runtime code
improved previously recorded behavior.

For each incident, add a synthetic fixed case tied to the failed authority,
preserve its expected state/artifact, and run before/after under the same
configuration. Keep raw personal traces local. Test count and line coverage are
diagnostics, not capability scores.

## Browser And Deployment Checks

Use a Vite development server: source fixtures under `UI/tests/` are deliberately
excluded from the production build.

```powershell
# Terminal 1, from UI/; choose another port if occupied:
npm run dev -- --host 127.0.0.1 --port 5186 --strictPort
# Terminal 2, from the repository:
$env:CANVAS_TEST_BROWSER_CHANNEL='msedge'
$env:PROMETHEA_UI_TEST_URL='http://127.0.0.1:5186'
python tests/run_all_tests.py --suite browser --timeout 300
```

An installed Edge or Playwright Chromium is required. Run UI/SDK checks separately:
`npm --prefix UI test`, `npm --prefix UI run lint`,
`npm --prefix UI run build`, `npm --prefix sdk/typescript run generate:check`,
`npm --prefix sdk/typescript run typecheck`, `npm --prefix sdk/typescript test`.
Browser fixture success is not full production-shell + Gateway + provider E2E.

Only the following live suite is the opt-in read-only deployment probe:

```powershell
$env:PROMETHEA_TEST_BASE_URL='http://127.0.0.1:8000'
$env:PROMETHEA_TEST_TOKEN='<dedicated-test-account-token>'
python tests/run_all_tests.py --suite live --live
```

Explicitly enabled but missing deployment settings fail rather than silently
skip. This probe checks readiness, profile and session listing, not model
quality or desktop controls. Existing host-interaction tests need separate
operator consent and must never be enabled against valuable files.

## Artifact Policy

Direct pytest uses `.tmp/pytest-runtime/`; runner trials use a dedicated
`<output>/pytest-runtime/` so concurrent invocations cannot clean each other's
data. Both remove their own temporary tree on normal completion.
Interrupted cleanup may leave residue there. Persistent reports, coverage and
local evidence belong in ignored `.tmp/evaluations/`. The runner chooses unique
output directories by default; an explicit output path may be overwritten.
Versioned, sanitized audit/baseline summaries live in `tests/evaluation/`.
Cleanup must never target personal runtime directories.

## Manual Business Acceptance

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

### External Knowledge Pilot

`tests/fixtures/web_research_cases.json` contains 20 real research questions, not
fixed answers or a completed benchmark. Run them with a dedicated account and
your configured model/search provider after the basic business pass. Do not force
unnecessary extra searches on a question already resolved by reliable material.
For ambiguous, version-sensitive or contradictory findings, check whether the
Agent autonomously reads sources and searches again when needed.

For each case record the session/run identity, provider attempts (including empty
results), retrieved URL/title/time/source fingerprint, relevant quoted passage,
answer citations, model calls, elapsed time and known/unknown cost. Distinguish
search snippets from actual page reads. Review whether the cited text supports the
answer and belongs to the applicable version; a nonempty response alone is not a
pass. Mark blocked access, empty extraction, missing provider configuration and
unsupported content separately from model reasoning failures. The automated
scripted-loop tests establish the protocol path, not a score on these questions.
