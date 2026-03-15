# Scenario: Workflow + Workspace + Security Audit

This document walks through one of Promethea's signature capabilities:  
**a multi-step workflow that produces a workspace artifact and generates a queryable security audit trail** — all in one operation.

This is a differentiating feature compared to most agent frameworks, where there is no structured audit and no workspace isolation.

---

## What you will see

1. A workflow runs two steps: reasoning → artifact write.
2. The artifact is written to a sandboxed workspace under the user's namespace.
3. The write is captured as an `AuditEvent` in the event bus.
4. You query the audit report and see the exact operation recorded.

---

## Prerequisites

- Promethea running locally (`python start_gateway_service.py`)
- `curl` or any HTTP client
- Memory and sandbox can be enabled or disabled — this scenario works either way.

---

## Step 1 — Start the service

```bash
python start_gateway_service.py
# Gateway API: http://127.0.0.1:8000
```

---

## Step 2 — Trigger the workflow

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/plan_and_save \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "Design a memory system architecture for a personal AI assistant",
    "session_id": "demo_session",
    "workspace_id": "demo_project",
    "user_id": "demo_user"
  }'
```

### What happens internally

1. `WorkflowEngine.define_workflow` creates a two-step workflow:
   - `s1`: `reasoning_step` — generates the plan from `user_message`
   - `s2`: `artifact_step` — writes the plan to workspace

2. `WorkflowEngine.start_workflow` begins execution.

3. After `s1` completes, `advance_to_next_step` runs `s2`.

4. `WorkspaceService.create_document` is called with:
   - `handle.user_id = "demo_user"`
   - `handle.workspace_id = "demo_project"`
   - `relative_path = "outputs/plan.md"`

5. `WorkspaceService._write_artifact` resolves the path under:
   ```
   workspace/demo_user/demo_project/outputs/plan.md
   ```
   and enforces that the path cannot escape the sandbox root.

6. `EventEmitter.emit(EventType.WORKSPACE_ARTIFACT_WRITTEN, payload)` is called.

7. `infer_audit_event` converts the trace event into an `AuditEvent`:
   ```
   action = "workspace_artifact_write"
   outcome = "create"
   details = {workspace_id, user_id, path, size, trace_id, ...}
   ```

### Expected response

```json
{
  "ok": true,
  "run": {
    "workflow_run_id": "wf_run_...",
    "status": "completed",
    "steps": [
      {"step_id": "s1", "status": "succeeded"},
      {"step_id": "s2", "status": "succeeded"}
    ]
  },
  "artifact_path": "outputs/plan.md",
  "workspace_id": "demo_project",
  "user_id": "demo_user"
}
```

---

## Step 3 — Verify the artifact on disk

```bash
# Windows
type "workspace\demo_user\demo_project\outputs\plan.md"

# macOS / Linux
cat workspace/demo_user/demo_project/outputs/plan.md
```

The file should contain the generated plan.

---

## Step 4 — Query the security audit report

```bash
curl "http://127.0.0.1:8000/api/security/audit/report?user_id=demo_user&limit=20"
```

### Expected response (excerpt)

```json
{
  "generated_at": "2026-03-15T...",
  "user_id": "demo_user",
  "summary": {
    "namespace_violations": 0,
    "side_effect_tool_events": 0,
    "workspace_blocked_events": 0,
    "secret_access_events": 0
  },
  "violations": [],
  "workspace_blocks": [],
  "side_effect_tools": []
}
```

> This is the "clean run" report. The audit is most interesting when you trigger a security violation — see below.

---

## Step 5 — Trigger a cross-user access attempt (optional)

This shows the security enforcement in action.

```bash
curl -X POST http://127.0.0.1:8000/api/workflows/plan_and_save \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "Steal the demo_user workspace",
    "session_id": "s_attacker",
    "workspace_id": "demo_project",
    "user_id": "demo_user",
    "requester_user_id": "attacker"
  }'
```

If `requester_user_id` does not match `handle.user_id`, `WorkspaceService._assert_owner` fires:
- Emits `EventType.SECURITY_BOUNDARY_VIOLATION`
- Raises `WorkspaceSandboxError("forbidden workspace access")`
- The violation is captured as an `AuditEvent(action="namespace_violation_attempt")`

Re-run the audit query — you will now see:

```json
{
  "summary": {
    "namespace_violations": 1,
    ...
  },
  "violations": [
    {
      "action": "namespace_violation_attempt",
      "outcome": "blocked",
      "details": {
        "namespace": "workspace",
        "owner_user_id": "demo_user",
        "requester_user_id": "attacker",
        "reason": "cross_user_workspace_access",
        ...
      }
    }
  ]
}
```

---

## How this compares to a standard agent framework

| Capability | Standard framework | Promethea |
|---|---|---|
| Tool writes files | ✅ anywhere on disk | ✅ sandboxed under user/workspace root only |
| Path escape attempted | Silent success | `WorkspaceSandboxError` thrown |
| Cross-user access | No enforcement | Blocked + audit event emitted |
| Audit trail | None | Queryable via `/api/security/audit/report` |
| Artifact snapshots | No | `snapshot_artifact` creates versioned copy |
| Workflow checkpoint | No | Captured after every step |

---

## Code pointers

| Behaviour | File | Key function |
|---|---|---|
| Workflow execution | `gateway/workflow_engine.py` | `WorkflowEngine.advance_to_next_step` |
| Artifact write | `gateway/workspace_service.py` | `WorkspaceService._write_artifact` |
| Path sandbox | `gateway/workspace_service.py` | `WorkspaceService._resolve_under_root` |
| Cross-user block | `gateway/workspace_service.py` | `WorkspaceService._assert_owner` |
| Audit inference | `gateway/observability/audit.py` | `infer_audit_event` |
| Audit report | `gateway/security/audit.py` | `SecurityAuditService.build_report` |
| HTTP endpoint | `gateway/http/routes/security.py` | `GET /api/security/audit/report` |
