# Self Evolve

Self Evolve authors isolated artifacts, not changes to Promethea Core. It uses
the existing CapabilityService, permission checks, process sandbox, and Action
loop. Model errors are returned as observations for the same agent to repair;
there is no parallel code-generation agent or hidden retry loop.

## Artifact Kinds

- A **tool package** exports `tool.py:handle(command, args)`, declares smoke-test
  arguments, and optionally declares `expected_result`. Publication creates an
  immutable version and hot-registers it through the existing ToolRegistry.
- A **canvas application** contains a static HTML entrypoint, scripts/styles, and
  declared browser tests. It runs independently inside the existing Canvas shell.
  It is an artifact, not a new tool protocol or a replacement for the main UI.
  Publication stores an immutable artifact without registering fake tool commands.

Canvas applications are limited to 32 artifact files and 1 MB. Dependency folders,
Python caches, and local environment metadata do not enter the package. Prefer a
self-contained HTML file with plain JavaScript/CSS; TypeScript/React source must
first be built into browser-consumable artifacts. Authenticated opaque-origin
previews are not a general replacement for arbitrary websites or development servers.

## Authoring And Repair

1. `evolve_create_task`: record the goal and acceptance criteria; select a tool
   package through `commands`, or an application through `canvas`.
2. `evolve_collect_context`, `evolve_search`, `evolve_read_file`: inspect bounded
   task-local context, file hashes, and line-numbered source.
3. `evolve_write_file`, `evolve_patch_file`, `evolve_delete_file`: edit staging
   only. Exact patches and deletion require the inspected SHA-256. Full writes
   optionally accept `expected_sha256`; stale edits fail instead of overwriting.
4. `evolve_review`, `evolve_restore`: inspect diffs and restore automatic
   checkpoints. Keep the latest 20 checkpoints per task. Restoring creates a new
   revision and invalidates validation; published versions remain immutable.
5. `evolve_run_check`: run a declared argv such as a build, test, or linter through
   the existing OS process sandbox. Return exit status and bounded output. A
   command exit code alone never marks the artifact validated.
6. `evolve_validate`: check structure, parse Python modules, run declared tool
   examples with optional expected-result assertions, or run real browser
   interactions. Browser page errors and failed assertions block publication.
   Return diagnostics, test steps, and a screenshot path for inspection.
7. Repair the identified cause and validate again. `evolve_publish` and
   `evolve_open_canvas` require a passing validation digest matching the current
   files. Changes during validation or publication are rejected.

The engineering mechanisms borrow checkpoints/review from
[Cursor](https://docs.cursor.com/en/agent/chat/checkpoints) and verification-driven
iteration from [Claude Code](https://code.claude.com/docs/en/best-practices).
They do not make an incapable model reliable by themselves: model-written tests
may be incomplete, and passing declared checks does not prove every natural-language
acceptance criterion. Reports distinguish actual verification from these limits.

## Canvas Example

### Component Documents

For simple interfaces, call `evolve_get_canvas_schema` to inspect the generated
`canvas.ui.v1` grammar, create a normal canvas task with declared browser tests,
then call `evolve_compose_canvas(task_id, document, expected_sha256?)`. The
renderer supplies layout, text, inputs, checkboxes, selects, buttons, and tables.
Buttons can assign, increment, toggle, reset, or calculate using declared scalar
state. Components cannot contain arbitrary event handlers or execute tools.

```json
{
  "version": "canvas.ui.v1",
  "title": "Counter",
  "initial_state": {"count": 0},
  "root": {"type": "stack", "id": "counter", "children": [
    {"type": "text", "id": "count", "bind": "count"},
    {"type": "button", "id": "add", "label": "Add", "actions": [
      {"op": "increment", "field": "count", "value": 1}
    ]}
  ]}
}
```

Use `#count` and `#add` in this example's browser tests. Composition uses the
same owned staging writer, checkpoints, digest validation and deployment as
custom applications. It never marks a task validated automatically. The full
schema is also generated through the existing public-contract generator.
See [Intelligent Canvas](../../../docs/architecture/intelligent-canvas.md).

### Custom Applications

```json
{
  "goal": "Make an editable counter",
  "capability_id": "counter",
  "version": "1.0.0",
  "description": "Counter",
  "canvas": {
    "entrypoint": "index.html",
    "tests": [
      {"action": "click", "selector": "#add"},
      {"action": "expect_text", "selector": "output", "value": "1"}
    ]
  }
}
```

Write the files, validate, then call `evolve_open_canvas(task_id)` for a
session-scoped application, or set `reusable=true` to place a copy in the user's
`_canvas_library` workspace. Session applications remain in their conversation
workspace until discarded; they are not automatically promoted to the library.
The shell's bookmark action also retains a copy, including its current app data.
Deleting a generated app removes only its owned `.canvas_apps/<environment_id>`
directory, never an arbitrary registered project root.

Applications can use local JavaScript without contacting the agent. For durable
application data, the shell injects a small bridge before application scripts:

```javascript
let state = await window.promethea.getState()
state = await window.promethea.setState({ count: 1 }, state.revision)
```

State is a JSON object up to 256 KB. Saves use optimistic revisions so stale
clients cannot silently overwrite newer data. Code edits change the preview
fingerprint; data saves do not reload the frame or clear unsaved form input.
Runtime errors appear in the shell and the environment's diagnostics for repair.
Retained applications and data are included in personal workspace archives.
Import restores static artifacts only; it does not resume host processes.

## Security And Setup

Enable the existing `self_evolve.enabled` setting to expose authoring tools.
Process checks retain normal approval and sandbox requirements. The iframe has
an opaque origin and receives neither host credentials nor arbitrary Runtime
execution access. Its bridge supports app-state reads/writes and bounded error
reports only. Static previews block fetch/WebSocket connections through CSP;
browser verification also blocks undeclared network requests and WebSockets.

Install the existing browser dependency:

```bash
python -m playwright install chromium
```

Alternatively configure `SELF_EVOLVE__BROWSER_CHANNEL=msedge`
or another supported installed Playwright channel through the existing env/config
mechanism. Verification keeps Chromium's sandbox enabled; a missing browser or
failed launch is a failed check, never an automatic pass or sandbox bypass.
