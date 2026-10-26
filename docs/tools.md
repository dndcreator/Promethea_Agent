# Tool Catalog

This page lists the toolbox shipped as the `standard` manifest package. All tools, regardless of author, use the same discovery, Registry and CapabilityService execution path.

If your question is "what can the agent do out of the box", start here.

## Tool Pack Goal

The standard package covers common agent tasks without requiring custom plugin work:
- read/process web content
- inspect/write workspace files
- run controlled commands
- inspect session/runtime status
- operate workflow and memory

## Categories

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

## Example: General Task Pattern

For tasks like "search internet and write local report", a typical internal sequence is:
1. `web.search` or `web.fetch_text`
2. summarize/transform text helpers
3. `workspace.write_file`
4. optional `workflow.*` for resumable execution

This is the baseline toolbox for general-purpose agent behavior.
