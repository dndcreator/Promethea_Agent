# Task Runtime

`TaskService` is the durable work domain. It is separate from
`ConversationService`: conversations are the interaction surface, while tasks
represent user goals that may span conversations and execution attempts.

## Core records

- `Task` (`task_*`): user-owned goal, optional originating sessions, lifecycle,
  and linked runs.
- `Task Run`: one execution plan. The first backend is Workflow, which reuses
  its existing `wf_run_*` identifier directly.
- `Task Attempt` (`task_attempt_*`): one process acquisition of a Run. A Run
  may have several attempts after interruption or scheduled retry.
- `Task Event`: append-only task-domain facts such as task creation and run
  state transitions.

Every Task has a monotonic `revision`. User commands may supply
`expected_revision`; stale commands fail instead of overwriting a newer pause,
edit, or completion. Runtime execution uses a separate monotonic
`activation_epoch`, owner id, attempt id, and expiring lease. These fields form
the fencing token checked at Workflow commit boundaries. Lease ownership is
scoped to a Run, so independent Runs under one Task can execute concurrently.
Task and Workflow snapshots use atomic replacement and fail startup loudly on
invalid durable state; corruption is never interpreted as an empty task list.

## Lifecycle and detached execution

`TaskService` owns the durable Task state machine:

`open -> running -> waiting_user | paused -> completed | failed | cancelled`

Run state is reported by execution engines, but only `TaskService` derives and
persists the parent Task state. Invalid user-driven transitions are rejected.
Task control APIs expose update, start-run, pause, resume, and cancel commands.

Explicit workflow runs are prepared and persisted before execution begins.
`TaskRuntime` then advances them in a process-owned asyncio job, so the HTTP or
tool request can return without owning the execution lifetime. A dropped UI or
HTTP connection therefore does not cancel the run. On process startup,
TaskRuntime marks the previous process's open Task Attempt as `interrupted`,
repairs any persisted `running` Step Attempt, acquires a new execution epoch,
and continues from the most recent confirmed Workflow boundary. Graceful
shutdown performs the same explicit interruption before process state is lost.

Each Workflow Step persists an attempt record before execution. It carries a
stable idempotency key in the form `run_id:step_id`; retries and recovered
Attempts reuse it, and tool calls receive it as a stable request id. A completed, failed, waiting, or
interrupted attempt is retained as history instead of being overwritten.

Transient tool/provider failures enter durable `retry_wait` when retry policy
allows another attempt. The Run stores `next_retry_at` and exponential backoff
state. A process-owned supervisor scans durable Runs and reacquires due work,
so retry does not depend on the browser, conversation, HTTP request, or an
in-memory sleep surviving.

Pause is cooperative at Workflow step boundaries. Cancellation stops the
process-local job and persists both Workflow Run and Task as cancelled. External
side effects remain at-least-once across a hard crash: a process can die after
the remote action succeeds but before its receipt is committed. Built-in tool
adapters receive the idempotency key, but an external provider must honor it or
offer reconciliation for exactly-once-like behavior.

## Boundaries

- Ordinary chat and ephemeral reasoning/tool traces do not create a task
  implicitly. Runtime bridges mark those workflow runs with
  `task_mode=ephemeral`.
- Starting a workflow creates or binds a task, then synchronizes workflow
  lifecycle state to its Task Run.
- `trace_id` remains the request-level evidence key. `task_id` and `run_id`
  are optional fields on `RunContext` for downstream services.
- Task state is user-scoped portable data and is included in personal workspace
  export/import. Credentials and process handles remain excluded.
- The current JSON persistence and startup orphan repair target one local
  Gateway process. Multiple machines must not write the same state files; a
  future shared database deployment needs transactional lease acquisition.
- A sleeping or powered-off machine performs no work. On wake or restart, the
  supervisor reconstructs execution from durable state and continues.

This gives Workbench, background execution, and future subagents a shared
parent without turning conversations into task containers.

## Runtime Events

Gateway events are persisted to a bounded, append-only `RuntimeEventLog`. Its
sequence resumes across restarts, nested secret fields are redacted, and rotated
archives prevent unbounded disk growth. Persistence runs off the asyncio event
loop. Observability events remain best effort if the log is unavailable, while
`interaction.completed` fails closed so Memory never observes an interaction
that was not committed.

The normalized envelope carries optional conversation, task, run, and trace
identities. Memory tracks a durable consumer cursor, replays committed but
unfinished interactions after restart, and advances the cursor only after its
existing `MemoryWriteGate` pipeline completes. Source event identity is carried
into memory metadata. Delivery is intentionally at least once across a crash;
the semantic and graph dedupe gates make replay idempotent at the content layer
without pretending that a file cursor and every backend share one transaction.

Task state remains owned by `TaskService`. Its committed lifecycle changes are
mirrored to the shared event stream for Workbench and future subscribers; the
event stream does not become a second task-state authority.

## Workbench projection

`WorkbenchProjection` is the user-scoped read model for the right-side runtime
monitor. It combines Task state, runs, workflow recovery, memory review state,
and normalized runtime activities behind one snapshot API. On first access it
hydrates a bounded per-user timeline from Runtime Event Log; after that it
subscribes to `EventEmitter` and updates the materialized view incrementally.
The UI no longer joins independent Memory and Workflow APIs to invent task
state. Reopening a conversation or reconnecting a client reads the same durable
Task/Run scope and reconstructed activity timeline.

The Runtime Event Log remains the complete audit source, but it is not rendered
one event per row. The projection assigns stable business activity identities
to reasoning, tool, memory, workflow, task, and artifact lifecycles. Later
events update the existing activity, compatibility mirrors collapse into the
same row, and transport or execution bookkeeping is omitted from the user
timeline. Reasoning-tree nodes remain durable execution data; the Workbench
shows their readable objective and outcome rather than their raw tree shape.

The public Task view exposes identity, lifecycle, revision, linked Runs, and
timestamps. Process ownership, execution leases, activation epochs, raw
attempts, and recovery tokens stay inside `TaskService` and `TaskRuntime`.
Workbench clients can read a snapshot or subscribe to the same projection over
SSE. Every streamed snapshot carries a Runtime Event Log cursor; reconnecting
clients resume after that cursor instead of creating another state authority.
