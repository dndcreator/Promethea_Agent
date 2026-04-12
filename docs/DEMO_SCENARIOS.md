# Demo Scenarios

## Long-lived personal assistant

### Goal

Show that the assistant can preserve user-relevant continuity across sessions instead of behaving like a stateless chat.

### What the user does

- Starts a session and states preferences/constraints.
- Returns later and asks related tasks.

### What Promethea does

- Persists session-linked memory signals.
- Recalls relevant context into subsequent turns.
- Preserves user scope boundaries.

### What this proves

Promethea supports long-lived assistant behavior with memory-aware runtime paths.

### Suggested visuals

- Chat timeline screenshot (first and later turn)
- Memory graph/recall viewer panel
- CLI `memory recall-runs` output

---

## Multi-user internal runtime

### Goal

Show that multiple users can use the same runtime without data bleed.

### What the user does

- User A creates sessions and writes context.
- User B logs in and performs similar tasks.

### What Promethea does

- Enforces user ownership in sessions/memory/config/workspace paths.
- Keeps per-user logs and runtime traces isolated.

### What this proves

Promethea is not single-user by assumption; it has explicit multi-user isolation semantics.

### Suggested visuals

- Two user session lists side-by-side
- User-scoped log path examples
- Security/audit report snippet showing ownership boundaries

---

## Safe tool execution with audit

### Goal

Show that tool actions are governed and observable.

### What the user does

- Triggers a task requiring tool/workspace activity.

### What Promethea does

- Evaluates policy/sandbox constraints.
- Executes allowed actions.
- Emits trace/audit events for critical operations.

### What this proves

Tool use is runtime-governed and auditable, not opaque one-off calls.

### Suggested visuals

- Tool call blocks in UI
- CLI/HTTP security report output
- Audit event excerpt for workspace/tool action

---

## Resumable workflow with approval

### Goal

Show workflow continuity under interruption and gated progression.

### What the user does

- Starts a workflow.
- Pauses or hits approval gate.
- Resumes and completes.

### What Promethea does

- Maintains workflow run/checkpoint state.
- Supports resume/retry patterns.
- Continues artifact generation after resumption.

### What this proves

Promethea can handle non-trivial multi-step runtime execution, not only single-turn responses.

### Suggested visuals

- Workflow run list/status output
- Checkpoint view
- Generated artifact file path/output
