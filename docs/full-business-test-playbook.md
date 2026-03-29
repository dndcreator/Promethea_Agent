# Full Business Test Playbook (Release Audit)

Date: 2026-03-29

This playbook is for release-level validation under real business scenarios.

## Goal

Validate that the product is not only feature-complete on paper, but callable and reliable on the real runtime path:
- protocol layer
- reasoning + workflow loop
- tools and policy
- memory lifecycle
- config and readiness endpoints
- UI/CLI/API parity

## Preflight (must pass)

1. `GET /health`
2. `GET /api/status`
3. `GET /api/status/services`
4. `GET /api/ops/readiness`
5. `GET /api/doctor`

If readiness is `no-go`, stop and fix dependencies first.

## Automated Test Suites

Use the new grouped runner:

```powershell
python tests/run_all_tests.py --suite smoke
python tests/run_all_tests.py --suite core
python tests/run_all_tests.py --suite contracts
python tests/run_all_tests.py --suite business
```

Or one-step business audit with logs:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite business
```

## Manual Business Journeys (must execute)

### Journey 1: Chat -> Tool confirmation -> Resume

Expected:
- chat returns `needs_confirmation`
- approve call succeeds
- follow-up response references actual result/artifact

### Journey 2: Tool discovery -> Callability -> Execute

Expected:
- `/api/tools` and `/api/status/tools` expose callable catalog
- `callable_now` and `requires_confirmation` are meaningful
- tool call returns normalized result/error shape

### Journey 3: Reasoning complex task closed loop

Prompt style example:
- "搜索互联网资料并输出到 workspace 报告"

Expected runtime behavior:
- complexity gate triggers reasoning path
- reasoning enters ReAct/ToT loops
- tool action executed through workflow bridge when enabled
- observation fed back to reasoning and used in final answer

### Journey 4: Workflow resumability and artifacts

Expected:
- define/start/status/pause/resume/retry/approve are callable
- checkpoints are visible
- artifacts exist in workspace and match expected content

### Journey 5: Memory lifecycle

Expected:
- memory recall routes respond
- write gate decisions visible
- recall inspect and runs endpoints return explainable metadata

## Go/No-Go Criteria

`GO` only when:
- smoke + core + contracts + business suites pass
- no critical service failed in readiness
- manual journeys pass without silent failure
- API/CLI/UI can all trigger same backend capability surface

`NO-GO` when:
- health/readiness says critical failure
- any core journey requires hidden manual patch to complete
- contracts drift between discovery endpoints and actual handlers

## Reporting Template

For each failed case, report:
- case id
- expected behavior
- actual behavior
- trace_id/request_id
- root cause hypothesis
- fix status (done/pending)
