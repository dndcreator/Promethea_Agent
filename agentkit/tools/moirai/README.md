# Moirai

Moirai owns recoverable procedures and process experience. `moirai.py` retains
the checkpointed workflow tool; `learning.py` is its provider-independent learning
component, consumed by the existing reasoning-template memory and Conversation
service. It adds no new first-class service or tool execution path.

## Learning Flow

1. After an Action loop settles, record an immutable, user-scoped episode from
   Runtime observations: capability intent, side-effect constraints, attempted
   tools, errors, approval outcomes, evidence references, and declared procedure
   versions. Pending confirmations are not complete episodes.
2. After an idle delay, consolidate a bounded batch through `DistillationBackend`.
   Produce task-scoped or cross-task hypotheses with preconditions, adaptable
   stages, recovery guidance, and verification suggestions. Cross-task hypotheses
   require support from distinct observed capability contexts.
3. Expose relevant hypotheses and recent observed outcomes in the existing
   capability-resolution observation. The model may adapt, combine, or ignore
   them. Unmatched tasks retain general planning; permissions and execution
   remain exclusively Runtime-owned.
4. Later failures can revise a hypothesis. Active versions retain up to 32 support
   references and 32 counterexamples; immutable prior versions retain earlier
   evidence. `procedure_refs` records declared
   use of a version exposed in that loop, not proof that it caused the outcome.

Tool execution success is not task success. Episodes currently use
`goal_verification: unknown`; there is no invented reward, parameter update, or
claim of measured learning quality. Hypotheses require held-out evaluation before
claims of improvement. Instruction text is model-generated and advisory, not a
verified policy.

## Storage And Lifecycle

User-scoped episodes, revisions, and consolidation cursors live in
`brain/basal_ganglia/moirai_learning/learning.sqlite3`, independent of the Memory
backend. Personal workspace export/import includes episodes and revision history;
user cleanup removes them. Tool arguments and raw results are not copied, but
goal text and capability objectives can contain personal information.

Foreground chat interrupts that user's pending consolidation; shutdown cancels
workers. A transaction commits revisions and cursor together. Cancellation or
failure before commit leaves the batch available for retry. After restart, the
next eligible completed Action schedules pending work again; this is not a
separate always-running daemon. Concurrent consolidations use optimistic commit
checks so a stale batch cannot overwrite newer progress.

## Configuration

Use the existing config/env mechanism:

| Environment Variable | Default | Purpose |
| --- | --- | --- |
| `MOIRAI_LEARNING__ENABLED` | `true` | Record and recall process experience. |
| `MOIRAI_LEARNING__DISTILLATION_ENABLED` | `true` | Permit background model calls. |
| `MOIRAI_LEARNING__MIN_EPISODES` | `8` | Minimum pending episodes; range 2-32. |
| `MOIRAI_LEARNING__INTERVAL_SECONDS` | `3600` | Minimum time between committed batches. |
| `MOIRAI_LEARNING__IDLE_SECONDS` | `60` | Delay before attempting a batch. |
| `MOIRAI_LEARNING__TIMEOUT_SECONDS` | `30` | Maximum distillation call duration. |

Distillation uses the user's existing configured model and may incur API costs.
Disabling distillation keeps factual recording and recall without new learning
calls. Disabling learning stops this component's recording and recall; existing
successful-template and Workflow retention mechanisms remain independent.

## Local Models And Future LoRA

`DistillationBackend.distill(batch)` is the replaceable boundary. The current
`ModelDistillationBackend` delegates to Promethea's existing model interface.
A local or LoRA-adapted model can implement the same contract without changing
storage, permissions, or Action execution. Output receives the same schema and
episode-reference checks regardless of backend.

`training_examples(user_id)` provides unlabelled local episode data, not a ready
supervised dataset. Redaction, quality labels, train/evaluation splits, actual
training, and model publication are intentionally not implemented here.

Run focused tests with the project's Python environment:

```bash
python -m pytest tests/test_moirai_learning.py tests/test_action_service.py tests/test_reasoning_template_memory.py tests/test_moirai_service.py -q
```
