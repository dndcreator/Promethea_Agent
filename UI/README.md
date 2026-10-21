# Web UI Module

`UI` contains the Vite/React Web UI for Promethea.

## Responsibilities

- authentication and first-run setup surface
- chat console, persistent project grouping, and session navigation
- Agent Workbench and runtime monitoring
- Cognition/Memory Workbench and write-review controls
- separate task monitoring and workflow management; settings, files, search, avatar, and diagnostics pages

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

The shell has an icon rail, a collapsible project/conversation sidebar, a central feature surface, and one responsive Workbench. The chat stays mounted across feature navigation. A shared `WorkbenchProvider` consumes one SDK stream per scope; monitoring a separate Task opens a distinct task-scoped subscription without replacing the current conversation. Memory notices read that same conversation projection even when the Workbench is closed.

Projects are owner-scoped conversation groups stored by the Gateway, not execution workspaces or directories. Deleting a group only removes memberships. Project metadata travels with personal workspace archives and session-bearing legacy bundles.

The UI talks to the gateway HTTP API. Shared fetch/auth behavior lives in `UI/src/services/api.ts`; feature components should use that helper instead of duplicating token or base-url handling.

Primary backend docs:

- [docs/ui-overview.md](../docs/ui-overview.md)
- [docs/api-reference.md](../docs/api-reference.md)
- [docs/runtime-overview.md](../docs/runtime-overview.md)

Conversation links are parsed with Markdown source positions, without rendering raw HTML or loading remote images. HTTP(S) links open independently; same-origin `/api/workbench/artifact?workspace_id=...&path=...` links use the authenticated SDK. Active HTML/SVG artifacts download rather than execute in a preview tab. Follow-up anchors use Python-compatible Unicode offsets, with read compatibility for older UTF-16 annotations.

## Commands

```bash
npm run build
npm run lint
npm test
npm run dev
```

The root `start_gateway_service.py` script can start both backend and Web UI for local development.

The focused Node tests use native TypeScript stripping (Node 22.6+). Real-browser link regressions live in `tests/test_message_links_browser.py`; set `CANVAS_TEST_BROWSER_CHANNEL=msedge` and run them with the UI dev server available (`PROMETHEA_UI_TEST_URL` overrides its URL).

Production-shell browser regressions are in `tests/test_frontend_workspace_browser.py` and `tests/test_frontend_cognition_browser.py`. They intercept public APIs with synthetic data and do not require a running Python backend or model credentials. Screenshots are written under ignored `.tmp/frontend-qa/`.

`tests/test_frontend_feature_flows_browser.py` covers exact file-search navigation, upload retries, settings-load recovery, plugin updates, workspace-replacement confirmation, and closing an in-flight sign-in. Files display only previews provided by the existing API; they do not imply full-document editing or a download endpoint. Restoring a personal workspace refreshes configuration and resets old execution views while preserving the operation receipt.
