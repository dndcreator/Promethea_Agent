# Quickstart

This page is the shortest successful path.
If you want the full hand-holding version, use [Real User Setup](./real-user-setup.md).

## Prerequisites

- Python 3.10+
- Node.js / npm for the Web UI
- Neo4j for the full graph-memory path
- one valid model provider key

## Install

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Configure

1. Copy template:

```bash
cp env.example .env
```

2. Fill minimum required fields in `.env`:

```bash
API__API_KEY=your_key
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=openai/gpt-4.1-mini
```

These three are a set: if one points to another provider, requests will fail.

## Run

```bash
python start_gateway_service.py
```

## Validate

- `GET /health`
- `GET /api/status`
- `GET /api/health/memory`
- `GET /api/ops/readiness`

If these fail, run `promethea doctor run` or open [Release Notes](../../RELEASE_NOTES.md) for current preview limitations.
