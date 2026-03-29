# Quickstart

## Prerequisites

- Python 3.10+
- API key for your model provider

## Install

```bash
pip install -r requirements.txt
```

## Configure

Set env variables (example):

```bash
API__API_KEY=your_key
API__BASE_URL=https://openrouter.ai/api/v1
API__MODEL=openai/gpt-4.1-mini
```

## Run

```bash
python start_gateway_service.py
```

## Validate

- `GET /health`
- `GET /api/status`
- `GET /api/ops/readiness`

If these fail, go to [Operations / Release Readiness](../operations/release-readiness.md).
