# Lightweight Goal Gaps

## Reference And Scope

Yu Luo et al., **Beyond Memory: Harnessing Long-Horizon Agents with Explicit
Belief States**, arXiv:2610.01415v1, October 2026.
[Paper](https://arxiv.org/abs/2610.01415) |
[Method](https://arxiv.org/html/2610.01415v1#S3) |
[Cost analysis](https://arxiv.org/html/2610.01415v1#S4.SS3).

PoS distinguishes information still needed (epistemic gaps) from goal conditions
not yet attained (achievement gaps), validates belief updates, and diagnoses
stalled progress. In its RCA-100/Qwen3.7-Plus cost experiment, total tokens were
5.06 times Raw Trajectory, including belief maintenance and Sentinel work. This
is one reported setting, not an overhead estimate for every task.

Promethea adopts the two gap types, explicit revisioned updates, and bounded
repetition monitoring. It deliberately does not reproduce PoS's full world graph,
independent LLM Sentinel, confidence-based health score, or semantic trapping
classifier. No paper-level performance or savings percentage is claimed.

## Existing Runtime Integration

```text
Main model: normal ModelAction + optional gap_update
  -> ActionService: validate delta, scope and evidence
  -> existing CapabilityService execution and RuntimeObservation
  -> local repetition monitor
  -> next ordinary model step: one current, bounded gap projection

TaskService: durable task-bound state and revision/lease checks
Moirai: compact outcome evidence for existing process distillation
```

There is no additional control loop or top-level service. Gap interpretation
remains model work; transition legality, persistence and explicit value checks
are Runtime work. `RunContext.goal_gaps` is a projection, not another authority.
Main-model context and its revision enter the existing model-call manifest.
Memory, cognition recall, Workflow retention, and safety/approval policy remain
owned by their existing services.

Ordinary chat does not create a durable Task. A task-bound Action run reads the
Task's current gap state; transient runs own their own state. Approval and
refusal checkpoints retain it. Task snapshots, export/import and restart reuse
the same persisted records. Updating the Task objective explicitly resets gap
state while recording its previous value; stale writers cannot commit against
the old objective. A present execution lease is checked at the same boundary.

Public HTTP/SSE and SDK run requests can supply an owned `task_id` explicitly;
omitting it keeps ordinary conversation semantics. Public Task and Workbench
projections include `goal_gaps` without monitoring or causal-boundary internals.
Confirmation checkpoints retain Task identity, objective and the original
Runtime execution token. They do not acquire the identity of a replacement
worker. Task authority is checked before model/dispatch boundaries even if the
model emits no gap delta. Leased execution requires its trusted Runtime token;
the client request cannot grant one.

## Delta Contract

Attach `gap_update` to an existing answer, capability request/inspection, or tool
batch. Omit it when unnecessary or unchanged. For example:

```json
{
  "revision": 0,
  "create": [{
    "id": "export_valid",
    "kind": "achievement",
    "requirement": "The document export passes the validator",
    "check": {
      "tool_name": "document.validate",
      "pointer": "/valid",
      "expected": true
    }
  }],
  "focus": ["export_valid"]
}
```

The example tool name is illustrative: the actual tool must exist in Registry.
After its real observation, update with the current revision:

```json
{
  "revision": 2,
  "updates": [{
    "id": "export_valid",
    "state": "resolved",
    "evidence_refs": ["obs_runtime_receipt"]
  }]
}
```

The revision includes monitoring-state commits, so it must be read from the
current projection, not guessed from the number of model updates. IDs,
and requirements are immutable. An unverified check may be replaced by
reopening the same gap, without evidence, and declaring a new check. States are
`open`, `blocked`, or `resolved`; there is no silent deletion or unbounded
recursive goal decomposition.

The model owns decomposition and the semantic interpretation of observations.
Resolution requires successful observations supplied by Runtime. Without a
check, knowledge can resolve as `inferred`. An achievement stays open during
execution; a final answer can close it as `reported` once all tracked gaps
are resolved. Neither status counts as independent verification.
With a check, Runtime must
match the registered tool identifier and exact JSON value at the JSON Pointer.
The check must precede the verifying observation. Causal observation boundaries,
not wall-clock comparisons, enforce this. Reopening invalidates the previous
verification boundary. Refused or failed actions cannot establish resolution.
Declared output schema types and fields marked as transport metadata constrain
admission, but do not prove that a check is semantically sufficient.

A gap can declare `depends_on` when a downstream result needs earlier inputs.
For semantic resolution, prerequisites must be resolved. For a checked result,
the prerequisites also require passed checks. The
dependent Observation must follow the prerequisite Observations; optional
`check.bindings` compare exact JSON values between those receipts. Replacing or
reopening a prerequisite invalidates dependent results. Runtime still permits
exploration before verification, but cannot use the trial as a completed gap.
Dependencies are local to the Goal Gap ledger; they do not add a second task
or reasoning graph.

Passing a model-declared check proves only that specific assertion, not its
relevance or coverage of the user's entire goal. `checks_passed` is reported
separately; overall `goal_verification` remains `unknown`. TaskService still
derives Task lifecycle status. During execution, an answer cannot complete with
open or blocked tracked gaps. An explicit blocked report may settle the current
slice after every remaining gap is marked blocked with evidence. It carries
`goal_blocked` and an unverified goal, so Task drivers pause rather than complete.
Budget-limited final reports also remain unverified. An untracked direct reply
does not require fabricated gaps.

Before persisting `await_user`, Runtime checks a typed user dependency, its
references to unresolved gaps, and any cited observations. User-only information
requires a text request; a human-only action needs Runtime evidence. The model
still judges whether the information or decision genuinely belongs to the user.
Tool failures alone do not establish that dependency.

Invalid gap deltas become bounded feedback on the next ordinary model step.
A terminal decision that depends on a rejected update cannot pass. Persistence
or execution-fencing failures still fail closed.
This does not bypass recovery admission: when a recovery decision is required,
an invalid delta cannot grant permission to execute the proposed tool batch.

The model projection also derives a bounded `recent_obstacles` list from the
existing committed Observations, including capability and action-validation
failures. It is available even before the model declares a gap. This is not a
second persisted error ledger: the model interprets the obstacle and may create,
block or reopen relevant gaps through the same delta contract. Runtime does not
invent semantic goals or treat a failed observation as successful evidence.

## Cost Controls

- Zero dedicated model calls for extraction, review, monitoring or recovery.
  Main-model gap output and its protocol/context still consume tokens.
- Default maximum 12 tracked gaps, six create/update operations per decision,
  four focus ids, an 8 KB delta limit and a four-step monitoring window.
- Default current-state projection budget is 2,400 characters, not tokens. It
  prioritizes outstanding IDs and states, shortens requirement text and omits
  bulky details before dropping goals. Previously persisted larger ledgers may
  need a larger budget after tightening configuration.
- Gap deltas are removed from subsequent assistant-action history; only the
  current projection is added to each model request. Existing tool/observation
  history is not otherwise compressed or rewritten.
- Moirai receives compact gap outcomes, not another world graph or full set of
  monitoring frames. Learning still runs through its existing idle distillation.

The Runtime monitors repeated action/results, repeated structured error families
even with changing arguments, and failures declared non-retryable. It does not
parse website names or natural-language error text. Monitoring remains active
without declared gaps and when all gaps are blocked. Approval, protocol-validation,
model-output and control-rejection receipts do not masquerade as executed steps.
An evidence-backed blocked update for a focused gap also requests reassessment.

### Controlled Recovery

ActionService enters `reassessing` for the next ordinary model decision.
Capability inspection and new calls classified read-only by the ToolRegistry
can investigate through the usual authorization path without a recovery
packet. Other tool calls require a recovery decision inside the existing delta:

```json
{
  "revision": 7,
  "recovery": {
    "strategy": "replan",
    "reason": "Inspect another source before retrying the failed operation",
    "evidence_refs": ["obs_current_obstacle"],
    "repair_refs": []
  }
}
```

Strategies are `investigate`, `replan` and `retry`. Runtime validates the revision,
current obstacle reference and the concrete proposed batch before authorization
or dispatch. Merely changing the reason text cannot replay a known non-retryable
failed call. That requires `retry`, a newer successful observation in `repair_refs`
and at most one granted retry for the failed call. Repeating a failed call twice
within one batch is refused. One ordinary transient failure can retry once
without a separate recovery decision. No call in a rejected batch is executed.

An admitted decision starts one trial. When gaps are tracked, a novel successful
result does not clear Recovery. A checked resolution can clear it; independently
authorized read-only investigations remain available in the meantime. Runs with
no declared gaps retain the existing successful-trial behavior.

The model may attach `gap_update.belief_updates` to an existing decision. Each
entry identifies a gap, a claim and successful Observation references. Runtime
keeps a bounded set of these candidate beliefs in the same checkpoint, prioritizes
focused gaps when projecting them, and ignores exact repeated claims for the same
gap even when the source changes. A candidate does not verify the claim, close
the gap or reset Recovery. Raw observations remain separate from task beliefs.

Foreground chat and durable chat Tasks have a configurable, one-time extension
at the Action step boundary. For tracked gaps, it requires recent candidate or
checked progress and a fresh successful tool observation. It does not reset
Recovery, bypass tool policy, or change model-request admission. An explicit
RunContext cost or token limit still disables automatic extension.

Repeated no-progress trials and consecutive rejected proposals
are bounded by `max_recovery_attempts`; distinct alternatives are still bounded
by the normal Action budget, but do not exhaust Recovery just by failing.
The final model call can report partial progress or propose a validated wait,
not dispatch another tool. Recovery does not bypass policy, approval, Task leases
or cancellation.
The model still judges whether a different method and its repair evidence are
semantically relevant; Runtime verifies receipts and ordering, not that judgment.

Advisory Recovery is the default; strict Recovery is available by setting
`action.gaps.advisory_recovery` to false. The optional
`action.gaps.semantic_context` adds a bounded original-goal excerpt and linked
evidence index. Advisory Recovery lets fresh registered workspace
operations pass the same heuristic gate as fresh read-only operations. Neither
option bypasses ordinary authorization, exact failed-call replay guards, or
delivery checks. External and privileged operations keep their existing rules.

Session/Task checkpoints retain this control state with their Observations through
approval, restart and human waits. A human reply opens another bounded decision
slice but does not count as a successful repair or authorize a tool. Independent
Task runs keep the durable goal requirements while starting fresh execution
monitoring; old loop-local observation references must not deadlock a new run.
The old facts remain in Runtime's event history. Renaming a gap or claiming
inferred resolution within a run does not clear failed-call guards.

This deterministic guard does not detect all semantic drift when every irrelevant
result is novel. Semantic gap interpretation remains model work. No dedicated
reflection call is added, although corrective decisions and their context can
increase total model use. Comparative live A/B evaluation remains necessary.

## Configuration And Tests

Use existing JSON/env configuration, under `action.gaps` or `ACTION__GAPS__...`.
`enabled`, `max_gaps`, `max_updates`, `window`, `context_chars`, and
`max_recovery_attempts` are configurable.
Capacity settings must leave room for all outstanding identities. Disabling new
updates does not erase already-persisted task requirements.

```bash
python -m pytest -q tests/test_goal_gaps.py tests/test_action_progress_control.py tests/test_action_service.py tests/test_task_service.py tests/test_moirai_learning.py
python scripts/generate_public_contracts.py --check
```

Tests verify call counts, bounded projection, revision conflicts, real check
values and causal boundaries, reopening, refusal checkpoints, durable resume,
user isolation, export/import, completion guards, and persistence rollback.
The public `GoalGapView` omits internal monitoring and causal-boundary state.
Public contract types continue through the existing JSON Schema/TS generator.
