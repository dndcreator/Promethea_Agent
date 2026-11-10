# Test And Evaluation Audit

Scope: Promethea in the current checkout. AUV is a separate workspace and is not
modified or assessed here. This audit is about fault detection, not test counts.

## Standalone Todo Business Trial (November 6-8, 2026, Asia/Shanghai)

Run the user's unchanged todo goal through the production HTTP/SSE entry, with
ten action steps and a fresh $0.10 ceiling. The driver chooses no business tools,
writes no app code and grants no approval. Twenty-four local evaluator/proxy
checks pass before the live run. Promethea writes a 12,397-byte `index.html`.
The original artifact is retained with its SHA-256; no source is changed during
acceptance. On November 8, independent Edge testing passes all six preregistered
checks using direct `file://` navigation and newly chosen task labels. Both
completion and deletion persist after refresh and reopening the browser. No
page errors or 390px horizontal overflow occur; screenshots are retained.

The real Agent gets `TOOL_NOT_FOUND` for a misbound `capability_inspect` tool
name and subsequently uses the declared capability operation. This is live
evidence of recoverable feedback without phantom approval. Its browser then
rejects the local file scheme before it can exercise the page. A later upstream
HTTP error yields no usage, closing admission without a normal Agent final
answer. The proxy retained only the exception class, not upstream HTTP status
or body; the specific provider cause is unknown. Artifact functionality passes;
autonomous verification and final delivery do not. A workspace-scoped preview
would address the local verification gap without globally enabling file URLs.

Nine requests settle with $0.0429594 conservative configured-price accounting;
one unresolved request reserves $0.0328992. Total reserved exposure is $0.0758586
within $0.10, not a billing claim. No further paid calls occur after unknown
usage. Original receipts, Runtime/SSE records, separate verification JSON and
desktop/mobile captures remain under ignored `.tmp/todo-agent-live-20261106-2258/`.
All test processes and listeners are closed.

### November 8 Follow-up: Preview and Delivery Recovery

Real Edge exercises the original, unchanged artifact through the new workspace
preview: open, add, complete, reload with state intact, and delete followed by
reload. A separate test exercises the registered browser tool and confirms the
preview cannot use the ordinary tab or its browser state. Simulated 503 and
admission-closed responses after a committed write cover both streaming and
non-streaming paths. The transient case reaches model-authored completion; the
closed-gate case records a separate Runtime status, does not replay the write
or send an extra request, and retains unknown usage as unknown. This is not a
rerun of the live autonomous trial. Full offline report:
`.tmp/evaluations/preview-delivery-full-20261108/summary.json`.

## Tool Admission Repair And Retest (2026-11-06 21:54, Asia/Shanghai)

Remove lookup-created tool placeholders. Unknown tools now produce a typed
`TOOL_NOT_FOUND` without mutating the Registry; registered tools with undeclared
risk remain privileged. Approval preflight and dispatch share the same
registration, enabled/config/dependency, ownership and policy checks. Validate
every batch member before waiting for the first approval, including already
approved IDs after restart. Keep the actual failing call's error distinct from
adjacent `BATCH_NOT_EXECUTED` receipts. Do not alias a mistaken protocol name.

Thirteen dedicated admission tests cover unknown names, inspection purity,
owner/config/dependency/disabled/policy rejection, batch ordering and removed
or disabled tools after approval. Update old tests that confused declared risk
with authenticated readiness, preserving all independent risk and execution
assertions. The first full report retains five obsolete assertions as failures;
final full suite: 1,506 passed / 96 optional skipped / two known xfailed. SDK
39 tests/build/typecheck/generated freshness and UI 31 tests pass. The original
unbounded cancellation-fixture wait is now bounded and verifies revalidation.

The separately authorized $0.10 live cohort retests only current production
source, not a new paired experiment. Same calculator/GitHub goals and five-step
Native allowance, no business scripting or automatic approvals; memory is
disabled with an explicit isolated SQLite backend. Preregister calculator
verification as actual browser clicks accepting either numeric output or an
explicit addition equation with matching input operands/result. Bounded AST/
Decimal checks reject wrong sums/operands and never execute display text; prior
trial reports are unchanged.

| Goal | Actual result | Calls | Input / output tokens |
| --- | --- | ---: | ---: |
| Calculator | Real standalone file; both browser arithmetic cases pass; additional code validation waits for approval | 3 | 20,965 / 2,938 |
| GitHub | First-step inspection + resolution accepted; four browser operations; DataDome frame and durable human-input wait; no account/repository | 6 | 73,340 / 5,900 |

No phantom approval or protocol error occurs. The live model uses the correct
operation types, so do not claim live correction of a malformed proposal; that
path has fixed offline regressions. The two-query Native batch does exercise
the formerly rejected heterogeneous-query path, but not query + ordinary-tool
mixing in this trace. GitHub cumulative cache hit is 77.49%; final-response hit
is 89.65%, with identical function definitions and no rewrites of prior visible
Observation facts. This is observed behavior, not a causal saving against the
earlier shorter, blocked runs.

All nine requests settle with known usage. Conservative spending: $0.0388971
of $0.10; published off-peak/cache-aware estimate: $0.009212646, not an invoice.
Price source: <https://api-docs.deepseek.com/quick_start/pricing/>, checked
November 6 (hit/miss/output $0.003/$0.15/$0.60 per million). Preserve receipts,
original results, source hashes, actual calculator and separate analysis under
ignored `.tmp/tool-admission-live-20261106-2149/`; full regression reports are
under `.tmp/evaluations/tool-admission-20261106*`. All scoped service ports and
browser processes are closed; no extra paid retry follows the human boundary.

## Request-Stability Live Retest (2026-11-06 21:26, Asia/Shanghai)

Fresh authorization: $0.10, shared across four goal-only production HTTP/SSE
attempts. Restore the retained on-demand pre-repair source in five documented
modules; all other source and the CapabilityService authorization functions
match. Do not compare with the earlier eager-directory baseline or reuse its
remaining budget. Eleven evaluator/proxy checks and source-parity preflight
pass before any paid admission.

| Attempt | Pre-repair calls / cache hit | Repaired calls / cache hit |
| --- | ---: | ---: |
| Calculator | 5 / 71.50% | 4 / 65.41% |
| GitHub | 2 / 45.17% | 2 / 46.45% |

Both calculator files exist, and independent Edge clicks produce the expected
5 and -1.5. The original numeric-only verifier rejects the candidate's visible
equation `2 + 3 = 5`; a separate post-hoc review retains actual DOM values for
both arms without modifying the primary report. The task did not require
numeric-only display. Both product runs nevertheless pause before executing
`code.run_python` validation; independent artifact correctness is not full
autonomous product completion. Estimated cache-aware attempt costs are
$0.00363339 baseline and $0.002892234 candidate (20.40% lower in this sample),
not statistically established completed-task costs.

Both GitHub attempts stop before browser dispatch. The model inserts the
protocol operation `capability_inspect` as an ordinary tool name in the
`tool_calls` wrapper. It is absent from both initial 148-tool registries, but
the Registry's inferred privileged fallback sends the name into confirmation
instead of returning a recoverable unknown-tool observation. This is a common
pre-existing validation/approval-order boundary issue, not a genuine typed
mixed Native batch or an authorization bypass. No account or repository exists.
Retain it as the next blocking defect; do not auto-alias protocol names or
approve the nonexistent tool to continue the test.

Neither arm reaches final-response phase or emits a real mixed query/tool
function batch. Both record zero function-definition changes, zero rewrites
of prior visible Observation facts and zero protocol errors on these traces.
The intended repaired branches therefore remain covered offline, not proven by
this small live sample. Cache hit improvement is not established either.

Thirteen requests settle with known usage; conservative spending is $0.0402807
of $0.10, with no admission denial or unapproved sensitive execution. Using
the published off-peak rates at the request time (hit/miss/output:
$0.003/$0.15/$0.60 per million), the total estimate is $0.011466174, not an
invoice. Source: <https://api-docs.deepseek.com/quick_start/pricing/>, checked
November 6. No additional paid rerun or production fix follows these results.
Keep plans, source hashes, original results/receipts, artifacts, display review
and separate analysis under ignored `.tmp/request-stability-live-20261106-2118/`.

## Mixed Actions And Request Stability (2026-11-06)

The pilot exposed a codec restriction, not missing provider support: an
independent capability inspection and session read were rejected as a mixed
Native batch. The same retained provider response now decodes offline into two
typed operations with distinct original call bindings; no business action is
replayed. Standalone queries and mixed execution share the existing ActionService
batch path. Typed query dispatch cannot be selected by spoofing a tool name.
Answer/wait cannot mix with execution, and inspection does not exempt adjacent
tools from authorization or Goal Gap recovery requirements.

New deterministic cases check successful mixed query/resolution/read receipts,
whole-batch approval/rejection after restart, interrupted side effects without
replay, invalid mixed batches, diagnostic-exemption prevention and final-phase
execution rejection despite identical Native function definitions. Existing
tool concurrency and cancellation tests remain in the full suite.

The request-stability change retains accepted bounded views in the action
history/checkpoint. Repeated views are byte-stable while their actual projected
sizes fit; pressure triggers re-projection from the retained original evidence,
not a preview of a preview. Tests check original result/hash preservation,
bounded serialized previews, unchanged older receipts after a small new result,
and checkpoint retention. Current environment and goal data remain fresh. The
function list no longer changes just because the Runtime entered final response;
decoding/dispatch still prohibit execution in that phase. This is a structural
cache opportunity, not measured cache performance or an invoiced saving.

Both initial and final full offline reports: 1,481 passed / 96 optional skipped /
two known xfailed. Final frozen-source rerun is retained separately under
`.tmp/evaluations/mixed-actions-cache-20261106-verified/`. SDK 39 tests and
build/typecheck/generated freshness, plus UI 31 tests, pass. No new paid model
call, external signup, approval bypass, UI change or public protocol regeneration
is part of this repair.

## Live Tool-Context Pilot (2026-11-06 19:25, Asia/Shanghai)

The separately authorized $0.10 trial used the real production HTTP/SSE path,
Native protocol, fixed 8,192 output allowance and five Action steps. Only the
six documented context/projection modules differed from the frozen baseline;
execution/approval function ASTs matched. Fresh deployments had no personal
memory. The driver supplied goals, not business tool actions or approvals.
All 17 upstream requests have known usage and settled journal entries.

| GitHub attempt | Eager baseline | On-demand candidate |
| --- | ---: | ---: |
| Model calls | 5 | 6 |
| Initial input tokens | 20,320 | 5,048 |
| Total input tokens | 111,919 | 48,488 |
| Cached input tokens | 87,680 | 29,824 |
| Output tokens (including reasoning) | 2,179 | 3,065 |
| Conservative configured-price USD | 0.0361905 | 0.0182244 |
| Cache-aware public-price estimate USD | 0.01041258 | 0.009456144 |

Inputs fell 56.68%, but the cached baseline was much cheaper than uncached
pricing suggests. Using DeepSeek's published peak rates at the request time
(hit/miss/output: $0.006/$0.30/$1.20 per million), estimated cost fell only
9.19%, not 49.64%. These are public-price estimates, not provider invoices.
Source: <https://api-docs.deepseek.com/quick_start/pricing/> (checked November 6).
One pair with unequal cache warmth establishes neither significance nor a
general production saving.

Both attempts reached the signup site's DataDome human-verification obstacle
and requested input; neither delivered an account or repository. The candidate
also proposed capability inspection and a tool call in one Native batch. The
existing codec rejected that combination before dispatch, wasting one model
call and some step allowance. Recovery worked, but this is an observed protocol
friction, not evidence of unchanged quality or a reason to bypass validation.

The candidate calculator produced a real standalone file. Independent Edge
interaction passed both 2 + 3 and -2.5 + 1 with network blocked. The Agent itself
performed file/readback checks but did not browser-test its artifact. Its six
calls cost $0.0211782 conservatively ($0.01214652 cache-aware estimate).
The baseline calculator's first $0.0375708 reservation exceeded the remaining
shared conservative allowance and was never sent. Mark that pair censored;
do not score the zero-call baseline as a cheap failure or claim non-degradation.

Total conservative spending: $0.0755931 of $0.10; cache-aware public-price
estimate: $0.032015244. No unknown usage or unapproved sensitive execution was
recorded. Retain the immutable original report, source hashes, receipt journal,
artifact and separate offline analysis under ignored
`.tmp/context-ab-20261106-1128/`. This turn changes evaluation/reporting only;
no paid rerun or production repair is folded into the comparison.

## Demand-Loaded Capabilities (2026-11-06 11:06, Asia/Shanghai)

Keep the complete Runtime catalog and Registry unchanged as the authority.
The default model view now contains bounded namespace/tool identifiers,
availability and offered capabilities; full descriptions, schemas, readiness
and policy detail are obtained via existing resolution/inspection. Preloading
requires explicit preference and current callability. Wildcard resolution
returns complete owner-filtered directory data, with existing Observation
paging when large. No new planner, model router, tool protocol or service exists.

`action.capability_context_chars` applies both at initial assembly and after
refresh, including the snapshot reference. A tighter explicit RunContext budget
reduces only that projection, using the existing character estimate. Goal data
is projected before the Conversation callback, and original user messages and
identity remain intact. This does not implement an exact provider-token hard
cap or a new history-summarization algorithm.

Replay the same retained pilot through its frozen renderer and verify the
original Native wire hash before changing the model projection. Evidence is
`.tmp/evaluations/on-demand-capabilities-20261106/input-comparison.json`:

| Measure | Frozen baseline | On-demand candidate |
| --- | ---: | ---: |
| Tool-context characters | 69,800 | 5,750 |
| Discoverable tool identifiers | 148 | 148 |
| Namespaces | 30 | 30 |
| Implicit schemas | 17 | 0 |
| Native action function definitions | 6 | 6 |
| Serialized Native wire bytes | 92,510 | 22,311 |

The byte reduction is 75.88%, not a measured token/cost reduction. Only the old
20,324-token provider receipt exists. No new paid model call is made, and extra
on-demand decisions can affect step count, cost and completion quality.

Add deterministic coverage for bounded/overflow directories, explicit schema
selection, exact effect/confirmation inspection, wildcard ownership and effect
scope, refresh after compaction and a same-loop inspect/invoke journey. Change
the real artifact integration journey to inspect its schema before writing;
retain actual file/readback/history/restart/cross-user assertions. The first full
report preserves its obsolete eager-schema assertion failure. Verified full
regression: 1,462 passed / 96 optional skipped / two known xfailed. A final
46-case focused run additionally includes the subsequently added wildcard
owner-isolation assertion and real Windows author/validate/publish/invoke test.
Model decisions remain scripted, not a live autonomy score. SDK 39 tests,
build/typecheck/generated freshness, UI 31 tests and whitespace checks pass.
No UI code or provider wire protocol is changed in this batch.

## First-Request Input Attribution (2026-11-06 10:26, Asia/Shanghai)

Analyze the retained low-ceiling pilot without sending another model request.
The complete catalog prompt is reconstructed using its frozen renderer and
capability snapshot; its content hash and the reconstructed Native wire hash
both match their saved manifests. See ignored
`.tmp/reg-live-20261106-1006/audit_input.py` and `input-audit.json`.

| Actual Native input component | Content characters |
| --- | ---: |
| Runtime tool catalog | 69,800 |
| System identity/protocol/runtime/Self Model context | 10,870 |
| User objective | 409 |
| Environment observations | 285 |
| Snapshot reference | 225 |

Six generic Native function schemas add 2,680 compact JSON characters separately.
The earlier pre-codec system message has 11,155 characters; Native conversion
reduces it to 10,870. Provider usage remains 20,324 input tokens, of which 896 are
reported cache hits; do not equate per-component character shares with token
shares or diagnose persistent cache failure from this single sample. The 990
reported reasoning tokens belong to output, not the 20,324 input tokens.

The all-tools index is not actually small: 148 entries (131 callable), of which
17 receive selected schemas and seven selected entries are unavailable. The
selection algorithm prefers explicit tools, then name order, without filtering
unavailable tools for schema selection. Description-field removal saves 16,483
catalog characters; removing all input schemas saves only 5,700, leaving 63,400.
Other field-removal measurements are in the JSON report. There are 137 empty
effect selectors, 143 empty capability-detail objects, 137 null prerequisites,
127 empty offered-capability arrays and 131 redundant `callable` reason strings.
The schema selection budget does not bound the complete model-facing index.

The system message also includes both a 2,601-character core identity and a
1,087-character additional default prompt repeating identity/operating policy.
Its Native action protocol is 4,675 characters. Skill listing and passive
personal-space continuity are small (410 and 591 characters); long-term memory
recall was disabled in the pilot. These are secondary to the tool projection.

There is also an input-budget ownership gap. The normal RunContext builder
leaves `token_budget=None`, so optional PromptAssembler compaction is not a
normal final guard. Even explicitly setting a fixture budget is insufficient:
the actual `compact_blocks` removes tools, then `refresh_tool_message` adds the
69,800-character block back before a model call without another budget pass.
The zero-provider-call probe produces eight content characters before refresh
and 70,033 afterward, including the fresh snapshot reference. The probe uses
the exact same PromptAssembler source as the retained deployment.

Priority for a later repair is the existing model-visible projection and final
refresh/budget boundary, retaining Runtime's complete registry, capability
discovery, inspection and policy authority. Do not remove tools, introduce a
semantic keyword router, truncate schema arbitrarily or tune output limits as
a substitute. No production code is changed in this diagnostic audit.

## Low-Ceiling Goal-Only Pilot (2026-11-06)

Authorize a new $0.05 cohort with the same account/demo objective, a new isolated
production deployment and the existing evaluation-only DeepSeek Native endpoint.
Do not script a business route, browser actions or approvals. Configured price
ceilings are $0.30/$1.20 per million input/output tokens, not a current vendor
pricing claim; cached input is conservatively charged at the input ceiling.

One settled request reports 20,324 input and 1,215 output tokens (990 reasoning),
costing $0.0075552 at those ceilings, with zero unresolved usage. Promethea chooses
browser navigation to the signup page; the real Observation reports
`net::ERR_CONNECTION_CLOSED`. That does not establish CAPTCHA, an automation ban
or an unavailable alternative path. No human verification or approval is reached.

The second request is rejected before transport: $0.0426786 reserved plus
$0.0075552 already spent is $0.0502338. The driver correctly fails its completed-
transport assertion. Account/repository/code delivery and the model's post-error
recovery behavior remain unverified. Retain the original source snapshot, ledger
and failed result in `.tmp/reg-live-20261106-1006`, rather than rescoring success.
Both isolated listeners are closed and no cohort-scoped browser/server remains.

Audit the evaluator separately: total-token reservation includes output tokens,
but the currency formula incorrectly also prices those tokens as input. Separate
input and output pricing, retaining the existing byte-based input upper reserve
and 512-token padding. The old total-token check, deadline, unknown-usage stop and
hard money ceiling remain. Corrected reserve for that denied request would be
$0.040221 ($0.0477762 including settled spending); this is an offline calculation,
not a newly sent request, refund or revised historical bill. Historical usage
and price assumptions remain unchanged.

Offline verification: 81 passed / four opt-in live cases skipped, covering exact
pricing, real local proxy sends/rejections, unknown billing, journal persistence,
carried spending and Native protocol support. No paid rerun, product budget
change, Agent strategy change or full-suite rerun follows this test-only fix.

## Capability Acquisition Audit (2026-11-06)

Reconstruct the capability message from the retained registration snapshot and
the original renderer before diagnosing tool visibility. The reconstructed
67,381-character message matches the original model-call manifest hash and
includes Self Evolve and code execution. The saved audit preview ends at 12,000
characters; absence from that preview is not absence from the actual request.
New request previews explicitly report original length and truncation. This
case-specific reconstruction does not establish general full-prompt retention.

The actual discovery defect is semantic: resolution used a required Runtime
dependency as an offered operation. Tools without such a prerequisite could
not match an intent, even when callable. Add validated optional `provides`
metadata to the existing ToolSpec/Registry path, keep dependency readiness
separate and preserve discovery by canonical ID. Also pass the trusted current
configuration into `runtime.list_tools`; tool arguments cannot spoof it. Keep
generated command schemas and offered capabilities through Self Evolve
normalization/publication. Large schemas use existing inspection rather than
duplicating every definition in the resolver result.

Local dispatch in CapabilityService creates a fresh invocation context with the
same explicit RunContext/configuration used for authorization. It overrides
stale or absent caller metadata without mutating that caller's context. Thus
workflow/reasoning and chat share truthful list projections; neither tool
arguments nor stale metadata can substitute a different configuration. These
internal references are not added to the external MCP wire protocol.

`tests/system/test_capability_acquisition.py` exercises the real Conversation,
Action, Capability, Registry and native Windows process runner in a temporary
project: missing provider, authoring discovery, actual source write, sandboxed
validation, publication, same-loop context refresh, resolution, invocation and
independent file readback. It also checks owner isolation and disabled authoring.
Three exact approvals and all model decisions are scripted. The test verifies
execution plumbing, not live model invention, autonomous path selection, strong
Windows read/network isolation or GitHub delivery. Existing policy is unchanged.
No paid provider request or external signup is repeated in this audit.

The focused suite initially exposed a resolver local-variable collision that
mutated the catalog's side-effect selector; a pure-projection regression now
guards it. An initial scripted journey incorrectly treated a paged broad
resolution response as a complete candidate list; the fixture now requests the
specific declared authoring capability. These failures are not successful task
scores. Full-run evidence is retained separately under ignored
`.tmp/evaluations/capability-acquisition-20261106`.

The next full run and a single-file runner reproduction expose a real native
Windows deep-path failure, not a random suite-order effect. Validation times out
before generated Python starts; its empty TimeoutError was then reduced to a
generic failed-tool message. Identical isolated probes succeed with a 201-character
working path and time out at 209/221 with the old nested TEMP layout. They succeed
at both depths after shortening only the owned per-process temporary directory.
The precise interpreter-internal Win32 call is not established by this probe.

The Windows helper now creates a short unique TEMP inside the same workspace,
checks the [Win32 temporary-path limit](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-gettempfilename),
accepts an equivalent short-path representation where available, and fails
explicitly if no valid confined path exists. It never falls back to host TEMP.
Token, ACL, job cleanup and approval policy remain unchanged. A real deep-path
Python/temp-file regression and a fail-closed cleanup test protect this boundary.
Self Evolve preserves typed smoke-test errors and exposes validation diagnostics
through the existing error envelope, including Canvas validation. Failure still
blocks publication; no automatic retry or additional model is introduced.

Both runs in `.tmp/evaluations/acquire-path-fixed` pass the same full acquisition
journey under the evaluation layout. The targeted sandbox/validation/audit suite
passes 34 checks. Initial full reports and the failed runner probe are retained;
the first draft of the new deep-path test also used an invalid allowlist name,
corrected to the existing suffix-free `python` identifier without changing policy.
The subsequent longer-named full report passes validation/publication but hits
the explicit path guard during generated-tool invocation. Remove the redundant
package-name segment from transient execution storage and use that same call
pool for validation: each call already owns a unique directory and is cleaned
independently. A deliberately deeper probe also confirms validation's previous
task-name nesting was unnecessary. Immutable package paths, owner
checks and per-call sandbox roots remain unchanged. Do not shorten the evaluation
root or loosen the path guard to conceal the failure.

Final verification (2026-11-06 01:28, Asia/Shanghai): 1,455 passed / 96 optional
skipped / two known xfailed. The earlier 1,451-pass full report precedes the
cross-entry context regression expansion; final evidence is
`.tmp/evaluations/capability-acquisition-20261106-context-verified`. SDK 39 and UI
31 tests, SDK build/typecheck/generated freshness, UI lint/build and whitespace
checks pass. Existing browser-data-age and bundle-size warnings remain. Both
deep-layout acquisition repeats in `capability-acquisition-deep-path-20261106-fixed`
pass. These are offline engineering results, not a new paid business cohort or
proof that a live model proactively creates a useful missing capability.

## Goal-Progress Control Audit (2026-11-05)

The retained registration deployment has `action.gaps.enabled=true`; three gaps
are created open and observation monitoring advances their revision. Saved model
request manifests contain the current goal projection and obstacles, but none
contains the old recovery instruction. This is a detection failure, not evidence
that the model ignored an injected recovery command. Full call/result fingerprints
vary with tab arguments and error content, while the old dispatch path contains
no progress gate. The earlier live cohort is not rerun or re-scored here.

The repair adds structured-error-family monitoring and a Runtime reassessing
phase to existing Goal Gaps/ActionService. A compact recovery decision uses the
existing optional `gap_update`; no new action kind, reviewer model or service is
introduced. Deterministic tests verify refusal before batch dispatch/approval,
actual executor counts, matching Native tool receipts, bounded failed trials,
ordinary transient retry, verified-new-evidence requirements, durable input and
approval restarts, absence/blocked goals, and capability-inspection loops.

Independent Task runs keep goal requirements, but old loop-local recovery
references cannot deadlock a fresh run. Same-run checkpoints retain both guards
and their receipts. Monitoring revisions are visible even before a semantic gap
is declared; otherwise valid later declarations become stale. Existing actual
code-maintenance acceptance still edits files, explicitly approves a real native
Windows test process after restart, checks its output and records one procedural
episode. Its scripted actor now reads current revisions, not a hardcoded zero.

These are execution-control regressions, not proof that the model selects good
alternative strategies. Runtime checks evidence identity, success and order;
repair relevance and novel-result usefulness remain semantic judgments. No new
paid model experiment or task-completion gain is claimed. The first full report
is retained under `.tmp/evaluations/goal-progress-control-20261105`, including its
stale-generated-artifact and scripted-revision failures; later results are kept
separately rather than replacing that report.

Final verification (22:11, Asia/Shanghai): 1,435 passed / 96 optional skipped /
two known xfailed on Windows, SDK 39 and UI 31 tests passed. SDK build/typecheck,
generated freshness, UI lint/build and whitespace checks passed. The verified
report is `.tmp/evaluations/goal-progress-control-20261105-verified`. The intermediate
`-final` report retains an over-specific steering-position assertion failure:
the repaired assertion still requires the latest user instruction, the original
observation and fresh approval, while allowing named Runtime data afterward.
Existing browser-data-age and bundle-size warnings remain. No new paid-provider
trial or real autonomous-success score was obtained in this follow-up.

## Real Registration Pilot (2026-11-03)

### Goal-Only Business Journey (2026-11-05 20:30, Asia/Shanghai)

Under a new $0.30 total authorization, submit only a user goal: create a new
GitHub account, then develop and independently check a simple project owned by
that account. No route, external selectors, business code or automated approvals
are supplied. Available normal tools and append-only Self Evolve are enabled;
unrelated background cognition and optional long-term memory are disabled. The
ordinary Session/Action state remains durable. No existing identity, mailbox
access or repository is provided.

The initial 21 actual provider calls end in durable `needs_input`, not account
creation. The user confirms closing the restricted page and subsequently seeing
a login page. Browser observations expose a real stale-active-page defect: new
tabs exist, but reads target the closed prior page and tab enumeration can fail
on that closed entry. The model's blanket claims of no visible browser and no
remaining generic route are not established by these observations. Do not treat
its unsupported account-policy claims as independently verified evidence either.

Pause at the saved input checkpoint and repair the browser-owned lifecycle:
track context pages/popups, remove closed entries, retain a live active page,
avoid ID reuse and expose current browser state. Reads with no page do not reopen
a window or replay a side effect. Real Edge regression covers this exact
close/read/new-tab sequence. The user's own close-window report is then submitted
through public `reply_to_input` after restarting the same deployment; the test
supplies no repair plan or destination actions to the model. Retain old source
files and both source manifests to distinguish the engineering revision.

Five further provider calls show the model opening and explicitly switching to
the new tab, receiving headed/connected state, observing the same challenge and
generating an OS-protected credential reference. A generated reference is not
an account. The user confirms the page only reports access restriction, with no
verification entry; no challenge bypass is attempted. No signup/email submission,
account, demo repository or functional code delivery is verified.

All 26 unique admissions have settled usage: $0.2443203 at the configured
conservative rates, zero unknown exposure. The next $0.0633786 reservation would
exceed $0.30 and is rejected before send. The continuation contains a Runtime
error, and the live driver correctly fails its completed-transport assertion;
retain this failure rather than scoring a successful task. Change future proxy
admission failures to standard JSON error envelopes instead of HTTP-server HTML;
that does not retroactively repair the live stream. Both instances are stopped.
Evidence is ignored under `.tmp/registration-agent-live-20261105-2016`, including
the original report and `followup-1` ledger/source archive. Actual focused checks:
45 passed / one optional skipped with real Edge; five ledger checks passed.

The first full regression flags a real error-priority change: the new no-page
check masks an existing private-network policy rejection. Restore the security
check's priority, without changing its assertion or permitting the request.
Final focused verification: 43 passed / three conditional skips. Final full
offline regression: 1,416 passed / 96 optional skipped / two known xfailed;
retain `.tmp/evaluations/registration-lifecycle-20261105-2030` (failed) and
`registration-lifecycle-20261105-2034-final` (passed) separately. Whitespace checks
pass. This engineering result does not turn the incomplete business journey
into a completed account/development task.

### Follow-Up: Durable Input And Protected Credentials (2026-11-05)

Add a canonical `await_user` proposal to both Prompt JSON and Native adapters.
The existing Action state machine persists a nonterminal wait; Session owns
foreground checkpoints and existing Task drivers own background checkpoints.
The public API exposes only the bounded input question. Replies bind to the
current request ID and become unverified Runtime user-report Observations,
never tool authorization or proof of a completed website action. Offline HTTP,
Native and Task tests cover restart, no model polling, stale/cross-owner refusal
and a subsequent sensitive operation still awaiting approval. UI browser tests
cover restored state and typed reply serialization at desktop/mobile widths.
These use scripted model boundaries and are **not** real signup success cases.

Windows DPAPI regressions independently check generated credentials, ciphertext,
origin and owner refusal, tamper rejection and metadata-only references. A real
Edge fixture verifies protected filling, safe DOM reads and encrypted cookie
restoration; arbitrary JavaScript is unavailable in a credential profile.
Fixed DOM projection moves into the browser module instead of sending scripted
inspection through the general-purpose evaluation operation. Other OS backends
are not implemented: managed credentials fail closed there, ordinary browser
sessions remain usable but ephemeral. DPAPI does not isolate trusted/approved
host code or provide cross-machine secret portability.

Full regression also exposes a Windows cursor-file replacement failure. Add
unique fsynced cursor state files, bounded retries of only the idempotent rename
for Windows sharing/access errors, and rollback of in-memory cursors when a
save fails. Keep the original failed reports; no event/tool is retried by this
I/O recovery. Do not equate a later passing suite with proof of all-platform
storage reliability.

The user authorized a new $0.10 real-model cohort after offline checks. That
authorization does not renew the earlier pilot or permit replay of its budget.
The live driver uses only public account/chat/session APIs for setup and audit;
no registration selectors, answers, business code or external browser actions
are supplied by the tester.

This new cohort ends incomplete after the user observes an access-restricted
page and closes it. Eight requests have settled usage, with $0.0564168 at the
configured conservative prices, zero unresolved requests and one subsequent
request denied before send by the original $0.10 ceiling. No account, email
submission or credential creation is verified. The site restriction's exact
cause is unknown. Preserve the original receipts, source hashes and final
report in ignored `.tmp/registration-agent-live-20261105`; do not pool this
authorization with the November 3 cohort.

An important evaluation defect remains in that historical cohort: the goal
explicitly requested a browser-first route and the allowlist exposed only the
browser and Runtime inspection. It therefore cannot evaluate whether Promethea
independently discovers an API or a better available route. The future driver
now submits the goal without prescribing that route, restores ordinary available
tools under the same approval policy, accepts structured human-input waits and
does not require a browser call as a passing condition. This change has not been
rerun against a paid provider. A normal driver exit still does not verify account
creation; that requires independent destination-side evidence.

The actual initial turn stopped at its action-step limit with an honest model
report, but without a structured `await_user`. The retained deployment predates
the final-completion repair: both Native and Prompt JSON completion may now
return an answer or persist a human-input wait, never dispatch a tool at that
boundary. Offline tests cover this repair; this cohort does not certify its
live behavior. Internal Task resume cannot manufacture a human acknowledgement;
only an explicit authenticated user reply/resume can supply it.

Additional full runs exposed Windows access/sharing failures during Session
replacement and immutable Self Evolve publication. Share only a bounded local
rename helper with cursor/credential storage, preserving replace versus
non-replace semantics. It does not change permissions or replay the operation
that produced the data. The exact external locking cause is unconfirmed.

Final offline verification after these repairs: 1,413 passed / 95 optional
skipped / two known xfailed in 148.89 seconds; SDK 39 and UI 31 tests passed.
SDK generation freshness, build and typecheck, plus UI lint and production build
passed. Existing Browserslist-age and bundle-size warnings remain. The report is
retained under ignored `.tmp/evaluations/input-credentials-20261105-final-verified`.
These are engineering regression results, not autonomous route-selection or
successful external-registration evidence.

The following paragraphs retain the separate November 3 pilot's evidence and
historical limitations, rather than applying its results to the new code.

An isolated production launcher, HTTP/SSE chat, Native model calls and the
registered browser tool drove a real GitHub signup attempt. The driver only
provisioned the local test principal, submitted the goal and retained evidence;
it did not navigate or fill the external browser, inject answers or grant
external-write approvals. Seven requests have known usage, with conservative
configured-price cost of $0.0510033 against this pilot's $0.10 ceiling. This is
an estimate, not a provider invoice.

The registration task **did not succeed**. Runtime observations show a device
check iframe before any signup form. No email, permanent password or email code
was entered, no account was verified and no repository/PR was created. The exact
cause of the site challenge is unknown; the model's IP/environment speculation
is not verified evidence. The Action step budget ended the turn. A passing
driver test only confirms the test transport ran, not account creation, live
code maintenance or a resumable human-input workflow.

The attempt exposed missing iframe metadata and screenshot Base64 text in tool
observations. Fix the common browser adapter rather than adding signup selectors
or a GitHub-specific executor. Actual Edge regressions check frame-only pages,
secret-free form labels, protected-field refusal, ordinary-fill echo suppression
and valid workspace screenshot files without Base64 text. A protected credential
broker, durable interactive browser handoff and model-visible image delivery
remain separate uncompleted boundaries; no unattended signup success is claimed.

Retain the deployment, session, Runtime events, SSE and metered receipts under
ignored `.tmp/registration-agent-live-20261103`. Never reset that cohort or reuse
its original ceiling as new authorization. Manual email verification was chosen;
no mailbox credentials or mailbox access were supplied.

After explicit manual-handoff agreement, retain a second deployment with a
visible browser and the same carried ledger. One additional genuine Native
request caused Promethea to navigate to the signup page. Combined usage is known
for all eight requests, with $0.05766 conservative estimated cost. The next
request was not sent: its $0.0434274 conservative reservation plus settled cost
would exceed the original $0.10 ceiling. Thus the page opened but that turn's
final model reply was blocked by evaluation admission. Keep the terminal error,
not a successful handoff claim. The visible test deployment remains available
for manual site verification with no model polling; this is test infrastructure,
not an implemented durable product human-input lifecycle.

## Continuous Observation And Maintenance Slice (2026-11-03)

The implementation stays inside the existing temporal, event, cognition,
Task/Action and tool boundaries. No GitHub service, CI-specific decision loop or
new execution authorization path is introduced.

| Previously Missing Boundary | Implemented / Verified | Limit |
| --- | --- | --- |
| Scheduled reads become environmental facts | Explicit read-only observation-source declaration, model-visible Registry projection, existing scheduler cursor/version persistence and outbox, durable idempotent publication before delivery acknowledgement | Retained log keys and up to 4,096 object versions are bounded, not unlimited exactly-once execution |
| Several changes survive an activation | Ambient Task admissions retain bounded event-reference batches; SelfModel resolves owner-scoped facts independently of the rolling context; completion acknowledges the admitted cursor, not later arrivals | Waiting/paused activations retain the batch; log retention limits still apply |
| Agent can configure ongoing observation | Normal manifest tools expose existing scheduling and owner-scoped list/pause/resume/remove; full Runtime evidence can be paged by event ID | No automatic permission for arbitrary commands or external writes |
| Real external input reaches cognition | Anonymous GitHub read acceptance on `dndcreator/Promethea_Agent`/`develop` obtains five CI run observations and creates an Ambient Task admission with zero model calls | CI prioritization and repair decisions are not evaluated by this read-only test |
| Real code repair can continue after restart | Actual isolated Python file repair, pending approval, reconstructed Runtime, exact approval, native Windows subprocess checks and checked Goal Gap | Decisions are scripted; this is execution/recovery acceptance, not a live-model reasoning result |
| Background practice reaches procedural learning | Ambient records Runtime-backed Moirai episodes with Task/Run identity and a Task-owned objective; no fabricated user exchange, assistant reflection or automatic Memory fact | Goal verification remains unknown except explicit checked progress; no statistical learning advantage claimed |
| Feedback storage can fail safely | Failure pauses before consuming the event batch; resumption reuses the completed Action checkpoint, retries idempotent episode insertion and does not re-execute the tool | Autonomous model distillation remains the existing separately governed idle process |

The GitHub manifest provides only read-only source/evidence tools. Success,
recovery and new failures are facts, not instructions to create repair tasks.
Polling has explicit baseline/catch-up bounds documented in the tool catalog;
old completed reruns outside the retained window need backfill or future webhook
input. Repository/branch selection is configuration, not Core control flow.

The native Windows runner currently reports partial/write isolation, not read,
network or desktop isolation. Keep command approvals intact. A stronger unattended
execution policy requires an explicit technical decision and a verified stronger
boundary. No branch push, PR creation, live-model repair trial or new paid request
was performed in this slice.

## Runtime Continuity And Native UI Acceptance (2026-11-02)

Freeze output-budget selection research. Do not infer new product defaults from
the earlier pilots. Keep Native opt-in, Prompt JSON compatibility and existing
bounded recovery; this change does not introduce another Agent loop.

The full App/SDK/SSE/unmodified production launcher acceptance now includes an
isolated community tool with an inert external-write classification. Write an
actual file, stop at approval, restart the backend on the same port, reopen the
conversation, approve once, continue and restart again. Check disk contents,
exactly one fixture receipt and persisted history, not the Agent's completion
claim. The session detail now exposes only the existing public `ToolCall`
projection of the pending approval; provider wire, prompts and ownership tokens
remain private. Browser state is cleared when changing conversations.

The separately authorized **$0.10** live DeepSeek cohort exercises real provider
streaming and nonstream continuation. The first attempt sent only a greeting:
the test's conservative $0.03 per-request reserve blocked the full production
context before transport. Retain that attempt's known $0.0007971 and continue
under the same total authorization; do not reset the ledger. The second attempt
passes file/approval/history checks and two controlled restarts. Across attempts,
eight requests were admitted, seven have usage receipts, costing **$0.0286815**
at the configured conservative ceilings. A final background greeting was still
pending when the original proxy's daemon thread exited: retain **$0.0212478**
unknown exposure, for **$0.0499293** total conservative exposure. This is not an
exact invoice or a fully settled bill. Stop further live admissions.

Fix the test proxy to drain active provider calls and fsync usage receipts before
shutdown; add local HTTP disconnect/unknown-usage regressions and repeat the full
production browser journey offline. Strengthen future journeys to retain Runtime
Observations and require a successful read. The live cohort did not retain its
read Observation, so do not retroactively certify that particular check. Restart
coverage here means **while waiting for approval and after completion**, not
arbitrary interruption during an external side effect. Chat's consume-before-
resume crash interval still needs a durable continuation acceptance test.

### Autonomous Chain Audit

| Boundary | Current Evidence / Small Fix | Remaining Validation |
| --- | --- | --- |
| External change enters Runtime | Existing durable event log and Ambient subscription/replay are reused. | No built-in GitHub/CI change collector was found; a tool available for querying GitHub is not a background event feed. |
| Observation reaches cognition | Resolve the **admitted** trigger from RuntimeEventLog through SelfModel, separately from the last-24/last-four attention windows. Verify event ID, sequence and user; mark clipped excerpts. | Real CI payload quality, retention beyond log rotation and long-running situation relevance. |
| Long-term objective survives | Store Ambient direction in the existing Task objective; repair empty objectives only on idle legacy tasks. | Relevance/priority decisions still require real-model behavior evaluation. |
| Autonomous execution and progress | Reuse TaskRuntime/ActionService/CapabilityService; stop unconditionally disabling Goal Gaps in Ambient activation/confirmation. A checked subgoal does not complete a continuable root goal. | Native arbitrary-crash and cross-service unknown-effect recovery; no new execution system added. |
| Feedback influences future work | Runtime action evidence, task checkpoints and SelfModel working state persist. | Ambient participation is intentionally excluded from foreground Moirai episode recording; automatic governed transfer into reusable experience/long-term memory is not proven. Never fabricate a user interaction or store private model reflection as fact. |

Deterministic integration cases prove state/transport contracts, not that
SelfModel/Memory outperform a fixed workflow. The planned five-case autonomy
comparison (persistent failure, transient irrelevant failure, recurrence, failed
plan, silence) still needs an actual environment feed and independent results.
Keep this gap explicit rather than reporting a scripted CI demo as cognition.

## Per-Call Output Contract Pilot (2026-11-01)

Test the user's narrower hypothesis: allocate for the **current call's known
output constraints**, not overall task complexity. Keep ordinary/unknown
decisions at 8,192. Try 4,096 only for a Runtime-enforced <=1,024-character action
contract; final-answer-only does not imply short output. Scope contracts are an
evaluation fixture shared by all three arms, not a shipped ability to predict
the model's next action. No extra classification or provider Thinking switches.

Pre-register three new cases: finite file review, unrestricted invoice-page
generation, and a bounded requirements read followed by unrestricted page
generation. Keep the old structural predictor unchanged (2,048/4,096/2,048),
Prompt JSON, permissions, six-decision/one-final limits, recovery and acceptance
checks common. Two randomized repeats finish all 18 runs/six triplets. Exact
finite-answer Gold and real-browser behavior, not Agent self-report or code
length, determine delivery. Runtime scope changes use successful committed
reads; claiming to have read a file cannot widen the scope.

| Policy | Goals | Calls | Input | Output | Cache Hits | Truncations | Protocol Errors | Recovery Retries | Conservative USD | USD / Goal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fixed 8,192 | 6/6 | 25 | 104,082 | 29,554 | 67,200 | 0 | 7 | 7 | 0.0666894 | 0.0111149 |
| Legacy prediction + recovery | 5/6 | 29 | 126,592 | 25,229 | 88,576 | 2 | 9 | 10 | 0.0682524 | 0.0136505 |
| Input/output aware | 4/6 | 25 | 104,954 | 25,763 | 70,400 | 0 | 12 | 10 | 0.0624018 | 0.0156004 |

Category cells are goals / calls / conservative USD:

| Call Context | Fixed | Legacy | Input/Output Aware |
| --- | --- | --- | --- |
| Bounded review | 2/2 / 6 / 0.0067584 | 2/2 / 6 / 0.0067968 | 1/2 / 5 / 0.0056817 |
| Unknown code | 2/2 / 10 / 0.0386712 | 2/2 / 10 / 0.0299451 | 2/2 / 9 / 0.0320262 |
| Bounded read -> unknown code | 2/2 / 9 / 0.0212598 | 1/2 / 13 / 0.0315105 | 1/2 / 11 / 0.0246939 |

The candidate actually uses 4,096 during constrained reading, then 8,192 after a
committed read releases the constraint. Its three increases are **one ordinary
phase transition plus two final-report transitions**, not three successful
truncation recoveries. Candidate truncation recovery increases: zero; legacy:
two. No candidate call reaches its output ceiling.

Both candidate failures occur before any successful read: the model repeatedly
emits provider-private call markup instead of the agreed JSON action. One failed
review emits just 66 and 73 completion tokens before a truthful final report;
4,096 was not exhausted. The legacy failure combines truncation/format recovery
and the common step cap, retaining only a partial HTML head/style fragment.
Failures remain scored; do not remove them to make a policy look better. Their
direct causes do not establish that a smaller output ceiling caused the private
markup, or that the candidate is generally worse; two repeats cannot resolve
such causal effects. Plain final reporting is valid and is not itself counted
as a protocol error just because the diagnostic action parser cannot parse it.

The unknown-code candidate and fixed arm both use 8,192; their cost differences
are not evidence of a policy benefit. Across all tasks the candidate's lower
raw spend is not a win: it completes fewer goals and costs more per success.
**Do not promote the candidate to production.** The per-call principle remains
reasonable, but savings and reliability benefits are unproven. A stable native
protocol is a prerequisite for a less confounded future comparison, not an
excuse to silently change this frozen cohort or purchase more runs.

Total conservative estimate **$0.1973436**, below the separately authorized
$0.30: 79 unique known provider/local request IDs, zero unresolved exposure,
maximum request reserve $0.0218346 (cap $0.03). Audit all twelve code-artifact
hashes: ten functional pages, one partial page and one missing page. No policy
labels reach model requests; no Thinking flags are added. Preserve source,
corpus, request/decision logs and `evidence-audit.json` under ignored
`.tmp/evaluations/call-budget-20261101/`. Corpus hash
`aee751af205eb6a4cb40f13b3ac23e36dbb92c0f303453994bb60d28d6bc9744`;
source hash `d32415489a767a43e60972a2472a4d19b6f3cdf07a71ce0a1af306c21261f372`.
Source archive matches that fingerprint. Prices are configured conservative
estimates, not an invoice. Product budgets, Core, SDK and UI remain unchanged.

## Native Acceptance And Independent Budget Replication (2026-11-01)

Promote the shared canonical-action wire codec into production Chat Completions
I/O, with explicit env selection and unchanged JSON defaults. Native messages,
call IDs and protocol pins survive existing checkpoints and confirmation; no
second executor is introduced. Offline SDK-boundary tests cover streams,
batch/capability receipts, approval/denial, unknown-effect restart, compaction,
local preflight errors and preservation of user data. Real React/SDK/SSE/Gateway
tests at 1440/390 pixels verify file delivery and reloaded history with scripted
provider packets. This is not a live API+full-UI restart certification.

Under one newly authorized **$0.75** ledger, all three live Native smoke cases
pass (file write, capability inspection and approval wait): eight requests,
$0.0080361 conservative estimated cost, zero unauthorized fixture dispatches.
The live test uses the product codec and Action/Capability services through a
metered single-provider transport. Other Chat-compatible providers have offline
wire coverage/documented scope, not live certification; Anthropic/Gemini/Responses
are not silently treated as Chat Completions.

Freeze four new tasks before paid execution: BMI calculator, savings projection,
persistent contact book and JSON Merge Patch. The unchanged public structural
prior assigns 2,048/4,096/8,192/2,048; B/C share the exact same prediction.
All budget arms keep Prompt JSON, tools, recovery, eight-decision/one-final limits,
and independent browser checks fixed. Two interleaved repeats produce 24 complete
runs/eight comparable triplets, 121 requests and no quota/timeout/evaluator stop.

| Policy | Goals | Calls | Input | Output | Cache Hits | Truncations | Protocol Errors | Recovery Retries | Growths | Conservative USD | USD / Goal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fixed 8,192 | 8/8 | 37 | 175,874 | 72,712 | 119,424 | 1 | 13 | 14 | 0 | 0.1400166 | 0.0175021 |
| Predicted fixed | 6/8 | 34 | 183,569 | 63,131 | 113,280 | 6 | 9 | 13 | 0 | 0.1308279 | 0.0218047 |
| Predicted adaptive | 8/8 | 50 | 290,407 | 69,061 | 198,272 | 5 | 13 | 17 | 5 | 0.1699953 | 0.0212494 |

Each category cell below is goals / calls / conservative USD:

| Category | Fixed 8,192 | Predicted Fixed | Predicted Adaptive |
| --- | --- | --- | --- |
| Simple | 2/2 / 8 / 0.0201606 | 2/2 / 7 / 0.0152658 | 2/2 / 12 / 0.0331953 |
| Medium | 2/2 / 7 / 0.0288318 | 2/2 / 10 / 0.0388044 | 2/2 / 10 / 0.0322359 |
| Large | 2/2 / 9 / 0.0342918 | 2/2 / 11 / 0.0596118 | 2/2 / 12 / 0.0478662 |
| Underestimated | 2/2 / 13 / 0.0567324 | 0/2 / 6 / 0.0171459 | 2/2 / 16 / 0.0566979 |

The low fixed merge-patch budget fails twice without retaining code; adaptive
recovers twice and passes 5/5 checks, rather than merely producing longer prose.
Trial one consumes its entire first 2,048 tokens in reported reasoning, grows to
4,096, and reaches full functional delivery at call three. Trial two grows twice
and also reaches delivery at call three. All five observed allowance increases
follow real output-limit errors. However, adaptive's full merge-patch cost is
effectively tied with fixed-large (difference $0.0000345), and it uses more calls.
Across all tasks fixed-large is about 17.6% cheaper than adaptive (or adaptive
21.4% more expensive); this cohort does not establish general adaptive savings.

Not every extra call is useful progress. One large adaptive run reaches full
checks at call four, then incurs another format error/read/report sequence.
Fixed-large's second merge-patch run spends all 8,192 first-call tokens in
reasoning before recovering. Same-limit large-task variation is not a policy
effect. Per-call traces separate proposals, committed writes, actual accounting,
truncation tails and independent artifact-check gains; necessary final reporting
and verification are not automatically classified as waste.

Overall known conservative exposure is **$0.4488759**, including Native, with 129
unique provider/local IDs, zero unresolved requests and maximum per-request
reserve $0.0254772 (cap $0.03). Independently verify all 24 budget artifact hashes:
22 actual HTML files and two genuine missing-artifact failures. Retain frozen
plans/corpora, request journals, code versions, decision traces and an ignored
360-file source archive. Evidence: `.tmp/evaluations/native-budget-20261101/`,
including `evidence-audit.json`; corpus hash
`afa336db4055d155d80b2920e64345c7f07157b4a30e9a69f0f95b086e4d4104`,
experiment source hash
`819a5a8057003c3f2950e732b6d62ac6b29aa5c1441b760459c1146351c82f0f`.
Post-run Native compatibility hardening does not alter the frozen comparison.

Decision: retain bounded truncation recovery, but do not promote this small
structural predictor or change global product budgets on two repeats/four HTML
tasks. Short-task prediction can help; medium-task savings are not demonstrated;
adaptive is verified as a recovery mechanism, not a universal cost optimization.
No full 108-run experiment, exhaustive artifact/security validation, arbitrary
task generalization or exact invoice claim is made. Production defaults stay
unchanged. Protocol reliability remains a separate optimization target.

## Four-Category Budget Pilot (2026-11-01)

Run the separately authorized $0.50 pilot with frozen Prompt JSON, tools,
recovery and eight-decision/one-final limits. The unchanged structural predictor
assigns simple/medium/large/underestimated initial allowances of
2,048/4,096/8,192/2,048 to both predicted arms. Three prior regression tasks are
retained; the new CSV reconciliation page has a small interface but public,
nontrivial quoting/newline/validation/aggregation/exact-money requirements. No
minimum code length, hidden requirement, extra classifier or forced truncation
is used. Four tasks, one trial per arm: all 12 evaluated, four complete triplets,
73 known provider receipts, no evaluator/admission/timeout stop.

| Policy | Functional Goals | Calls | Input Tokens | Output Tokens | Cache Hits | Truncations | Recovery Retries | Allowance Growths | Conservative USD | USD / Goal |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fixed 8,192 | 2/4 | 30 | 214,768 | 71,302 | 136,448 | 2 | 8 | 0 | 0.1499928 | 0.0749964 |
| Predicted fixed | 3/4 | 21 | 135,674 | 34,817 | 83,968 | 4 | 7 | 0 | 0.0824826 | 0.0274942 |
| Predicted adaptive | 4/4 | 22 | 158,374 | 44,150 | 101,632 | 2 | 6 | 2 | 0.1004922 | 0.02512305 |

Recovery retries count actual next action requests following model-output/format
errors, not SDK retries, ordinary tool failures or the final-only report. Both
observed allowance increases follow provider truncation; protocol errors never
increase the allowance. All spend includes recovery and post-delivery calls.

Per-category cells below are **goals/calls/conservative USD**, not pooled averages:

| Category | Fixed 8,192 | Predicted Fixed | Predicted Adaptive |
| --- | --- | --- | --- |
| Simple | 1/1 / 6 / 0.0173103 | 1/1 / 7 / 0.0191409 | 1/1 / 3 / 0.0070722 |
| Medium | 1/1 / 6 / 0.0250809 | 1/1 / 2 / 0.0076068 | 1/1 / 9 / 0.0417255 |
| Large | 0/1 / 9 / 0.0431841 | 1/1 / 9 / 0.0470691 | 1/1 / 2 / 0.0131976 |
| Underestimated | 0/1 / 9 / 0.0644175 | 0/1 / 3 / 0.0086658 | 1/1 / 8 / 0.0384969 |

H1 is mixed. Medium predicted-fixed delivers with two calls versus six, but
simple predicted-fixed uses seven versus six. Its actual output decreases
4,489 versus 5,870 tokens, while input rises 45,847 versus 34,221 and total cost
increases. Lowering a ceiling alone is not a reliable cost saving.

H2 has a real positive example, not just a scripted threshold test. CSV adaptive
requests use 2,048 -> 4,096 -> 8,192 after two actual truncations; the artifact
first passes all 15 browser checks at call four and remains valid at call eight.
Predicted-fixed truncates twice at 2,048 and retains no artifact. Fixed-large
uses nine calls but leaves only an interface passing 1/15 checks. Its first cut
uses 6,876 reasoning tokens out of 8,192 completion tokens, leaving little room
for the action/code. Adaptive's $0.0384969 versus fixed-large's $0.0644175 includes
all initial failures and later work. This demonstrates an operational recovery
example, not a controlled counterfactual proving a universal advantage.

The large category has identical 8,192 limits in **all three arms**, yet yields
different outcomes and 9/9/2 calls. Those differences are model trajectory
variation, not budget-policy effects. Two failed fixed-large artifacts retain
only partial interfaces/unfinished scripts; successful file writes do not imply
functional delivery. Functional first-delivery and all later artifact versions
are preserved; extra reads/final reporting are not automatically called waste.
The Agent cannot access the grader or a browser verification tool in this closed
workspace-tool pilot. Canvas mounting, UI aesthetics, semantic reply quality,
cross-run continuation and general natural-language prediction are not measured.

At [official off-peak/cache prices](https://api-docs.deepseek.com/quick_start/pricing/),
fixed/predicted-fixed/adaptive totals estimate $0.054938544/$0.028898004/$0.035306196,
or $0.027469272/$0.009632668/$0.008826549 per successful artifact. Estimates are not
invoices. Conservative total $0.3329676 remains below $0.50; all 73 request IDs
are unique and every actual usage cost stays within its pre-send reserve and
$0.03 request cap. No unknown exposure remains. Eleven retained files match
their original hashes, including partial failures; nine are functional deliveries.
No failed case was silently rerun or omitted.

Evidence: ignored `.tmp/evaluations/budget-four-category-20261101/`. Corpus hash
`c7f9d75d5000e49b8be6ba14ce5fd7414357cedd222ddea3a14f0bd04074c1e1`;
source hash `c9d2306225db5f7d7a3487c9697a8df466ed8223e792991355033760b6b6f75c`.
Prepaid calibration initially caught a missing JSON import in the new grader;
fix it and add fast structural/type-comparison tests before any paid request.
The calibration module passes four tests, including one real-Edge test covering
all four reference apps plus faulty/prose controls; focused offline checks
33 passed / three browser deselected. Add this regression to the critical and
CI browser suites. Whitespace and ledger/artifact checks passed. No new full
Python/UI build is claimed for this evaluation-only work. Product defaults stay
unchanged. Retain bounded growth as a supported mechanism, but do not promote the
count-based predictor or claim statistical superiority from one run per category;
the proposed larger independent/repeated corpus still needs separate execution.

## Protocol Reliability Pilot (2026-11-01)

Run the separately authorized $0.50 pilot through one ActionService and
CapabilityService, with isolated files and an inert approval fixture. Prompt JSON
and native canonical-action functions share registry/schema context, four model
decisions, one final-only boundary and 8,192 output allowance. Native is an
evaluation-only wire adapter, not a new registry or a production mode switch.
It preserves raw function IDs, committed tool receipts and provider reasoning
replay; all native schema/replay input is included in admission and billed usage.

The first 20-run attempt exposed an evaluator defect: its inspection callback
was synchronous although ActionService requires an awaitable. Weak checks only
required an invocation, allowing scripted preflight to miss the failed inspection.
Discard that attempt for protocol/cost selection, preserve its 49 receipts and
$0.0397815 conservative cost, and strengthen required-operation assertions to
require successful observations (with explicit exceptions for expected failed
reads). Fix the callback in the fixture, not the product. Corpus v2 also makes
the capability-request path explicit rather than ambiguously accepting any
availability query. Do not compare v1/v2 scores as model improvement.

Restart the whole paired pilot in a fresh directory, carrying prior spending
under the same $0.50 ceiling. All 20 v2 runs and 10 task pairs complete, without
quota, timeout or evaluator stop. All 47 new provider receipts have known usage;
no fixture send executes without approval. Ten expected artifacts are independently
verified against retained file hashes.

| Mode | Contract Passes | Calls | Protocol Errors | Input Tokens | Output Tokens | Cache Hits | Conservative USD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Prompt JSON | 10/10 | 25 | 4 | 43,139 | 2,573 | 33,915 | 0.0160293 |
| Native action functions | 10/10 | 22 | 0 | 54,129 | 3,037 | 47,743 | 0.0198831 |

Both have zero truncations and zero unauthorized fixture dispatches. Reported
reasoning tokens are 779/618, already included in completion usage, not added
again. Successful Runtime observations number 12/13; these counts measure commits,
not semantic value, and extra calls do not earn a better task score.

Using the recorded cache counts and the verified
[official Sunday/off-peak tariff](https://api-docs.deepseek.com/quick_start/pricing/),
v2 Prompt JSON/native costs estimate $0.003029145/$0.002923329. This secondary
estimate is not an invoice and gives a different ranking from the conservative
no-cache ledger. Native eliminated the observed format errors and used three
fewer calls, but this single repetition does not establish general superiority,
lower production cost or a completion-rate improvement. No output-budget policy
is selected by this experiment.

Across discarded and corrected attempts, all 96 receipts remain accounted for:
$0.0756939 conservative known cost, zero unknown reservation, below $0.50. The
new pre-send fsynced journal retains actual request content/hash/input bytes,
output allowance and request-specific reserve; terminal records settle usage or
retain that reserve. A crash/timeout no longer needs an entire-context estimate
when a pending record exists. Journals and credentials are ignored local data.
Evidence directories: `.tmp/evaluations/protocol-pilot-20261101/` and
`protocol-pilot-corrected-20261101/`; original report hash is verified unchanged.

Full preflight: 1,347 passed / 79 optional skipped / 2 known xfailed. The fixture
defect was discovered by real traces despite that pass, demonstrating why weak
assertions are insufficient. After the fixture/runner corrections, final focused
checks: 72 passed / two browser checks deselected. Generated-contract freshness
and whitespace checks passed. No new UI build or browser-product acceptance is
claimed. The adapter is append-only/text-only and does not yet support product
history rewriting, streaming or checkpoint restoration. Default protocol and
budget settings remain unchanged; the four-category budget experiment has only
scripted transition preflight, not new real-model results or 108-run authorization.

## Declared-Contract Budget Pilot (2026-10-31)

Test-only policies use the same corrected parser, recovery, tools and eight-step
limit: fixed 8,192; declared-contract predicted fixed; and the same prediction
with bounded adaptation. New scratchpad/splitter/inventory cases select
2,048/4,096/8,192 from declared fields/actions/persistent collections. Every arm
sees the same contract, without hidden checks or an extra classifier call. This
is not general natural-language complexity estimation or a production policy.

The first attempt stopped after one completed run and one provider timeout at
30 seconds. With explicit approval, retain it unchanged and start a fresh pilot
using a uniform 120-second timeout and the same overall $0.50 ceiling. The legacy
timeout receipt lacks input length; reserve a full 1,048,576-token provider
context plus the requested output ceiling at conservative peak rates. This is
an intentionally extreme exposure bound, not a claim about consumed tokens.
New timeout receipts preserve input bytes; no automatic transport retry is added.

The restart planned 18 trials but completed only eight; the ninth stopped before
a further send because its request reserve would exceed the shared ceiling.
There are only **two fully paired task groups**, scratchpad and inventory, each
with one observation per arm. Splitter's two delivered artifacts remain evidence,
but its interrupted fixed-large arm excludes the whole task from comparisons.
The second repetition never started. Do not report 2/2 as two repetitions or
count currency admission as an Agent capability failure.

| Policy | Paired Functional Goals | Calls | Input Tokens | Output Tokens | Conservative USD | Cache/Off-Peak USD |
| --- | --- | --- | --- | --- | --- | --- |
| Fixed 8,192 | 2/2 | 7 | 29,811 | 19,820 | 0.0327273 | 0.013710594 |
| Predicted fixed | 2/2 | 10 | 71,509 | 15,173 | 0.0396603 | 0.012642438 |
| Predicted adaptive | 2/2 | 9 | 39,886 | 21,650 | 0.0379458 | 0.015134436 |

Cache/off-peak values use recorded cache counts and the verified
[official Flash tariff](https://api-docs.deepseek.com/quick_start/pricing/)
for the Saturday request window, not an invoice. Their cost ranking differs from
the no-cache conservative ledger: predicted-fixed is cheapest in this secondary
view; fixed-large uses fewer calls. Neither result establishes superiority from
one short/long pair. Inventory uses an identical 8,192 allowance in all arms, so
its differences cannot establish a prediction effect. No request allowance grew
in the comparable cohort: the single truncation occurred at the 8,192 ceiling.
Adaptive budget-growth benefit remains unmeasured here.

Artifact evidence is stronger than response length: adaptive-labelled inventory
first writes a version passing only 1/10 checks, then a second version passing
10/10. That is real repair, not merely a longer explanation; it is not evidence
that output-budget expansion caused it. Scratchpad's smaller-allowance arms each
need five calls versus three for fixed-large, with no truncation. All paired arms
have two protocol errors each; inspected failures include provider-specific DSML
control syntax instead of canonical JSON. Strict rejection preserved execution
safety. Budget size alone does not solve this model-I/O compatibility problem.

Across both attempts: 41 request attempts, 40 usage receipts and one timeout
without usage. Known usage at conservative rates totals $0.1626417. Unknown-call
reserve is $0.3244032; combined admission exposure is $0.4870449, below $0.50.
The $0.487 figure is **not actual spend**. Restart-only known cost is $0.1512333;
incomplete/non-comparable calls remain included in total accounting. Original
report hash is checked against the restart ledger; raw reports are not repriced
or overwritten. Local evidence: ignored `budget-prediction-20261031/` and
`budget-prediction-20261031-restart/` under `.tmp/evaluations/`.

Preflight: 46 checks including real-browser positive/broken/prose-only oracles
passed. Final focused offline checks: 47 passed / two browser checks deselected,
including timeout input receipts, no hidden retries, carried exposure, seeded
schedule, equal B/C initial predictions, equal public contracts and no private
grader leakage. No new full Python/UI/SDK build is claimed for this evaluation-only
change; production defaults and Python Core remain unchanged.

## Runtime Efficiency Experiment (2026-10-30)

The fixed ten-case scripted boundary corpus retained real Runtime/file effects:
27 to 17 model-boundary calls, 616,132 to 361,042 request characters, and 8/10 to
10/10 checks. These are not billed tokens or real-model quality measurements.
Historical baseline and final reports: `.tmp/evaluations/efficiency-before/`
and `.tmp/evaluations/efficiency-after-final/` (ignored local evidence).

The live `deepseek-v4-flash` policy ablation completed seven paired cases, both
conditions delivering 7/7 artifacts. Fixed/adaptive calls were 26/29; prompt
tokens 82,896/97,046; completion tokens 4,289/6,608; reported cache hits
57,856/69,248. Conservative paired costs were $0.0300156/$0.0370434, so this
sample does **not** demonstrate cost savings. A follow-up verified-file pair
used 4/3 calls; the adaptive long-source case failed to deliver, and its fixed
counterpart stopped at admission and is excluded from paired comparisons.
Neither cohort produced output truncation; live output adaptation is unmeasured.

Total across both cohorts: 77 requests, $0.0927816 conservative estimate under
one $0.10 ceiling. Rates were $0.30/$1.20 per million input/output tokens without
cache discounts, based on [official peak prices](https://api-docs.deepseek.com/quick_start/pricing/),
not the invoice. Both conditions share current Runtime safety/prefix behavior;
this is a small single-repeat policy ablation, not a historical checkout or a
qualified semantic Judge score. Receipts and incomplete attempts remain in
`efficiency-live` and `efficiency-live-followup` reports. Larger/repeated live
experiments need new explicit budget authorization.

### Goal-Progress Follow-Up

Zero-cost audit of the original paired traces found eight committed writes per
arm. Fixed/adaptive calls were 26/29 and protocol errors 5/7; both delivered 7/7.
The calculator was first written at call 1/2, with total calls 2/5. Both retained
HTML hashes match the original delivery receipts. Extra post-write requests are
not automatically waste: reading back and final reporting can be necessary.
Historical intermediate functional snapshots were not retained, so no such
progress curve is inferred. Audit: `.tmp/evaluations/task-progress-previous/`.

### Three-Arm Live Delivery (2026-10-31)

After separate $0.50 authorization, run three tasks twice per arm under common
Runtime/tool/recovery/Observation rules and an eight-decision cap. All 18 runs
were evaluated; 93 paid requests had complete usage, with no budget/evaluator
stop. Request alias: `deepseek-v4-flash`; response model: `deepseek-flash`.

| Output Policy | Functional Goals | Calls | Truncations | Protocol Errors | Conservative USD | Conservative USD / Goal |
| --- | --- | --- | --- | --- | --- | --- |
| Fixed 2,000 | 3/6 | 30 | 7 | 6 | 0.080366 | 0.026789 |
| Fixed 8,192 | 6/6 | 26 | 0 | 10 | 0.097232 | 0.016205 |
| Adaptive 2,000-8,192 | 5/6 | 37 | 6 | 9 | 0.099244 | 0.019849 |

The first adaptive to-do run reached five functional checks through actual file
versions. Fixed-small left an HTML/CSS shell with an empty script; remediation
JavaScript in its final reply earned no delivery credit. In the second adaptive
to-do run, truncation increased allowance from 2,000 to 4,000, but a fenced JSON
proposal and concatenated objects then exhausted the shared recovery counter;
no artifact was committed. More output allowance alone does not solve protocol
adherence. Fixed-large reached every goal, although its ten protocol errors also
remain a reliability issue. No intermediate functional regressions were observed.

The original budget ledger conservatively ignores cache and off-peak discounts:
total $0.2768418. All 93 receipts report cache usage, and calls occurred between
16:19:10 and 16:34:13 UTC on October 30, outside the published peak windows.
Using [the current official Flash rates](https://api-docs.deepseek.com/quick_start/pricing/)
($0.15 uncached input, $0.003 cached input, $0.60 output per million tokens), a
separate sensitivity calculation gives fixed-small/fixed-large/adaptive totals
$0.026240/$0.038211/$0.029414, or $0.008747/$0.006368/$0.005883 per verified goal.
Thus fixed-large has the best completion count here, while adaptive has the
lowest cache/off-peak estimated cost per completed goal. Neither pricing view is
an invoice. Preserve both views; do not overwrite historical budget receipts.

Adaptive has real artifact benefits over the low fixed ceiling in this sample,
but does not dominate the high fixed ceiling. Its prompt tokens are 210,133
versus 107,104 for fixed-large, despite fewer output tokens (30,170 versus
54,251): repeated calls/context, not simply longer answers, matter. Check gains,
thought length and code length are different measurements. Tail calls may include
necessary verification/reporting and are not all classified as waste.

Raw report, artifact versions and the tariff calculation are under ignored
`.tmp/evaluations/task-progress-20261031/`; source/corpus hashes are recorded.
This is a small repeated, restricted-tool code-delivery experiment, not proof of
general superiority, response truthfulness, production Canvas integration or
cross-restart continuity. No production policy was changed based on the result.
See [the execution protocol](testing-strategy.md#goal-progress-versus-output-length).

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
| Production startup composition | Existing HTTP system tests compose their own Runtime and fixture browser tests bypass startup. They missed a built-in `file` source being registered again by the production integration, and a swallowed initialization failure reported as success. | Add unmodified launcher subprocess tests over fresh SQLite/identity/file stores, restart persistence and real startup faults; add real React/Vite-to-production-API registration, login, upload and reload. No API fixtures or product-module overrides in these cases. Keep model, Neo4j and desktop acceptance explicitly separate. |
| CI | SDK tests run, but React `npm test` is omitted; browser acceptance is opt-in and absent from CI. | Run existing UI tests; add bounded isolated system checks and publish test artifacts. No paid providers in CI. |
| Model evaluation | No versioned independent behavior corpus, Judge calibration gate, repeated comparison, or measured quality baseline. | Add evaluation-only corpora, production-owned prompt adapters, hard evidence checks, independent Judge protocol and explicit budgets. Unreviewed calibration labels cannot qualify a Judge. |
| `test_voice_routes.py` (speech integration pass) | Five old tests replace private dispatch functions, so provider serialization, per-user configuration, MIME and bounded errors are not exercised. | Replace with route tests over real user env and HTTP MockTransport. Keep actual Gateway/Conversation/Action/history and approval-waiting paths. Add SDK multipart/binary/abort checks and desktop/mobile browser configuration, recording and cleanup; no paid audio calls. |

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
| Speech provider I/O | voice route HTTP contracts, user env isolation, bounded/redacted errors, real conversation/history and approval waiting; SDK multipart/audio/abort; voice browser settings/recording/cleanup | provider quality is not judged by scripted responses | real microphone, configured STT/TTS availability, pronunciation, recognition accuracy and billing |
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

## CI And Gold Follow-Up (2026-10-29)

Remote evidence: [CI run 40867340547](https://github.com/dndcreator/Promethea_Agent/actions/runs/40867340547)
at commit `29fe12293cd9e191d722b654ce7b12c4d2807577`. TypeScript passed;
Python failed collection and the browser failed before page execution. Linux
artifact `12894825594` contains three `ModuleNotFoundError: httpx` failures.
Declare the test dependency directly rather than rely on another package's
transitive dependencies. Browser logs show Chromium `No usable sandbox` under
Ubuntu AppArmor user-namespace restrictions. Enable namespaces only on the
disposable CI Linux runners, retaining `chromium_sandbox=True`. This is not a
product sandbox default or a host-desktop permission change.

The runner now emits the original failure-log tail, classifies pytest collection,
usage, empty selection, internal/process failures and timeout, retains malformed
JUnit as failure, and records Python/platform/critical dependency versions.
CI-runner regressions inject collection, timeout and malformed reports and
assert nonzero exits plus visible original causes. No automatic success-on-retry
policy was introduced.

The v3 behavior corpus has 37 Gold contracts in seven groups, each with 5-7
positive/negative/boundary/curated-historical cases and observable expectations.
They are engineering-reviewed synthetic cases, not newly human-certified Judge
labels. Before/after comparisons require the same Judge and calibration and
show per-case acceptance changes and resource metrics; a new corpus does not
have a retrospectively invented model-quality baseline.

Four real-service tasks check autonomous local plan creation, foreground child
artifact delivery with parent-context isolation, recalled memory after closing
and reopening SQLite, and Canvas expression/feedback/edit/next-turn state.
They script only the model boundary, not the service being tested. The first
delegation task exposed a genuine Gateway contract bug: legacy ChatParams
discarded metadata, attachments and Task options. It now reuses canonical
RunRequest; an explicit regression also rejects forged user identity. A Canvas
assertion was corrected to select the intended component, not the root container.

Local verification: 1,222 passed / 62 skipped / 2 known xfailed in 109.73 s;
cross-service/evaluation/request checks 30 passed, CI-runner checks 4 passed,
and SQLite Gold recall 15/15 with zero model calls. Generated types and workflow
YAML validation passed. A fresh isolated installation was attempted but stopped
after prolonged network transfer of the Playwright package; it did not complete
and is not claimed passing. Linux/macOS execution and a new remote CI run remain
unverified until submission. No real-provider quality or complete browser +
Runtime + model task is claimed by the four scripted service journeys.

## Remaining Evidence Gaps

Protocol follow-up (2026-10-31): the live task-progress experiment exposed two
independent blockers: low initial allowance caused truncation, then fenced or
concatenated JSON exhausted the same recovery counter. Complete outer JSON fences
are now accepted through the existing strict action parser; incomplete or
ambiguous proposals remain non-executable. Separate output-limit, empty-response
and protocol counters retain the existing total step bound and one answer-only
completion request. The dedicated mixed unit/integration regression file is in
the critical suite. Full Python regression: 1,317 passed / 78 skipped / 2 known
xfailed; generated TypeScript contract freshness passed. Two real Edge
React/SDK/SSE/history cases and five CI-runner regressions also passed. This is deterministic
evidence only; no new paid-model comparison or budget-prediction gain is claimed.
Tool argument validation is still implementation/provider-specific, not a
universal CapabilityService JSON Schema guarantee. A subsequent prediction
experiment must use Runtime-visible structured inputs, the same parser in all
arms, held-out short/medium/long tasks and a separately authorized live budget.

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
