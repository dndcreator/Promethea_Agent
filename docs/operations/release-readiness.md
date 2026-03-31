# Release Readiness

A release candidate is `GO` only if all conditions pass:

1. `/api/ops/readiness` has no critical service failure
2. `/api/doctor` has no critical recommendation unresolved
3. business suites pass (`smoke/core/contracts/business`)
4. manual journeys pass (chat-confirm, tools, workflow, memory, voice)

## Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite smoke
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite core
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite contracts
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite business
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
- unresolved known-risk list (if any)
