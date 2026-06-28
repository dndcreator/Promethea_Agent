# Web UI Module

`UI` contains the Vite/React Web UI for Promethea.

## Responsibilities

- authentication and first-run setup surface
- chat console and session navigation
- Agent Workbench and runtime monitoring
- Memory Workbench, Memory Atlas, and write-review controls
- settings, files, search, workflow, avatar, and diagnostics panels

## Layout

```text
UI/
  src/
    components/
    components/modals/
    components/avatar/
    store/
    services/
  package.json
  vite.config.ts
```

## Backend Contract

The UI talks to the gateway HTTP API. Shared fetch/auth behavior lives in `UI/src/services/api.ts`; feature components should use that helper instead of duplicating token or base-url handling.

Primary backend docs:

- [docs/ui-overview.md](../docs/ui-overview.md)
- [docs/api-reference.md](../docs/api-reference.md)
- [docs/runtime-overview.md](../docs/runtime-overview.md)

## Commands

```bash
npm run build
npm run dev
```

The root `start_gateway_service.py` script can start both backend and Web UI for local development.
