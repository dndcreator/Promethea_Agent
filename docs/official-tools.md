# Official Tools Pack (Runtime Built-ins)

This page documents the built-in official tools registered by runtime.

If your question is "what can the agent do out of the box", start here.

## Tool Pack Goal

The official pack should cover common agent tasks without requiring custom plugin work:
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

- `CapabilityService` registers and audits one official tool: `web.search`.
- `WebSearchRuntime` registers and selects providers inside that tool.
- Provider failures use stable codes and cancellation propagates through the
  asynchronous search path.
- Bounded source metadata is persisted with tool lifecycle events for replay.

The main model only selects `web.search`; it does not need to know whether Brave,
Tavily, SerpAPI, SearXNG, or DuckDuckGo will serve the request. Provider choice
is owned by the search runtime.

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

Official tools are registered by runtime startup through:
- `gateway/official_tools/__init__.py`
- `register_official_tools(...)`

Some tools are conditionally registered:
- memory tools require `memory_service`
- workflow/runtime status tools require `gateway_server`
- workspace tools require `workspace_service`

This means tool visibility reflects actual runtime wiring.

## How to Inspect at Runtime

### HTTP

```bash
curl http://127.0.0.1:8000/api/status/tools
curl http://127.0.0.1:8000/api/status/tools/official
```

### CLI

```bash
promethea status official-tools
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
