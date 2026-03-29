# Full Static Scan Report (2026-03-25)

Scope:
- Full repository text/code scan on all tracked code/doc/config files under workspace.
- Total files scanned: 384
- Total lines scanned: 60,464

Method:
1. Whole-repo marker scan (`TODO/FIXME/NotImplemented/pass/bare-except/conflict markers`).
2. Security-oriented API scan (`eval/exec/subprocess/os.system/shell=True/pickle/yaml.load`).
3. Encoding and merge-marker scan.
4. JSON parse validation across repository JSON files (excluding inaccessible temp folders).
5. Manual review of all runtime-critical hits (Gateway/Tool/Reasoning/Voice/Auth/Workflow/Workspace/Session layers).

## Findings and Actions

### F1. Bare exception swallowed in MCP tool-call parsing (fixed)
- File: `agentkit/mcp/tool_call.py`
- Risk: parse failures silently discarded (`except: pass`), reducing observability.
- Action: replaced with `except Exception as e` and debug log.

### F2. Account-deletion cleanup path swallowed exceptions (fixed)
- File: `gateway/http/routes/auth.py`
- Risk: session cache cleanup errors suppressed with no trace.
- Action: added warning log with user id + error detail.

### F3. JSON validity check failed on runtime session snapshots (not code contract)
- Invalid JSON files:
  - `sessions.json`
  - `gateway/sessions.json`
- Cause: malformed persisted runtime data (broken string quoting), not schema files.
- Impact: session loader fallback returns empty map when parse fails.
- Action in this pass: no destructive rewrite of user session data.
- Recommended follow-up: add optional tolerant repair/backup flow in `gateway/http/session_store.py` to prevent full-drop on malformed snapshots.

### F4. Frontend i18n contains mojibake baseline entries (known quality debt)
- File: `UI/script.js`
- Observation: initial `I18N.zh` block has garbled strings, later corrected via `Object.assign(I18N.zh, {...})`.
- Impact: if any key is not overridden by later assign, user may see garbled copy.
- Action in this pass: documented as quality debt; behavior currently mostly masked by override layer.

## Security/Consistency Scan Summary

- Merge conflict markers (`<<<<<<<`/`>>>>>>>`): none found.
- Bare `except:` in runtime code: none remaining after fix.
- High-risk command execution path found:
  - `gateway/official_tools/command_tools.py` uses `subprocess.run(..., shell=True)`.
  - Current design is sandbox-policy gated before execution.
  - Conclusion: acceptable by design for command tool, but should remain strictly gated and audited.

## Constraints in this environment

- Python executable unavailable in current shell (`python/py/pytest` not in PATH), so parser-level compile/lint/pytest execution cannot run here.
- This report is static scan + targeted manual code review over all hit locations.

## Current Status

- Runtime critical static issues discovered in this pass: 2
- Fixed in code: 2
- Non-code/runtime-data anomalies: 2 JSON snapshot files (kept intact)
- Quality debt retained (non-blocking): frontend mojibake baseline i18n block
