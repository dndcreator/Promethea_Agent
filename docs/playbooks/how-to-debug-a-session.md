# Playbook: How to Debug a Session

This guide explains how to investigate a session where something went wrong:  
wrong memory recalled, tool not invoked, response not what you expected, security violation triggered.

---

## 1. Get the trace_id

Every request generates a `trace_id`. It is returned in:

- The HTTP response headers: `X-Trace-Id`
- The response JSON body: `meta.trace_id`
- Every event in the event bus

If you don't have it, check the session log:

```bash
curl "http://127.0.0.1:8000/api/sessions/{session_id}"
```

---

## 2. Read the audit events for a user

```bash
curl "http://127.0.0.1:8000/api/security/audit/events?user_id=u1&limit=50"
```

Returns raw `AuditEvent` objects in chronological order.  
Useful for: namespace violations, workspace blocked events, secret access.

---

## 3. Read the security audit report

```bash
curl "http://127.0.0.1:8000/api/security/audit/report?user_id=u1"
```

Returns a structured summary:

```json
{
  "summary": {
    "namespace_violations": 2,
    "side_effect_tool_events": 1,
    "workspace_blocked_events": 0
  },
  "violations": [...],
  "side_effect_tools": [...]
}
```

---

## 4. Inspect memory recall for a session

```bash
curl "http://127.0.0.1:8000/api/memory/recall/runs?session_id=s1&limit=10"
```

Returns the recall run history. Each run includes:
- `selected_items`: what was recalled and why
- `dropped_candidates`: what was considered but dropped and why
- `strategy`: fast / deep / workflow
- `filter_reasons`: which filters triggered

This is the primary tool for "the agent forgot something it should have remembered."

---

## 5. Inspect a single recall run

```bash
curl "http://127.0.0.1:8000/api/memory/recall/run/{run_id}"
```

---

## 6. Check MCP service health

If a tool invocation failed with a connection error:

```bash
curl "http://127.0.0.1:8000/api/mcp/services"
```

Returns service health: `online`, `offline`, `degraded`, last sync time, last error.

---

## 7. Check config deprecation warnings

If something behaves unexpectedly due to a config mismatch:

```bash
curl "http://127.0.0.1:8000/api/config/runtime/scoped?scope=api"
```

Check the response for `deprecation_warnings`.

---

## 8. Common issues and where to look

### "The agent used the wrong memory"

1. `GET /api/memory/recall/runs?session_id=...` — what was recalled?
2. Check `dropped_candidates` — was the correct memory dropped by the filter?
3. Check `MemoryWriteGate` decisions — was the memory ever written? Filter the audit events for `memory.write.decided`.

### "The tool was not called"

1. Check `GET /api/tools/list` — is the tool registered?
2. Check tool policy: `GET /api/config/tool-policy?user_id=...`
3. Look at `TOOL_CALL_ERROR` events in the audit log — did a policy check block it?
4. If MCP tool: check `GET /api/mcp/services` — is the service online?

### "I got a security violation I didn't expect"

1. `GET /api/security/audit/events?user_id=...` — find the violation event.
2. Check `details.namespace`, `details.owner_user_id`, `details.requester_user_id`.
3. Enforcement points:
   - Memory: `gateway/memory_service.py` — cross-user recall
   - Workspace: `gateway/workspace_service.py` — `_assert_owner`
   - Tools: `gateway/tool_service.py` — `_assert_tool_namespace`

### "The workflow stopped"

1. `GET /api/workflow/{run_id}/status` — current step and run status.
2. If status is `waiting_human`: call `POST /workflow/approve_step`.
3. If status is `failed`: call `POST /workflow/retry_step` with the step_id.
4. If status is `paused`: call `POST /workflow/resume`.
5. Check checkpoints: `GET /api/workflow/{run_id}/checkpoints`.

### "Config change didn't take effect"

Priority order: `.env` > `config/default.json` > code defaults.  
If you changed `config/default.json` but have the same key in `.env`, `.env` wins.

Check what the runtime actually sees:
```bash
curl "http://127.0.0.1:8000/api/config/runtime/scoped?scope=memory"
```

---

## 9. Enable debug logging

```bash
SYSTEM__LOG_LEVEL=DEBUG python start_gateway_service.py
```

All six pipeline stages emit debug-level logs with `trace_id`.

---

## 10. Enable reasoning debug log

If the agent is making unexpected planning decisions:

```bash
REASONING__DEBUG_LOG=true python start_gateway_service.py
```

Reasoning node state transitions are logged at every step.
