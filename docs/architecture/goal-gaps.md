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
requirements and checks are immutable. States are `open`, `blocked`, or
`resolved`; reopening is supported. There is no silent deletion, supersession,
dependency graph, or unbounded recursive goal decomposition in this version.

Resolution requires successful observations supplied by Runtime. Without a
check it is `inferred`, not independently verified. With a check, Runtime must
match the registered tool identifier and exact JSON value at the JSON Pointer.
The check must precede the verifying observation. Causal observation boundaries,
not wall-clock comparisons, enforce this. Reopening invalidates the previous
verification boundary. Refused or failed actions cannot establish resolution.

Passing a model-declared check proves only that specific assertion, not its
relevance or coverage of the user's entire goal. `checks_passed` is reported
separately; overall `goal_verification` remains `unknown`. TaskService still
derives Task lifecycle status. A finished execution with outstanding tracked
gaps becomes `waiting_user`, while a final assistant reply can explain unfinished
work without pretending to have completed it. Tasks without gaps retain their
existing lifecycle behavior. Explicit user completion remains available.

Invalid gap deltas do not discard a valid tool action or assistant answer. The
rejection becomes bounded feedback on the next ordinary model step, without a
dedicated retry. Persistence or execution-fencing failures still fail closed.
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

ActionService enters `reassessing` for the next ordinary model decision. Final
answers, `await_user` and capability inspection/resolution remain available. A
tool proposal requires a recovery decision inside the existing delta:

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

An admitted decision starts one trial. New successful evidence returns control
to normal execution, but is not verified goal progress; only checked resolution
has that meaning. Repeated/failed trials and rejected proposals are bounded by
`max_recovery_attempts`. At the bound, execution stops and the existing final
model call supplies a progress report or durable human-input wait, not another
tool action. Recovery does not bypass policy, approval, Task leases or cancellation.
The model still judges whether a different method and its repair evidence are
semantically relevant; Runtime verifies receipts and ordering, not that judgment.

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
