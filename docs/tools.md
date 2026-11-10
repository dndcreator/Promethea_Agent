# Tool Catalog

This page lists the toolbox shipped as the `standard` manifest package. All tools, regardless of author, use the same discovery, Registry and CapabilityService execution path.

If your question is "what can the agent do out of the box", start here.

## Discovery And Capability Acquisition

Tools can declare the operations they offer in `provides`; `requiresCapability`
remains a readiness prerequisite. Both bundled and external tools use the same
Registry projection. Resolution reports declaration coverage and unavailable
candidates, but does not determine whether a whole task is feasible. Ordinary
tool IDs remain discoverable without additional annotations.

The default model context is a bounded namespace/tool-ID directory. Runtime
retains the complete definitions; it does not inject every description, readiness
record or an alphabetical batch of schemas into each request. Use
`capability_request` for a namespace/offered operation and `capability_inspect`
for exact schemas and effect/confirmation details. A wildcard request (`["*"]`)
returns the complete owner-scoped directory through existing Observation paging
when necessary. This is discovery, not authorization. Explicit skill preferences
can preload only callable definitions within the same projection budget.

When an operation has no direct provider, the Agent can inspect available
capability groups and compose existing tools. If a reusable implementation is
needed and Self Evolve is enabled, its existing create/edit/validate/publish
tools can supply one. One-off code execution need not become a plugin. Generated
commands preserve `provides`, `inputSchema` and `outputSchema`; successful
publication hot-registers them and refreshes the capability context in the same
Action loop. These are available paths, not a guarantee of model strategy quality.

Generated code remains owner-private and subject to the existing process
sandbox and approval policy; metadata cannot lower its effect level. The native
Windows runner provides partial/write isolation, not full read/network/desktop
isolation. New tools do not create external permissions or solve website access
restrictions. See the [tool authoring contract](playbooks/how-to-add-a-tool.md#offered-capabilities-and-prerequisites).

## Tool Pack Goal

The standard package covers common agent tasks without requiring custom plugin work:
- read/process web content
- inspect/write workspace files
- run controlled commands
- inspect session/runtime status
- operate workflow and memory

## Categories

### Persistent Schedules And Source Evidence

- `runtime.schedule`: persist an owner-scoped registered-tool target and trigger;
  `observe=true` requires an explicitly declared read-only observation source.
- `runtime.schedules`, `runtime.pause_schedule`, `runtime.resume_schedule`,
  `runtime.remove_schedule`: manage the current owner's schedules.
- `runtime.read_event`: page an owner-scoped retained Runtime event by ID.

See the [observation-source contract](playbooks/how-to-add-a-tool.md#persistent-observation-sources).
The existing scheduler owns collection and recovery; these are normal manifest
tools, not a new service or GitHub-specific automation loop.

### GitHub Read Adapter

The separate `agentkit/tools/github` manifest contributes `github.observe_ci` and
`github.read_ci` through that same tool runtime. The observer reports run metadata,
including success/recovery, and does not create a repair task by itself.
`github.read_ci` reads run metadata, paged jobs/steps and bounded job log text.
Signed log downloads never receive the GitHub authorization token.

For private repositories or higher request limits, put `GITHUB__TOKEN` in the
current user's `config/users/<user_id>/secrets.env`, with repository-scoped Actions
read permission. It is not copied from the operator's root environment or another
account. Public anonymous reads are supported subject to GitHub rate limits.

Example `runtime.schedule` arguments:

```json
{
  "name": "Repository CI",
  "service_name": "github",
  "tool_name": "observe_ci",
  "args": {"repository": "owner/project", "branch": "develop"},
  "interval_seconds": 300,
  "observe": true
}
```

The first observation covers the latest five matching runs, not historical
backfill. Later polls paginate new runs, track unfinished runs across restarts
and include recent completed runs so rerun/recovery changes are visible. Catch-up
beyond ten pages or more than 100 active runs fails without advancing the cursor;
narrow the scope or perform explicit backfill. Reruns of old completed runs outside
the retained recent window are not guaranteed by polling; a future webhook input
may complement this adapter without changing the cognition/execution path.
This release does not enable GitHub mutation, pushing, PR creation or merging.

### Data and Text

- `data.csv_to_json`
- `data.json_to_csv`
- `math.calculate`
- `text.word_stats`
- `text.find_matches`
- `text.normalize_json`
- `utils.now`
- `utils.uuid`
- `utils.hash_text`

### Code and Archive

- `code.run_python`
- `archive.zip_create`
- `archive.zip_list`
- `archive.zip_extract`

### Web

- `web.fetch_text`
- `web.fetch_json`
- `web.search`
- `web.extract_links`
- `web.download_to_workspace`

`web.search` is provider-backed. The tool name stays stable while
`SEARCH__PROVIDER` selects the runtime backend (`auto`, `brave`, `tavily`,
`serpapi`, `searxng`, or `duckduckgo`). `SEARCH__PROVIDER_ORDER` controls
preference and `SEARCH__FALLBACK_POLICY` selects strict execution or observable
fallback. Provider keys and URLs live in `.env` or the current user's
`config/users/<user_id>/secrets.env`.

This is intentionally a two-layer design:

- `CapabilityService` registers and audits one tool: `web.search`.
- `WebSearchRuntime` registers and selects providers inside that tool.
- Provider failures use stable codes and cancellation propagates through the
  asynchronous search path.
- Bounded source metadata is persisted with tool lifecycle events for replay.

The main model only selects `web.search`; it does not need to know whether Brave,
Tavily, SerpAPI, SearXNG, or DuckDuckGo will serve the request. Provider choice
is owned by the search runtime.

`web.fetch_text` and `content_tools.web_fetch` share a bounded asynchronous HTTP
reader and [Trafilatura](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
article extraction. HTML is not returned as purported article text. Plain text
remains plain text; unsupported binary formats fail explicitly, and empty or
JavaScript-only extraction returns `read_status=empty` for the Agent to investigate
using existing browser/document capabilities. These tools do not bypass login,
CAPTCHAs or paywalls. Raw `web.download_to_workspace` retains its download semantics.

Page results contain the requested/final URL, document title, UTC Unix retrieval
time, extraction/truncation status and a fingerprint of the text actually returned.
The existing Action Observation retains the full bounded result; tool lifecycle
metadata retains the source identity and a small preview, not another full-body
store. Search snippets are explicitly separate from page reads. A retrieved page
is evidence of what was fetched, not proof that its claims are true. Runtime audit
retention remains bounded; this is not a permanent research archive or automatic
citation-correctness verifier. Use the normal workspace document tool to retain
research permanently when requested.

HTTP reads cap decompressed response size, enforce timeouts, preserve cancellation
and recheck sandbox policy on redirects and resolved DNS addresses. For a local
SearXNG service, use the operator-scoped endpoint setting in
[Configuration](configuration.md#sensitive-section-web-search-provider-env--secretsenv).

### Personal Accounts

- `mail.search`, `mail.read`, `mail.send`
- `calendar.list`, `calendar.search`, `calendar.read`, `calendar.create`, `calendar.delete`

These tools use authenticated user-scoped account settings. Reads are read-only;
sending and calendar mutations require exact Runtime confirmation. Missing
accounts/dependencies are visible in the ordinary capability catalog. The
`travel_booking` skill composes current provider/browser tools; it is not a new
booking protocol. See [setup and boundaries](playbooks/personal-assistant.md).

### Runtime and Session

- `runtime.exec_command`
- `runtime.read_env`
- `runtime.services`
- `runtime.processing_stats`
- `runtime.list_tools`
- `session.recent_messages`
- `session.info`
- `session.list`

`workspace.*`, `code.run_python`, and `runtime.exec_command` use the same
user/session workspace. An agent can write a program, execute it, inspect the
command output and generated files, then revise and rerun it. Command `cwd`
may select a directory inside that workspace, but cannot escape it. The caller
identity comes from the trusted tool invocation context, not model-supplied
`user_id` arguments. Command and code execution require confirmation by default,
then run through the platform sandbox described in
[Configuration](configuration.md). On Windows this executes native commands
with restricted file-write permissions; desktop input remains a separate host
capability.

### Workspace

- `workspace.copy_file`
- `workspace.delete_file`
- `workspace.ensure_dir`
- `workspace.file_info`
- `workspace.glob_files`
- `workspace.list_files`
- `workspace.move_file`
- `workspace.read_file`
- `workspace.read_files`
- `workspace.diff_file`
- `workspace.apply_patch`
- `workspace.replace_text`
- `workspace.search_text`
- `workspace.tail_file`
- `workspace.write_file`

### Memory

- `memory.get_context`
- `memory.list_entries`
- `memory.create_entry`
- `memory.summarize_session`
- `memory.recall_runs`

### Workflow

- `workflow.define`
- `workflow.list`
- `workflow.start`
- `workflow.status`
- `workflow.list_runs`
- `workflow.pause`
- `workflow.resume`
- `workflow.retry_step`
- `workflow.approve_step`
- `workflow.checkpoints`

## Registration Rules

All tool packages are discovered from `agent-manifest.json`. The standard
package declares a `create_tools(runtime)` factory in
`agentkit/tools/standard/agent-manifest.json`, exactly as installed packages can.
Factories return native tool instances; the loader validates their metadata and
registers them in the shared ToolRegistry. There is no official-only registrar.
See [How To Add A Tool](playbooks/how-to-add-a-tool.md).

Some tools are conditionally registered:
- memory tools require `memory_service`
- workflow/runtime status tools require `gateway_server`
- workspace tools require `workspace_service`

This means tool visibility reflects actual runtime wiring.

## How to Inspect at Runtime

### HTTP

```bash
curl http://127.0.0.1:8000/api/status/tools
```

### CLI

```bash
promethea status tools
```

## Side-effect and Policy Reminder

Not all tools are equal risk.
- read-only tools are usually callable by default
- tool manifests and local registrations declare a structured side-effect level
- external writes and privileged host actions require confirmation by default

`CapabilityService`, `ToolRegistry`, and `ToolPolicy` are the runtime authority for
that decision. The model cannot grant approval through tool arguments.

### Workspace Media

Install the optional codec support with `pip install ".[media]"`. No system
FFmpeg executable or shell approval is needed for `video.inspect` (duration,
streams and first-frame decode), `video.frame` (visual frame at a timestamp),
or `video.edit` (ordered trim and join to a new H.264 MP4). All times are in
milliseconds. The first edit format is silent video; output does not overwrite
existing files. Inputs are local MP4, MOV, WebM or MKV under the owned workspace.
Edits accept up to 12 segments and 120 seconds of output. `image.view` reads a
workspace image or screenshot into the existing multimodal model route. Frame
and screenshot understanding requires a configured vision-capable model.

For browser capture, install the recording component with
`python -m playwright install ffmpeg`. Use `record_start` on an allowed URL,
then `record_snapshot` or `record_screenshot` to observe that isolated tab.
`record_click` and `record_press` retain external interaction approval;
`record_press` accepts up to 32 explicit keys in one approved call. Action times
are approximate offsets from capture start; use `video.frame` to verify exact
edit points. `record_stop` closes the isolated context and returns the finalized
WebM path. The recorder stops at its time limit, never attaches to the desktop,
and does not share normal tabs or their browser credentials. It does not capture
audio.

### Browser Observation And Account Boundaries

`computer_control.browser_action` uses the same registry and policy path as other
tools. `snapshot` reports main-document controls and bounded embedded-frame
metadata; an empty control list does not prove that a page has no embedded UI.
Frame contents are not included or inspected automatically.

For a static HTML artifact, use `browser_action(action="preview", path="app/index.html")`.
Use the same action with `operation` set to `snapshot`, `click`, `fill`, `press`,
`reload`, or `close`. Use selectors from the preview snapshot. Runtime reads the
entry file and supported static assets from the trusted workspace and serves them
inside a separate browser context without opening a port. No normal tabs,
credential store, `file://` access, or private-network exception is granted.
The preview blocks outbound web requests; it is not an OS process sandbox.
Local storage survives a reload of the same preview but is discarded when the
preview closes or changes to a different app. This verifies browser behavior,
not persistence after closing the preview.

Browser observations report connection state, launch mode and active/open tab
IDs. Headed mode does not certify that the user saw the window. Closed pages are
removed and the active handle falls back to a surviving page. If no page remains,
reads fail without reopening; `new_tab` is an explicit operation. New-tab replies
report whether that tab is active; use `switch_tab` when necessary. A generated
credential reference proves storage only, not successful registration or login.

Screenshot tool replies contain a validated PNG `image_path` under the trusted
workspace, not Base64 text or an inferred visual description. The image remains
available as a file. Set `include_image=true` on `screenshot` or
`record_screenshot` to also send pixels via the standard visual observation
path for the next model decision. This requires a vision-capable model; the
default remains file-only. Raw controller images remain available to existing
OCR code.

Form observations omit field values and ordinary fills do not echo their text.
`create_credential` generates a password for the current HTTPS origin inside
Runtime. Its output is an opaque `credential_ref`, origin and username, never the
password. `list_credentials` lists the same metadata for the current owner;
`fill_credential(selector, credential_ref)` checks owner, exact origin and password
field type, and remains an external-write operation requiring normal approval.
Plaintext password fills are rejected. Retain account metadata/references in
normal Agent state, not secret values in prompts or Memory.

Windows uses DPAPI in the current OS-user context with owner/reference binding.
Browser cookies and local storage for owner-scoped workspaces are encrypted in
the same protected store; successful browser operations attempt a durable save.
Persistence failure after an operation is reported without pretending the
operation did not occur. Anonymous/unscoped browsers remain ephemeral. Platforms
without this protected-storage implementation cannot generate or fill managed
credentials and do not silently fall back to plaintext authentication files.
Existing workspace `browser_state.json` files are left untouched and not
automatically trusted/imported. Passwords and browser authentication are not
portable personal-space data; DPAPI records require their original OS context.

Protected credential profiles disable arbitrary `evaluate`. Creating/filling
credentials after arbitrary script execution is refused; start a clean context.
Fixed DOM snapshot/content operations remain available, and screenshots mask
password fields. This does not isolate secrets from trusted Python extensions,
approved host code, administrators, or the destination website. Keep privileged
command approval and sandbox boundaries intact. Do not reuse personal browser
profiles. Site challenges require human handling, never automated bypass.
Email-code handoff does not grant mailbox access.

### Waiting For Human Input

The canonical `await_user` action requests a non-secret text reply or human
acknowledgement. Runtime persists `waiting_input` before publishing the request;
it is nonterminal and performs no model polling. Session detail exposes only
`pending_input`; internal messages, native wire history and checkpoints remain
private. Chat replies use the existing `message` plus `reply_to_input` request ID.
The UI binds this field automatically. Clients must refresh a stale request
rather than assuming a reply addresses the newest question.

Task-backed waits use the existing TaskRuntime lifecycle. Resume an
acknowledgement through the ordinary Task resume command, or supply
`input_reply={request_id,content}` for text input. Neither operation approves a
tool, proves that a website operation succeeded, nor resolves a Goal Gap by
itself. The model receives the user's report as an explicit unverified
Observation and can inspect the environment before deciding what to do next.

## Example: General Task Pattern

For tasks like "search internet and write local report", a typical internal sequence is:
1. `web.search` or `web.fetch_text`
2. summarize/transform text helpers
3. `workspace.write_file`
4. optional `workflow.*` for resumable execution

This is the baseline toolbox for general-purpose agent behavior.
