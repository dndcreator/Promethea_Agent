# Deployment Guide

This guide provides production-oriented deployment baseline for Promethea.

If your target is "new users can run it with minimal support", start from:
- [Getting Started / Real User Setup](./getting-started/real-user-setup.md)

## 1. Deployment Modes

- Local single-node (default)
  - FastAPI runtime + local UI + local storage.
- Self-hosted service mode
  - Runtime exposed to internal clients (UI/CLI/API consumers).

## 2. Prerequisites

- Python 3.10+
- Valid LLM provider credentials via environment variables
- Optional: Neo4j for full memory backend
- Optional: Tesseract OCR binary for image OCR tools (`pytesseract` is the Python wrapper)

## 3. Environment Baseline

Required minimum:

- `API__API_KEY`
- `API__BASE_URL`
- `API__MODEL`

Recommended runtime toggles:

- `MEMORY__ENABLED=true`
- `REASONING__ENABLED=true`
- `KERNEL_SCHEDULER__ENABLED=true`

## 4. Start Procedure

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Prepare `.env` from `env.example`.
   - Keep the provider trio coherent: `API__API_KEY`, `API__BASE_URL`, `API__MODEL`.
   - For first-time users, prefer `MEMORY__STORE_BACKEND=sqlite_graph` to reduce external dependencies.

3. Start service:

```bash
python start_gateway_service.py
```

4. Verify readiness:

- `GET /api/health`
- `GET /api/status`
- `GET /api/ops/readiness`
- `GET /api/automation/scheduler/status`

## 5. Production Checks

Before exposing service:

- Security
  - Ensure secrets are environment-managed only.
  - Validate boundary enforcement with multi-user tests.
- Reliability
  - Confirm `ops/readiness` is `go` for critical services.
  - Verify memory/tool dependency degradation behavior.
- Observability
  - Confirm trace/audit events are generated for key flows.

## 6. Upgrade / Rollback

- Read `CHANGELOG.md` before upgrade.
- Back up runtime state files and memory backend.
- Validate config compatibility via config contract and diagnostics endpoints.
- Keep previous version ready for rollback if readiness regresses.

## 7. Operational Notes

- Corrupt session snapshots are now quarantined by session storage loader.
- Kernel scheduler (local recurring task loop) controls:
  - `POST /api/automation/scheduler/run-once`
  - `POST /api/automation/scheduler/pause`
  - `POST /api/automation/scheduler/resume`
  - Optional env:
    - `KERNEL_SCHEDULER__TICK_SECONDS` (default `5.0`)
    - `KERNEL_SCHEDULER__MAX_JOBS_PER_TICK` (default `10`)
    - `KERNEL_SCHEDULER__START_PAUSED` (default `false`)
- For incident triage, use:
  - `/api/ops/runbook`
  - `/api/ops/framework-check`
  - `/api/doctor`
