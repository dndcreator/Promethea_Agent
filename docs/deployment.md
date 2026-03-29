# Deployment Guide

This guide provides production-oriented deployment baseline for Promethea.

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

## 4. Start Procedure

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Prepare `.env` from `example.env`.

3. Start service:

```bash
python start_gateway_service.py
```

4. Verify readiness:

- `GET /api/health`
- `GET /api/status`
- `GET /api/ops/readiness`

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
- For incident triage, use:
  - `/api/ops/runbook`
  - `/api/ops/framework-check`
  - `/api/doctor`
