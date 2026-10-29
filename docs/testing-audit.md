# Test And Evaluation Audit

Scope: Promethea in the current checkout. AUV is a separate workspace and is not
modified or assessed here. This audit is about fault detection, not test counts.

## Before Changes

The initial AST inventory found 196 Python test-named files and 1,133 test
definitions. Definitions are not collected cases: parametrization expands them,
non-Test classes with constructors are not collected, and duplicate definitions
can shadow one another. The previous complete suite collected 1,237 cases.
`scripts/audit_test_assets.py` reproduces the inventory without importing Runtime.
Its mock and assertion counts are review hints, not quality scores or deletion
criteria. Baseline execution artifacts live under `.tmp/evaluations/before/`.
Static discovery covered all test assets; manual review concentrated on risk
owners, suspicious duplicates, whole-service mocks, execution scripts and new
acceptance paths. This is not a claim that every assertion was manually proved.

Confirmed findings before implementation:

| Asset | Finding | Decision And Risk Preservation |
| --- | --- | --- |
| `test_api_compatibility.py`, `test_gateway_basic.py`, `test_agent_integration.py`, `test_memory_system.py` | Four standalone scripts masquerade as pytest files; their classes are not collected. Boolean returns are not pytest assertions. WebSocket reads have no deadline, no authenticated user, and the memory script can mutate a live deployment. | Replace with collected, explicitly opt-in, read-only authenticated deployment checks. Preserve local memory mutation/isolation coverage in existing governed memory tests; do not run decay/cleanup on personal data. |
| `test_conversation_core_metrics.py` | Exact repeated function definition shadows the first copy. | Remove one identical definition. The surviving parametrized cases preserve collection and terminal-fact assertions. |
| `test_business_journeys.py` and `business_plus/test_business_plus_flows.py` | Approval roundtrip repeats the same fake whole-service success path. MessageManager and ConversationService are replaced; no report is written. | Keep one Gateway mapping contract, remove the repeated roundtrip and duplicate fake setup; retain the two distinct Workflow/batch journeys. Add a real-service artifact/approval/history path with only the model boundary scripted. |
| `run_general_benchmark.py`, `general_capability_tasks.json` | A handcrafted catalog and ToolStrategyEngine keyword recommendation score are called general Agent capability; 75% aggregate permits individual failures. CLI smoke writes under checkout by default. | Label as legacy recommendation diagnostics, report each case, separate from Agent quality. Run artifact smoke in disposable storage; non-passing individual cases must be visible, not averaged away. Keep independent ToolStrategy unit risks. |
| `tests/run_all_tests.py`, audit/preflight scripts | Overlapping named profiles repeat suites; no wall-clock/repeat report, no behavior evaluation baseline. `--live` does not collect the standalone scripts. | Keep one runner, add explicit layer selection, budgets, repetitions, JUnit-based reporting, and opt-in boundaries. |
| Browser tests | Real React is exercised, but most APIs are fulfilled by fixtures. Valuable UI tests, not proof of full deployment integration. | Retain their distinct UI race/disclosure/isolation checks and label their limits. Add a real HTTP Runtime integration surface, do not call a fixture browser test a live-model success. |
| CI | SDK tests run, but React `npm test` is omitted; browser acceptance is opt-in and absent from CI. | Run existing UI tests; add bounded isolated system checks and publish test artifacts. No paid providers in CI. |
| Model evaluation | No versioned independent behavior corpus, Judge calibration gate, repeated comparison, or measured quality baseline. | Add evaluation-only corpora, production-owned prompt adapters, hard evidence checks, independent Judge protocol and explicit budgets. Unreviewed calibration labels cannot qualify a Judge. |

## Coverage Matrix

Coverage means named evidence, not a claim of exhaustive correctness. Existing
checks at different boundaries are retained even when they concern the same risk.

| Capability / Authority | Deterministic And Module Evidence Retained | Behavior Evaluation Focus | Remaining Live Boundary |
| --- | --- | --- | --- |
| ActionService / ConversationService | action service/recovery/steering, runtime completion, tool execution, conversation staging | direct answer vs capability request, failure recovery, truthful unsupported outcomes, guidance | real model choices, provider streaming latency |
| CapabilityService / ToolRegistry | capability projection, confirmation, discovery/reload, policy/spec tests | unavailable vs available tools, full schema discoverability, no invented capabilities | external MCP availability |
| TaskService / TaskRuntime | task service, background agents, delegation, agent messages, goal gaps | continuity, goal completion evidence vs assertions | process termination and uncertain remote side effects |
| Persistence / Recovery | runtime event log, action checkpoints, sessions, workspace archive, identity store | continued facts after restart, no repeated side effects | Windows intermittent replace/rename errors remain visible |
| MemoryService | memory Gate, semantic recall, backend import/lineage, forgetting, Hippocampus | durable vs hypothetical facts, query relevance, conflicting updates, missing facts | Neo4j native index and real embedding quality |
| SelfModel / Environmental State | environment observations/collaboration, cognitive continuity, semantic UI | current/stale view, observation vs inferred intent, untrusted source text | real generated custom UI fidelity |
| Ambient | ambient service, temporal runtime, environment collaboration | useful intervention vs silence, disabled state, sensitive-action boundaries | longitudinal usefulness and interruption rate |
| Frontend / SDK | steering/runtime/workspace browser checks, SDK transport/contract tests | state consistency through real API flows | production-shell + real Gateway + configured provider together |
| Workflow / Moirai / Self Evolve | workflow lifecycle, learning, sandbox, Canvas validation, append-only boundaries | evidence-bound reuse and inability acknowledgement | generated application quality and host-dependent tools |

## Interpretation

Passing scripted-model tests proves Runtime behavior under those model outputs,
not that a real model will choose them. Judge scores never override deterministic
permission, ownership, artifact or persistence failures. Missing provider usage
or pricing is unknown, not zero. New baseline summaries must identify corpus,
rubric, code, model, repetitions and budget; no improvement claim is made from a
single run or from a changed dataset. The owner reviewed three calibration
labels; the configured Judge has not yet been calibrated or scored live cases.

## Disposition And Verification Record

[The versioned offline baseline](../tests/evaluation/baselines/offline-v1.json)
lists every retained, added and removed Python test asset, the UI/SDK assets,
and per-module before/after outcomes. Unless listed as changed in the table
above, existing risks are retained: no safe deletion was demonstrated.

The assertion scan's remaining three candidates in `test_computer.py` were
reviewed and retained: constructor smoke intentionally asserts non-throwing
construction, while optional browser/screen initialization checks explicitly
skip without operator opt-in. They are not desktop-task quality tests.
`test_utils.py` contains shared support, not collected cases; no deletion follows
from its zero test-definition count. Two Workflow/batch journeys were moved,
not dropped. Existing Gateway fake-service tests remain narrow mapping tests,
not substitutes for the new real-service acceptance paths.

| Evidence | Before | After |
| --- | --- | --- |
| Python collected cases | 1,237 | 1,275 |
| Passed / optional skipped / known xfailed | 1,178 / 59 / 0 | 1,211 / 62 / 2 |
| Production lines covered / statements | 27,335 / 38,160 | 27,404 / 38,160 |
| Line coverage | 71.63% | 71.81% |
| Complete pytest wall time, Windows/Python 3.12.4 | 103.32 s | 119.69 s |
| Repeated critical risk suite | No versioned repetition record | 181/181 in each of 3 trials |
| Independent model-quality score | Not measured | Not measured; 22 runnable versioned cases |
| Human-reviewed Judge seed | None | 3 labels; actual provider calibration pending |

The denominator stayed identical. Added system tests deliberately add execution
time; this is stronger fault detection, not a performance optimization claim.
Three additional optional skips are the explicit live-deployment probes. The
two strict xfails expose pre-existing diagnostic failures previously hidden by
the aggregate 75% threshold; neither is a new production regression.

Additional actual verification: 58 browser cases passed; React 24 and SDK 35
tests passed; UI lint/build, SDK generation check/build/typecheck passed. The
build reported stale Browserslist metadata, not a build failure. CI workflow
syntax and local commands were checked; remote three-OS CI was not run here.

The no-op writer injection proves a successful tool response and assistant
wording cannot pass artifact acceptance when the output file is absent. The
TCP system journey restarts an actual subprocess and checks the old token,
identical history and persisted file. It uses a test-owned composition root,
not the production launcher. Provider behavior remains scripted. An isolated
SQLite recall pilot passed all 4 cases across 3 repetitions with zero metered
model calls. Generic pytest provider calls are not instrumented and are marked
unknown rather than assigned a fabricated zero.

## Remaining Evidence Gaps

Judge v2 follow-up (2026-10-29): separate task completion from behavior and
require Runtime evidence for known blockers. The original three seeds were
translated without discarding the evidence-insufficient case; one synthetic
Runtime-unavailable fixture implements the newly approved policy and is marked
as policy-derived rather than individually reviewed. The offline-v1 baseline
above remains historical; its rubric hash must not be compared as though v2
were the same scoring protocol. No live Judge score has been obtained.

- Real-model decisions, long-horizon memory evolution and useful Ambient
  intervention still require repeated business trials. No quality gain is
  inferred from scripted output or from the small SQLite pilot.
- Neo4j native indexes, local embedding downloads/inference, external MCP and
  hosted-model latency/cost are not exercised by this offline baseline.
- Browser fixtures and TCP Runtime acceptance are separate. A browser against
  the production launcher with a real provider remains operator acceptance.
- Three calibration labels are only a seed. Expand reviewed ambiguity and
  adversarial examples before using Judge scores as a release gate.
- Earlier Windows Self Evolve replace/rename failures did not recur in either
  audited full run; their absence here does not establish a root-cause fix.

No Python Core, transport API, MCP or React behavior was changed for this test
restructure. Existing uncommitted feature work was preserved. AUV was untouched.
