# Release Readiness

A release candidate is `GO` only if all conditions pass:

1. `/api/ops/readiness` has no critical service failure
2. `/api/doctor` has no critical recommendation unresolved
3. business suites pass (`smoke/core/contracts/business`)
4. release-focused regressions pass (`files`, `chat attachment`, `config org_brain`)
5. frontend build passes in a local Node environment
6. manual journeys pass (chat-confirm, file attachment, global search, tools, workflow, memory, voice)
7. enterprise feature visibility matches `org_brain.enabled`

## Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite smoke
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite core
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite contracts
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite business
```

Targeted regression checks for recent UI/API changes:

```powershell
python -m pytest tests/test_files_routes.py tests/test_chat_routes_args_resilience.py tests/test_config_routes_contract.py -q
```

Frontend build check:

```powershell
cd UI
npm run build
```

One-shot preflight gate (recommended for real-machine validation):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_release_preflight.ps1
```

The script checks endpoint health (`/api/health`, `/api/status`, `/api/ops/*`, `/api/doctor`), runs suites, and writes a timestamped report to `logs/release-preflight/`.

## Recommended Evidence Bundle

- readiness JSON
- doctor JSON
- suite logs in `logs/test-audit/`
- frontend build output
- targeted regression output for file attachments and enterprise config
- unresolved known-risk list (if any)
