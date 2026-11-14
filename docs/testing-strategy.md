# Testing Strategy

Promethea separates Runtime correctness from model quality. Deterministic tests
must not require paid models, personal memory or host-desktop interaction.
See [the audit and coverage matrix](testing-audit.md) for retained risks and
[tests/README.md](../tests/README.md) for the entry point.

## Continuous Maintenance Acceptance

`tests/test_continuous_observation.py` exercises registered sources through the
real temporal scheduler, persisted outbox, idempotent Runtime log, SelfModel,
batched Ambient admission and Moirai feedback. Test publication-before-ack
failure, source-owner isolation, source permission changes, failed activation
without cursor acknowledgement, and experience-store recovery without executing
the completed actions again. Observation collection itself calls no model.

`tests/system/test_continuous_code_maintenance.py` runs on Windows with the native
restricted-token runner. It actually repairs an isolated Python file, persists a
test approval, reconstructs Runtime state, approves that exact call and runs the
regression assertions in a subprocess. Goal Gap resolution uses the successful
Runtime test receipt, and the execution episode is recorded separately from user
memory. Model decisions are scripted: this is not a live diagnosis score. The
existing sandbox is write-restricted/partial; arbitrary commands are not approved
automatically or described as fully isolated.

Public-source acceptance is independently opt-in and anonymous:

```powershell
$env:PROMETHEA_LIVE_GITHUB_REPO = 'owner/project'
..\.venv\Scripts\python.exe -m pytest tests/system/test_github_observation_live.py
```

This checks GitHub metadata -> tool runtime -> durable events -> Ambient Task
admission, with zero model requests and no GitHub mutations. It does not claim a
live-model repair, PR delivery, unknown-effect crash certification or an advantage
over a fixed workflow. Real-model trials require separate spend authorization.

## Per-Call Output Budget Pilot

The separate per-call candidate pilot is:

```powershell
..\.venv\Scripts\python.exe scripts/evaluate_call_budget.py --live --env-file .env.eval --max-cost-usd 0.30 --output .tmp/evaluations/call-budget-20261101
```

This command requires a **new** explicit authorization; it does not inherit the
Native/budget experiment's remaining funds. Three new cases, three arms and two
repeats are frozen in `tests/evaluation/call-budget-live.json`. Shared evaluation
Runtime contracts make short outputs genuinely bounded; merely requesting a
concise answer or an answer-only phase does not qualify. Contracts and permission
checks are identical across arms. The candidate uses 4,096 only for the enforced
short form, otherwise 8,192, and reuses existing truncation recovery. Report scope
changes separately from recovery growth. This is not a shipped product policy or
a predictor of arbitrary future actions. No extra classifier or Thinking switch
is added. Source archives, request ledgers and independent gold/browser checks
remain required; unfinished groups are not scored as task failures.

## Native Acceptance And Independent Budget Replication

The current full-production browser regression is
`tests/system/test_native_production_browser.py`. Its normal case uses a local
scripted HTTP provider with real React/App, SDK, Gateway, disk stores and process
restarts, including restored approval and a single inert side-effect receipt:

```powershell
$env:CANVAS_TEST_BROWSER_CHANNEL = 'msedge'
..\.venv\Scripts\python.exe -m pytest tests/system/test_native_production_browser.py -k 'not live_authorized'
```

The separate live case requires a new explicit authorization, evaluation-only
`.env.eval` settings and `PROMETHEA_NATIVE_LIVE_USD=0.10`. It meters **all** model
traffic, including greetings, through one proxy retained across backend restarts.
The conservative reserve of each request must fit the remaining total budget;
unknown usage prevents resuming. Existing ledgers cannot be silently replaced.
See the audit for the completed cohort's scope and unresolved background-call
exposure. Neither a passing scripted run nor this limited live journey certifies
arbitrary process termination during an external side effect.

`tests/test_model_protocol.py` exercises the product Chat codec through
`PrometheaConversation` and ActionService, including streaming, approval/denial,
checkpoint restart, unknown effects, compaction and receipt isolation. Experimental
and product decoders share `gateway/model_protocol.py`; the older append-only
pilot transcript is not the production implementation.

`tests/evaluation/budget-independent-live.json` freezes four new tasks and the
same structural predictor before any paid request. Every task uses all three
policies twice (24 planned runs), with identical Prompt JSON, tools, acceptance
checks and recovery. The prospective underestimation category is not selected
after observing results. Browser calibration includes correct code, broken
semantics and a prose-only negative control.

With explicit authorization, run the combined isolated experiment:

```powershell
..\.venv\Scripts\python.exe scripts/evaluate_native_budget.py --live --env-file .env.eval --max-cost-usd 0.75 --output .tmp/evaluations/native-budget-20261101
```

The three Native smoke cases and 24 budget runs share **one in-memory admission
ledger**. No cost reset occurs between phases; request content and the conservative
reserve are fsynced before sending. Per-request reserve is capped at $0.03,
requests time out at 120 seconds and SDK retries are disabled. Unknown usage stops
the experiment and retains the request reserve. A budget/deadline stop leaves
uncompleted runs unscored, not failed. This command always needs a fresh directory
and a new explicit authorization; it does not silently restart an earlier budget.
The launcher archives the clean source snapshot before creating deployment state;
archives, credentials and evidence remain ignored runtime artifacts. The completed
2026-11-01 cohort and its limitations are recorded in the testing audit.

The earlier 2026-11-01 live Native acceptance uses the product codec and real Action/Capability path,
with a single-provider metered test transport. Product streaming and restart have
offline integration coverage; this is not live coverage of every provider, MCP,
Canvas, or an end-to-end desktop UI. Compare functional completion and cost per
delivered goal first, not response length or configured output ceilings.

## Layers And Ownership

| Layer | Purpose | Actual Boundary |
| --- | --- | --- |
| Unit | Deterministic contracts, policy, state transitions, data transformations | Explicit file list in `tests/evaluation/suites.json`; mixed files stay integration |
| Module integration | Cross-service contracts, ownership, approvals, persistence and recovery | Existing service tests plus `tests/integration/test_runtime_journeys.py`; model outputs scripted at the model boundary |
| Intelligent behavior | Model decisions, extraction, recall relevance, situation and initiative | Versioned `tests/evaluation/behavior.json`, run independently of normal product operation |
| System | HTTP/authentication, streaming, actual artifacts and process restart | `tests/system/` includes the actual production launcher, plus explicitly composed HTTP Runtime journeys |
| Browser | Real React rendering, interactions, races and disclosure | Fixture-based UI regressions plus `test_production_browser.py` against the real launcher/API; no live-model quality claim |
| Live acceptance | Operator-owned deployment/provider checks and real business tasks | Explicit opt-in only; no automatic credentials or personal data |

Tests at different boundaries are not duplicates merely because they concern
the same capability. A new regression should fail on the original defect and
assert observable facts, not just a successful response. Replace the external
model/network boundary when needed; do not replace the whole service whose
behavior the test claims to verify.

The calculator budget-stop regression is covered by
`tests/test_action_completion.py`, `tests/system/test_http_runtime.py` and
`tests/system/test_chat_completion_browser.py`: actual file writes, no execution
during final completion, nonempty model/Runtime reports, SSE/HTTP parity and
reopened history. The browser case uses real React, SDK and HTTP services with
scripted model I/O, not API interception; it does not claim live-model calculator
generation or successful Canvas mounting. Task tests additionally verify explicit
continuation without repeating the committed write and goal-progress persistence.

`tests/test_action_protocol.py` checks complete-fence compatibility without JSON
repair, concatenated actions, nested duplicate fields, non-JSON constants, exact
argument preservation, batch IDs, approval blocking and safe streamed disclosure.
It also exercises independent recovery families, the shared step/final-response
boundary, checkpoint restoration and original-response versus canonical-history
audit records. These scripted-model checks establish protocol behavior, not a
measured improvement in live-model delivery or cost. Keep all budget-comparison
arms on the same parser and recovery policy before evaluating prediction.

## Deterministic Execution

### Runtime Efficiency Experiments

`scripts/evaluate_runtime_efficiency.py` compares the versioned ten-case offline
corpus through real Runtime/Workspace services and scripted model I/O:

```powershell
python scripts/evaluate_runtime_efficiency.py --output .tmp/evaluations/efficiency-before
# Apply the change, then use the same corpus and machine:
python scripts/evaluate_runtime_efficiency.py --output .tmp/evaluations/efficiency-after --baseline .tmp/evaluations/efficiency-before/report.json
```

Offline request characters and scripted model calls are not provider tokens,
cache hits, real-model quality or invoiced savings. Raw observations/artifacts
must remain intact. Never regenerate the old report using modified code and
present it as a historical baseline.

For live paired policy tests, put only `PROMETHEA_EVAL_*` settings in ignored
`.env.eval`: AGENT_BASE_URL, AGENT_API_KEY, AGENT_MODEL,
AGENT_INPUT_USD_PER_MILLION, AGENT_OUTPUT_USD_PER_MILLION and MAX_COST_USD
(all with the prefix). Use current conservative price ceilings. No product
credentials are inherited. SDK retries are disabled in the evaluation endpoint;
every paid request shares one call/token/time/currency admission budget. Missing
provider usage stops further calls. The calculator check uses a sandboxed browser
with all network requests blocked, not assistant claims.

```powershell
python scripts/evaluate_runtime_efficiency.py --live --env-file .env.eval --output .tmp/evaluations/efficiency-live
# Continue within the ORIGINAL currency ceiling, rather than reset spending:
python scripts/evaluate_runtime_efficiency.py --live --env-file .env.eval --case long-source-tail --previous-report .tmp/evaluations/efficiency-live/report.json --output .tmp/evaluations/efficiency-followup
```

The live comparison shares current Runtime safety and stable-prefix behavior;
it ablates fixed-output/legacy observation limits against adaptive/compact ones,
not historical Python checkouts. Alternate A/B order; compare only fully paired,
fully evaluated cases. Keep costs of incomplete attempts in total spend. Report
provider tokens, cache usage, actual artifact checks and failure types. One
repetition is a smoke experiment, not a statistically established improvement.
The known-cost estimate is not an invoice; product SDK-level call metrics also
cannot reveal hidden transport retries by an upstream SDK/server.

### Goal Progress Versus Output Length

`scripts/evaluate_task_progress.py` reuses the isolated Runtime and evaluation
endpoint for a three-arm output-budget experiment: fixed 2,000, fixed 8,192,
and adaptive 2,000 to 8,192 tokens. All arms share eight decision steps, the same
8,000/32,000-character Observation policy, recovery rules, tools and prompts.
The fixed-large control separates adaptation from merely permitting more output.
This is not the previous two-factor Observation/recovery ablation.

The versioned `tests/evaluation/task-progress-live.json` defines calculator
repair, quotation validation and persisted to-do interactions. Before execution
and after committed observations, an evaluator records actual artifact versions
and independently runs browser assertions. Golden inputs/results are not sent
back to the Agent. Report initial/final checks, first verified delivery, gains,
regressions, repeated observations, code artifacts, calls, output tokens and
conservative cost per verified goal. Code length, reasoning length and longer
answers earn no points. Calls after the last check gain include necessary final
reporting; repeated reads are not automatically classified as useless.

```powershell
# No provider requests; do not invent historical intermediate artifact versions:
python scripts/evaluate_task_progress.py --previous .tmp/evaluations/efficiency-live/report.json --output .tmp/evaluations/task-progress-previous
# Only after NEW explicit spending authorization; CLI budget applies to this run:
python scripts/evaluate_task_progress.py --live --env-file .env.eval --max-cost-usd 0.50 --repeat 2 --output .tmp/evaluations/task-progress-live
```

Live execution copies distributable source into the existing disposable snapshot
mechanism, excludes operator config/data, disables personal memory and reads only
the explicitly selected evaluation credentials. Browser checks use independent
contexts, a synthetic origin and a restrictive CSP/network route; they do not
execute generated Python/shell code on the host. The browser canary must pass
before any paid request. Model time and grader time are separate. A single shared
call/token/time/currency cap admits requests; no hidden SDK retries. Unknown
billing or evaluator failure stops further work. Use a fresh output directory;
this runner does not resume or silently reset the original experiment budget.

Use a recorded seeded shuffle of task/arm order and repeat each task twice by default. Compare only groups with
all three arms evaluated, including genuine functional failures; quota stops
and evaluator failures remain visible but are not Agent failures. Report total
spending including incomplete groups. If no output truncation occurs, the sample
does not demonstrate adaptive recovery effectiveness. This small experiment
tests within-run progress and standalone code delivery, not statistical superiority,
production Canvas mounting, cross-restart continuity or long-term cognition.

### Declared-Contract Budget Prediction

`tests/evaluation/budget-prediction-live.json` defines a separate held-out pilot:
Unicode scratchpad, bill splitter and persistent inventory. Compare fixed 8,192,
predicted fixed, and predicted adaptive. Prediction uses named fields/actions/
persistent collections explicitly provided to every arm as delivery requirements.
The candidate weighted count selects 2,048/4,096/8,192; absent a contract, fall
back conservatively to 8,192. Weights and thresholds are experimental hypotheses,
not a proven complexity estimator. No keywords, hidden checks, model classifier
or as-yet-unselected tool action are used. The B/C initial prediction is identical;
only C can increase its allowance on truncation, through current Runtime recovery.

```powershell
python scripts/evaluate_task_progress.py --live --corpus tests/evaluation/budget-prediction-live.json --seed 20261031 --env-file .env.eval --max-cost-usd 0.50 --repeat 2 --output .tmp/evaluations/budget-prediction-live
```

Use separate spending authorization and a fresh directory. Before the first paid
call, retain the corpus, source hash, resolved policies and schedule in `plan.json`
and `corpus.json`. All arms share the corrected parser/recovery and standalone
workspace tools; the Agent cannot access the evaluator/browser checks. Reference
and deliberately broken implementations validate the grader before execution.
The live report records actual per-request allowances, functional gains, failures,
artifact versions, input/output/cache tokens and conservative cost. Do not adjust
thresholds or rerun failed cases inside the same pilot. This evaluates a declared
contract prior, not general natural-language budget prediction or per-step phase
adaptation. Leave product defaults unchanged until representative evidence exists.

### Four-Category Budget Pilot

The follow-up `tests/evaluation/budget-four-category-live.json` pre-registers one
case per simple/medium/large/underestimated category. Three existing regression
tasks anchor the previous pilot; a new CSV reconciliation page probes semantic
complexity missed by the unchanged structural predictor. Full parsing, validation,
aggregation and money rules are public requirements. No minimum code length,
hidden requirement or forced truncation is imposed. Category labels and browser
answers are not used by the predictor. B/C initial limits are identical; only
real provider truncation allows C to expand. Keep Prompt JSON fixed in all arms.

```powershell
# NEW authorization required; a four-case single-repeat pilot, not 108 trials:
python scripts/evaluate_task_progress.py --live --corpus tests/evaluation/budget-four-category-live.json --repeat 1 --request-timeout 120 --max-request-cost-usd 0.03 --max-cost-usd 0.50 --env-file .env.eval --output .tmp/evaluations/budget-four-category
```

The report includes per-category paired results, actual token/call costs,
recovery retries and observed allowance growth. JSON browser assertions compare
actual structured results, not substrings. Calibrate the grader with correct and
incorrect CSV implementations before paid requests. No growth in a real-model
pilot means expansion benefit remains untested, not that the task must be rerun
until it truncates. Keep all incomplete/non-paired costs in the admission ledger.

### Protocol Reliability Pilot

`scripts/evaluate_protocol.py` compares Prompt JSON with experimental native
canonical-action functions through the same ActionService and CapabilityService.
Ten cases cover direct answers, arithmetic, file reads/writes, batches, missing
file recovery, capability inspection, absent capability resolution and approval.
The approval fixture has no real external send; any invocation is a safety failure.
Both modes retain the same registry/schema context, validation, four-decision
limit, one final-only request and 8,192 allowance. Native functions encode the
canonical actions, not a second tool registry or per-tool strict schemas.

```powershell
# Requires separate, explicit live authorization:
python scripts/evaluate_protocol.py --live --env-file .env.eval --max-cost-usd 0.50 --max-request-cost-usd 0.03 --output .tmp/evaluations/protocol-pilot
```

Native reasoning and tool-call receipt associations are replayed as required by
the [provider](https://api-docs.deepseek.com/guides/thinking_mode/#tool-calls)
and included in input costs. No extra summarizer or Agent loop is
introduced. The adapter is evaluation-only; the normal product protocol does not
switch. One trial per task/mode is a pilot, not statistical proof or a production
compatibility claim. Compare only complete task pairs. A provider/adapter failure
stops the experiment instead of being scored as a task failure.

The prototype supports append-only text histories only. It fails closed on
rewritten/compacted history and is not integrated with product streaming or
checkpoint restoration. Native pilot success does not establish production
readiness. Required tool checks assert successful observations; a case explicitly
expecting a failed read must separately assert the failure. Calling an operation
is not proof that it worked. Corpus v2 explicitly names capability-request versus
parameter-inspection paths because this pilot tests both action encodings, not
free-form planner quality.

Before transport, the evaluator durably appends the actual request, its hash,
input byte size, output allowance and conservative reservation to `requests.jsonl`.
Credentials are not part of the request body. Native schemas and replayed reasoning
are included in admission. Successful usage settles the record; timeout/crash leaves
that specific request reserved. Unknown usage stops further calls. Journal failure
before sending prevents transport; malformed journals are not silently treated as
zero exposure. All evidence remains ignored local evaluation data. The CLI uses
disposable source/workspaces, never personal memory or valuable host files.

An interrupted paid pilot is not silently resumed. If the operator explicitly
authorizes a new attempt inside the original currency ceiling, use a fresh output
directory and `--prior-run <original-report>` to carry known spending and reserve
unreceipted requests. `--request-timeout 120` applies equally to every arm, without
SDK retries. Legacy failed receipts lacking input size require an explicit
`--unknown-input-token-cap` based on that provider's context limit; this can reserve
most of the budget and prevent the planned repetitions. New failure receipts keep
input bytes. Reports distinguish current known costs, prior known costs, unknown
reserves and overall usage uncertainty. An upper exposure estimate is not actual
spend. Repeated/nested restart ledgers are deliberately unsupported; never reset
the ceiling or splice an abandoned trial into the new paired cohort.

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

The current corpus has 37 versioned cases covering direct/tool actions,
unsupported capabilities, recovery, cross-turn updates, memory extraction and
Gate semantics, SQLite recall/isolation, current/stale observations and bounded
Ambient behavior. Cases include positive, negative, boundary and curated
historical failures. They contain synthetic data, not personal logs.
Each of action, memory classification, retrieval, situation, Ambient,
continuity and delegation has 5-7 cases. `tests/test_ci_runner.py` guards
the group/risk structure, not a target total. Executable Gold expectations are
engineering-reviewed contracts over synthetic facts, not additional individually
human-reviewed Judge labels. Do not call an unmeasured model a passing model.

Four cross-service Agent journeys in
`tests/integration/test_agent_business_tasks.py` verify autonomous local work,
parent/child artifact delivery and context isolation, persistent memory after
database reopening, and a Canvas expression/feedback/edit/next-turn cycle.
Their offline model is scripted; the services, files, SQLite and component state
are real. Canvas service interaction is not a full browser/provider E2E test.

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
37 cases. There are no hidden provider retries. Failed API admissions consume
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
Judge identity and calibration hash must also match. Reports include per-case
acceptance changes and call/token/estimated-cost deltas, not only group averages;
an improved hard check does not establish improved semantic quality. Keep the
Agent identity in comparisons so intentional model changes remain visible.
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

### Production Startup Acceptance

`tests/system/test_production_startup.py` runs the actual `start_gateway_service.py`
in a disposable source deployment, with production lifespan, plugin discovery,
service wiring and real SQLite/identity/file stores. It covers startup, HTTP
registration/login, upload, `environment.inspect` through the real batch/tool
boundary, process restart and persisted identity/file access. Malformed deployment
config and a file blocking workspace-directory creation must produce a nonzero
exit without false readiness, scheduler startup or repeated health polling.
These cases are included in full, critical and smoke execution.

`tests/system/test_production_browser.py` uses real React and Vite against that
production process. It performs registration/login/upload/read/reload without
Playwright API interception or dependency overrides. It requires installed UI/SDK
dependencies and `CANVAS_TEST_BROWSER_CHANNEL`; CI includes it alongside the
existing fixture browser checks. Synthetic screenshots and launcher diagnostics
are retained under ignored `.tmp/production-qa/`.

```powershell
python -m pytest -q tests/system/test_production_startup.py
$env:CANVAS_TEST_BROWSER_CHANNEL='msedge'
python -m pytest -q tests/system/test_production_browser.py
```

No personal `.env`, accounts, logs or databases are copied. Speech/embedding
providers and cloud credentials are not inherited. Browser/desktop controllers
are disabled in the test deployment; filesystem and environment controllers are
real. A no-credential loopback-only model endpoint prevents paid model access;
these tests do not score LLM behavior, Neo4j integration, computer control or
first-install dependency downloads. Real startup acceptance complements, rather
than replaces, unit tests and live-provider task evaluation.

Speech regression uses `tests/test_voice_routes.py`, SDK `voice.test.mjs` and
`tests/test_voice_browser.py`. Network responses and microphone input are synthetic;
provider request encoding, user isolation, ordinary Chat/history, approval waiting,
audio failure preservation and resource cleanup remain observable assertions.
For live acceptance, explicitly configure a dedicated STT/TTS service and test
sample synthesis/download, recording/transcription, normal chat and optional spoken
replies in Settings. Check the provider's actual usage separately; do not interpret
chat token totals as speech charges. No audio provider is called by CI.

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

Direct pytest creates a unique run under `.tmp/pytest-runtime/`; runner trials
use a unique run under `<output>/pytest-runtime/` when the output is in the
checkout. Python temp files, pytest fixtures and child process temp files use
that run. Normal completion cleans only that run. An explicit `--basetemp`
must be a new directory under the checkout's `.tmp/`.

On Windows, use the repository wrapper for dependency installation, browser
downloads and test launches. It redirects only the command's environment
and stores caches under `.tmp/test-storage/` on the checkout drive:

```powershell
.\scripts\with-test-storage.ps1 python -m pip install -e ".[dev]"
.\scripts\with-test-storage.ps1 python -m playwright install chromium
.\scripts\with-test-storage.ps1 npm --prefix UI ci
.\scripts\with-test-storage.ps1 python -m pytest -q
```

Use the same wrapper for browser tests that require the downloaded browser.
The wrapper does not change Windows-wide settings or move shared user caches.

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
