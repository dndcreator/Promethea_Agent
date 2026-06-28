# Changelog

All notable changes to Promethea are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- Release-facing module documentation now includes explicit `skills/` and `UI/` README files plus clearer tool/extension/skill boundaries.
- README contact links for the project maintainer's email and X / Twitter profile.
- Curated release screenshot assets and a README preview gallery for the Web UI, Agent Workbench, Memory Atlas, and memory write review flow.
- Official `web.search` now has a provider runtime with explicit/auto selection for Brave, Tavily, SerpAPI, SearXNG, and DuckDuckGo fallback, configured through user-scoped secrets.
- Documentation now spells out the env-only search provider mechanism and the provider-runtime pattern for official tools with multiple backends.
- Release cleanup now keeps root-level personal/project side notes and tracked scratch files in ignored local history, and simplifies `.gitignore` into clear release-boundary groups.
- Workflow engine state now persists definitions, runs, and checkpoints to an atomic JSON store so workflow history can survive backend restarts.
- Successful workflow runs can now be retained as reusable workflow templates when the run or definition explicitly marks them as template candidates.
- Memory Workbench now includes a Canvas-based Memory Atlas with pan, zoom, node dragging, hover-neighborhood highlighting, focused graph search, and node detail inspection.
- Memory search APIs now expose backend-driven entry search and focused graph search via `/api/memory/search` and `/api/memory/graph/search`.
- User-scoped Agent Avatar foundation with a decoupled frontend driver registry, left-sidebar avatar surface, personalization settings panel, controlled asset APIs, and built-in image / GIF / WebM / MP4 support. VRM and Live2D remain isolated follow-up drivers rather than core UI dependencies.
- Self-evolve can now build a lightweight docs-derived runtime self model under `memory/self_model.json`, with API endpoints to read or refresh it.
- Memory Workbench pending-review tab for memory write conflicts, including confirm, ignore-once, and reduce-similar actions backed by write-proposal APIs.
- Memory write proposals now support confirming a new memory while keeping conflict candidates unchanged.
- RuntimeBlock / ContextCompiler LLM I/O layer so ConversationService can compile user text, attachments, and future module observations through one multimodal-aware path.
- Gateway-level `ActionService` with `ReActPlanner` adapter and structured action run traces for action-mode turns.
- Public-preview bilingual product homepage in `README.md`.
- `RELEASE_NOTES.md` for the current public preview release candidate.
- Release preparation record in `docs/operations/release-prep-2026-05-13.md`.
- Vite Web UI release surface with refined neuroscience-inspired visual system.
- File upload, attachment context, and global search UI/API flows.
- Workflow inspector UI for definitions, personal runs, recovery, pause/resume, and checkpoints.
- Backend-aware first-run/auth behavior for Neo4j default deployments.
- User secrets/env isolation support for per-user sensitive configuration.
- Prompt policy routing for need-based prompt block selection.
- Tool execution prompts now consume the same live registry-backed structured tool snapshot as prompt-policy routing instead of embedding static tool ids.
- Prompt-policy routing now declares a generic structured `action_intent`; runtime-dependent turns are normalized into the Observation-backed action path even if the model returns an inconsistent direct-mode decision.
- Cognitive budget routing with `direct`, `light_action`, `deep_reasoning`, and `workflow` modes.
- Explicit `L0 raw_log` memory-layer documentation and regression coverage.
- Test artifact policy that confines pytest runtime output to `.tmp/pytest-runtime/`.
- `example.env` with cloud / local / Azure model configuration examples.
- `CONTRIBUTING.md` with PR checklist and Definition of Done.
- `docs/configuration.md` - full configuration reference.
- `docs/quickstart-local-model.md` - local model setup guide.
- Unified Extension Catalog APIs: `GET /api/extensions/catalog` and `POST /api/extensions/reload`.
- Community extension drop-in folder at `extensions/community` with hot-reload documentation.
- Community manifest extensions are scanned on startup and can be refreshed at runtime from the Web UI.
- Official release tools for `code.run_python`, `archive.zip_*`, `workspace.diff_file`, and `workspace.apply_patch`.

### Changed
- Tool-authoring playbook was rewritten to remove mojibake and align with the current ToolService, ToolRegistry, policy, and provider-runtime model.
- Release-facing module READMEs were cleaned up to remove mojibake and keep concise technical descriptions.
- README now explicitly states the current public-preview status without weakening the product positioning.
- Release ignore rules now cover local brain/runtime data, memory database files, JSONL logs, and state files so personal run data stays out of public pushes.
- Public release and testing documentation now treat voice input as experimental/provider-dependent instead of a supported preview feature, clarifying that DeepSeek-only configurations do not provide STT/audio transcription.
- Agent Workbench timeline nodes now render semantic event summaries for memory recall, tool use, workflow progress, and response synthesis instead of surfacing raw backend fields as the primary display.
- Quick Start now keeps Neo4j on the main beginner path with a step-by-step Desktop setup, Browser login checklist, `.env` mapping, and first-run mistake notes; sqlite_graph remains documented only as a temporary degraded fallback.
- Public documentation now keeps a smaller release-facing index while historical audits, demos, backlogs, ADRs, and placeholder assets are kept locally under ignored `docs/_local_history/`.
- User-facing agent customization now lives in a separate prompt block for display name and interaction style, while the core Promethea identity remains non-overridable and Soul remains the long-term evolved temperament layer.
- Legacy core prompt configs are now wrapped with the full Promethea identity-layering rules unless they already contain the new non-overridable core identity contract.
- The right sidebar now acts as a current-task Agent Workbench, summarizing live task progress, tool activity, memory review pressure, workflow/recovery state, execution timeline, and task intervention without duplicating the left workspace navigation.
- Agent Workbench empty and idle states now use concise status text instead of explanatory product copy.
- Agent Workbench polling was reduced and no longer calls `/api/metrics` directly, cutting incidental runtime log noise while preserving current-task status summaries.
- Memory Atlas now offers theme, focus-neighborhood, and full-graph modes so the graph can feel like a semantic relation map by default while still preserving full exploration.
- User deletion now also cleans owned local runtime state such as user logs, workspace files, and reasoning-template artifacts instead of only removing account/config records.
- Account deletion now supports local-file user backends, purges user-owned workflow state, clears cached config, and removes the user's owned Neo4j memory/session subgraph instead of leaving orphan runtime data behind.
- Empty-chat welcome now presents the LLM-generated memory-aware greeting as one cohesive surface: clickable suggested actions remain below it, while the header shows local date and time instead of exposing internal greeting-generation state.
- Personalized welcome generation now stays deliberately understated without becoming templated: the LLM varies wording naturally, references at most one reliable continuation, and avoids turning internal memory, reasoning, or workflow state into a dashboard-style introduction.
- Personalized welcome refresh is now session-scoped: it runs on initial signed-in entry, explicit new-chat creation, or return to an idle blank conversation after three hours, rather than on sidebar toggles or incidental auth/context rerenders.
- Workspace navigation is now a ChatGPT-style overlay drawer. A compact menu button opens the full navigation, memory, workflow, operations, and recent-session panel above the workspace without consuming chat width; the adjacent Agent panel remains dedicated to the avatar, runtime status, and account identity.
- Agent panel now prioritizes full-body avatar presentation: image and video drivers use contain-fit rendering, the avatar canvas expands vertically, identity and presence move into lightweight overlays, and verbose runtime rows collapse into compact status dots.
- Agent panel model summary now reads the current user's configured `API__MODEL` from the existing sanitized secrets-status API instead of displaying the hardcoded `Runtime` placeholder.
- Agent panel model summary remains compact with an ellipsis and full-value tooltip. After removing the duplicate Memory card, Model and Queue return to a two-column row so the avatar area keeps maximum height.
- Agent panel status summary removed the duplicate Memory stat card and misleading Vector indicator. Memory health remains visible as a single status dot, while Vector is no longer implied to have an independent health check when it previously mirrored `memory_active`.
- Agent panel status dots now use the same two-column grid, spacing, and card geometry as the Model / Queue summary row for cleaner vertical alignment.
- Memory Workbench graph visualization now uses filterable `HOT` / `WARM` / `COLD` / `OTHER` swimlanes with adjustable node density, optional relationship rendering, and click-to-inspect node details instead of an always-on dense radial graph.
- Web UI visual theme now uses a neutral warm-gray workspace, deep teal interaction accents, and a sans-serif primary font stack for denser workbench readability.
- MCP startup and plugin hot reload now refresh-scan both official and community manifest roots even when the registry was pre-populated, and prompt-policy routing now receives the full structured registered-tool snapshot with availability metadata instead of a truncated text summary.
- Chat header now uses the backend session title when available instead of always showing a truncated session id.
- Memory Workbench graph view now renders a layered SVG topology from memory nodes and edges, with Neo4j marked as the semantic graph backend and SQLite graph marked as lightweight token/MEF structure.
- Empty chat now asks the backend LLM for a short dynamic agent opening with editable suggested actions, falling back locally only when the model call is unavailable.
- Self-evolve tasks now treat `self_model` as a baseline artifact: task creation stores a snapshot and context collection includes the architecture/capability baseline before target files.
- Chat UI now uses a multiline composer, lets users scroll away from streaming output without being forced to the bottom, and surfaces memory-review notices with a direct Memory Workbench action.
- Chat header token metrics now fall back to `/api/metrics` and support nested usage payloads instead of only reading `reasoning_meta.total_tokens`.
- Cold-layer memory summaries now follow the main conversation LLM by default when memory is configured to use the main API; `memory.cold_layer.summary_model` remains an advanced explicit override.
- The sign-in remember option is now labeled as staying signed in with a token rather than remembering or storing the password.
- Action-mode tool flow now uses a strict JSON action envelope (`tool_call` / `answer`) with one protocol correction retry, so narrated pseudo tool calls fail closed instead of being treated as executable actions.
- Raw-log checkpoint persistence now uses unique temporary files plus short PermissionError retries to avoid transient Windows file-lock failures during atomic state replacement.
- Action envelope protocol fields are stripped before tool dispatch, preventing runtime tools from receiving internal fields such as `action`.
- Action schema prompts, parsing, correction, observation continuation, and final answer handling now share one `ActionProtocol` definition across the runtime.
- ReAct replan prompts now ask the existing reasoning loop to perform lightweight strategy reflection before choosing `tool`, `think`, `memory`, or `done`, avoiding blind retries without replacing the ReAct state machine.
- Reasoning now carries a global budget ledger for elapsed runtime, total ReAct rounds, and low-yield tool failures, so the existing ReAct loop can switch toward synthesis before long multi-node runs become excessive.
- Reasoning budget accounting and completed-tree history persistence were split into focused gateway modules, keeping ReAct behavior intact while reducing `ReasoningService` coupling.
- Reasoning policy resolution, tree mutation/serialization, debug snapshots, and tool-runtime helper logic were split into focused modules while preserving the existing ReAct execution flow.
- Deep reasoning summaries and prompt blocks now preserve enough substance for final answer synthesis, including evidence limits, tradeoffs, risks, and practical next steps instead of over-compressing complex results.
- Action-mode protocol guidance now explicitly prevents leaking internal JSON/action-schema corrections into user-facing answers.
- Web UI reasoning sidebar now exposes a session-scoped trace history list so users can reopen recent completed reasoning trees without losing the live trace view.
- Action-mode turns now inject a generic action contract before entering the existing ReAct/tool-call loop, requiring executable JSON tool calls instead of narrated tool usage when tools can advance the goal.
- Prompt policy routing now receives a compact runtime tool catalog, so action decisions are based on registered local/MCP capabilities instead of generic model assumptions.
- Prompt policy routing now receives the same sliding-window recent messages used by ConversationService plus a runtime clock/context block, so short follow-up requests can route to action mode without bypassing the existing ReAct/Observation loop.
- Web UI session verification now distinguishes real authentication expiry from transient profile-check failures and throttles passive focus/visibility rechecks.
- Split gateway chat handling, RuntimeBlock input construction, memory visibility formatting, and tool prompt text into focused modules to reduce monolithic service coupling.
- Chat routes now pass raw messages plus structured attachments to ConversationService instead of merging attachment text into the user message at the HTTP layer.
- Light action tool turns now allow a small recovery budget for normal external-source failures instead of exhausting the loop after one failed retry.
- Quick start now uses provider-neutral API examples instead of implying a default provider/model.
- Enterprise Brain UI is hidden when `org_brain.enabled=false`.
- README now focuses on product positioning and release-readiness instead of internal engineering notes.
- Memory visualization/readability and modal structure were refined for the current UI.
- Web UI removed static showcase/reasoning leftovers from the runtime console and now keeps product promotion in documentation surfaces.
- Memory Workbench now renders entry, write-audit, recall, node, and edge details as readable UI instead of exposing raw JSON as the primary view.
- Workflow and advanced settings panels now use readable status/detail cards instead of raw JSON blocks for normal operation.
- Doctor and Self Evolution modals now present diagnostics/task results as readable summaries with clean bilingual copy.
- Chat composer send control now turns into a force-stop button while a task is running; stopping aborts the active stream and requests reasoning-tree cancellation when available.
- Streaming chat now emits the server-created session ID immediately so the reasoning sidebar can discover active trees during first-turn reasoning.
- Chat streaming now emits an early reasoning preparation event before prompt policy and runtime context are ready, so the UI can distinguish "preparing" from a missing reasoning trace.
- Memory-write classification and verification now receive recent interaction context, allowing short answers to direct prior questions to be written without deterministic keyword rules.
- Prompt policy routing instructions now tell the LLM router to select reasoning for explicit thinking, deep analysis, and analytical-framework requests unless clearly trivial.
- The LLM prompt-policy routing decision now propagates into `ReasoningService`, preventing a second internal gate from silently skipping reasoning after `need_reasoning=true`.
- Conversation runtime logs now record prompt-policy decisions and reasoning start/finish metadata for diagnosing long-running reasoning turns.
- Completed reasoning trees are retained in the runtime inspection cache so the Web UI can keep showing the trace after outcome assessment.
- Completed reasoning trees are also persisted under `brain/basal_ganglia/reasoning_traces/` so recent traces remain inspectable after a restart.
- Runtime reasoning trace snapshots are ignored by git to avoid committing user-specific execution data.
- The reasoning prompt block now uses `reasoning_summary` and a compact plan outline, so final answers can actually benefit from the completed reasoning tree.
- Channel, computer-control, and hot-memory modules had placeholder docstrings replaced with meaningful contracts.
- Core Promethea identity/system prompts were expanded to describe runtime capabilities, memory behavior, reasoning synthesis, tools/workflows, org context, and operating style.
- Runtime personality prompt assembly was unified around `soul_core`; separate `persona_core` and `persona_module` prompt blocks are no longer injected.
- Soul defaults and auto-evolution prompts now require durable long-term style/personality signals and explicitly reject facts, one-off requests, and tool/workflow rules.
- Soul auto-evolution is now scheduled from both the staged pipeline and the direct conversation-service processing path.
- `config/default.json` now includes the richer default `prompts.Promethea_system_prompt` and a stronger default `persona.soul` profile for new users.
- Self-evolve UI now reflects the real backend status payload: enabled state, task audit stats, store path, and disabled notice.
- `self_evolve` default configuration is documented and ships disabled by default.
- Settings advanced tools panel now shows official/community extensions from one catalog and can hot-reload manifest extensions.
- File upload modal now renders structured API errors as readable text instead of crashing the React tree, and its remaining mojibake copy was cleaned up.
- Tool-required streaming chat now routes through the real runtime tool loop instead of direct LLM streaming, and tool prompt blocks now forbid simulated tool results.
- Tool-call loop now fails closed when the model repeatedly emits fake function-style tool output instead of executable JSON.
- Prompt policy routing now separates reasoning, tool, and memory budgets so simple tool tasks can use a light action path without starting the full reasoning tree.
- Tool invocation now normalizes model-produced MCP calls against the unified registry, so official/community extensions use the same canonical `<service>.<action>` contract.
- Tool prompt instructions now distinguish official local tools from MCP/extension tools and inject the live registry snapshot for the current turn.
- Action/tool turns now use the existing tool-call loop as a lightweight ReAct path with an Observation verification gate before final answers.
- `light_action` routing now preserves a two-step budget by default: one primary action plus one optional verification/correction call.
- Web UI auth now follows a guest-first product flow: first paint is accessible, protected actions prompt sign-in, and existing tokens are verified on startup/focus/resume.
- Sign-in now supports a standard "remember me" option that stores tokens, not passwords; non-remembered sessions use a shorter session cookie.
- Settings now includes account management for current user status, sign-out, and guarded account deletion with username confirmation.
- Settings layout now keeps everyday controls visible while moving Enterprise Brain details behind a folded section to reduce first-screen complexity.

### Fixed
- Package metadata no longer ships the placeholder `your.email@example.com` author email.
- Workflow state persistence now JSON-safes checkpoint/run payloads and retries Windows atomic replacement briefly, preventing non-JSON runtime context objects or transient file locks from breaking release smoke tests.
- `.gitignore` now covers generated memory runtime state, self-model snapshots, cron job state, workspace output, and benchmark workspaces so release branches are less likely to include local runtime artifacts.
- Tool execution now JSON-safes structured tool results before formatting observations, preventing memory tools backed by Neo4j DateTime values from failing with serialization errors.
- Empty-chat welcome local fallback now follows the selected UI language, including the greeting text and date/time locale, when the backend LLM welcome call is unavailable.
- Error logging no longer uses Loguru diagnose mode by default, preventing exception traces from recording sensitive local variables such as login passwords.
- Login now returns a structured `neo4j_unavailable` / `neo4j_authentication_failed` error when the Neo4j-backed user store cannot be reached, instead of surfacing an unhandled server error after sleep/resume.
- Memory Workbench entry search now searches memory content and graph-node content / semantic keys instead of treating default `episodic` memory type labels as primary matches.
- Workbench welcome generation now follows the selected UI language via `/api/welcome?lang=...`, while chat responses continue to follow the conversation language policy.
- In-process MCP services now start in a registry-backed `ready` state instead of being mislabeled `offline` before their first invocation; unprobed remote MCP services remain `unknown`.
- Reasoning trace history now lists persisted completed trees from disk by user/session, so old conversations can recover trace history after in-memory caches are gone.
- Fixed a Web UI auth-profile verification loop that could repeatedly call `/api/user/profile` after a successful profile refresh and trigger HTTP 429 rate limits.
- Fixed MCP tool-call parsing so service-wrapped calls such as `content_tools` with nested `args.tool_name=web_fetch` preserve the concrete action instead of degrading into `content_tools.content_tools`.
- Fixed overly aggressive Web UI token clearing when `/api/user/profile` times out or the backend has a transient non-auth failure.
- Fixed prompt-policy context starvation where the router could choose direct chat for local computer-control requests because it had not seen the registered tool catalog.
- Clarified that corrupted-looking fragments in text normalization are intentional mojibake detection markers, not user-facing copy.
- The reasoning sidebar no longer polls active reasoning every two seconds while no chat task or reasoning tree is active, reducing misleading backend log noise.
- Token metrics now record real LLM call latency and usage from non-streaming and streaming calls, and the Metrics UI reads the backend's actual field names.
- Tool-call loop no longer returns unexecuted JSON tool-call protocol text to the Web UI when the lightweight ReAct path exhausts its tool budget.
- Restored Promethea core identity injection so thin user prompts cannot make the model identify as the provider or deny long-term memory as a fixed limitation.
- Restored LLM-driven prompt policy routing for memory decisions; removed deterministic keyword overrides from the router and recall gate.
- Removed keyword fallback memory-write classification; when the memory classifier LLM is unavailable, Promethea now skips automatic long-term writes instead of guessing.
- Restored Web UI conversation controls, memory-write visibility notices, queue status display, `@` insertion, and emoji insertion.
- Removed the static fake reasoning graph from the empty chat view to avoid confusing it with live reasoning or real memory structure.
- Removed the unused `AgentGraph` ReactFlow component and its frontend dependency after the live UI stopped using that static graph.
- Removed the disabled Pause control from the reasoning sidebar until a real pause endpoint exists.
- Fixed chat streaming state getting stuck when an SSE connection closes without an explicit `done` event.
- Clarified the reasoning sidebar empty state while a turn is running: it now waits for a real reasoning trace instead of implying a missing UI failure.
- Fixed memory-write verification rejecting contextual short answers such as a school name given in response to a prior assistant question.
- Fixed first-turn streaming UI being reset to the empty landing panel when the server-created session ID arrived before the turn was committed.
- Fixed MCP computer-control calls where the model swapped `service_name` and `tool_name`, causing valid registered actions such as `computer_control.execute_command` to fail as missing services.
- Fixed first-turn deep-reasoning streams clearing optimistic chat messages while `sessionId` was still pending.
- Fixed reasoning trace requests returning 404 immediately after a successful turn because outcome assessment removed the pending tree.
- Improved reasoning sidebar chronology and readability by sorting nodes by creation time and showing goal/notes/status cards instead of raw observations first.
- Fixed remaining Web UI mojibake in the app shell, sidebar, reasoning sidebar, and memory workbench.
- Fixed README Chinese mojibake and a local-model docs arrow mojibake issue.
- Removed stale product-homepage duplicate after confirming it matched `README.md`.
- Documented that `memory/raw_log.jsonl` and `memory/raw_log.state.json` are runtime memory state, not disposable logs.
- `web.fetch_text` now applies the same sandbox URL check as other web tools.
- MCP manifest registry now tracks source paths so built-in and community extensions can be exposed consistently without merging their backend implementations.
- Fixed Files modal white-screen behavior when `/api/files/upload` returns a structured 4xx error.
- Fixed a critical false-tool-call path where the model could answer with fake `math.calculate(...)`, `web_search(...)`, or file-creation text without any backend tool execution.
- Fixed tool-failure finalization so failed tool observations instruct the model to report failure instead of inventing successful data.

### Verification
- `D:\产品\.venv\Scripts\python.exe -m pytest -q` passed: 491 passed, 5 skipped after Agent Avatar foundation.
- `cd UI; npm run build` passed after Agent Avatar foundation.
- `D:\产品\.venv\Scripts\python.exe -m pytest -q` passed: 486 passed, 5 skipped after MCP cold-start health correction.
- `D:\产品\.venv\Scripts\python.exe -m pytest -q` passed: 485 passed, 5 skipped.
- `cd UI; npm run build` passed after registry-backed tool prompt and chat-title updates.
- `D:\产品\.venv\Scripts\python.exe -m pytest tests\test_reasoning_service.py tests\test_config_contracts_docs.py tests\test_prompt_assembler.py -q` passed: 40 tests.
- `cd UI; npm run build` passed after auth-profile loop fix.
- `D:\浜у搧\.venv\Scripts\python.exe -m pytest tests\test_tool_execution.py tests\test_tool_spec_policy_registry.py tests\test_prompt_policy_router.py tests\test_chat_routes_args_resilience.py -q` passed: 32 tests.
- `cd UI; npm run build` passed.
- `D:\浜у搧\.venv\Scripts\python.exe -m pytest -q` passed: 465 passed, 5 skipped.
- `cd UI; npm run build` passed.
- `..\.venv\Scripts\python.exe -m pytest tests/test_prompt_policy_router.py tests/test_chat_routes_args_resilience.py -q` passed: 8 tests.
- `python -m pytest tests/test_files_routes.py tests/test_chat_routes_args_resilience.py tests/test_config_routes_contract.py tests/test_prompt_assembler.py tests/test_user_secrets.py tests/test_prompt_policy_router.py -q` passed: 29 tests.
- Memory/channel/computer focused checks passed: 28 passed, 2 skipped.

### Manual Release Checks Remaining
- Web UI smoke: register/login, chat, file attachment, global search, memory inspector, workflow inspector, settings save.
- Neo4j-on and Neo4j-off first-run flows.
- One local startup from a clean checkout or clean copy.

---

## [0.1.0] - 2026-03

### Gateway & Protocol (Backlog 001-002)
- Unified `RunContext` and `SessionState` objects.
- `GatewayRequest` / `GatewayResponse` / `GatewayEvent` protocol contracts.
- Event bus (`EventEmitter`) with bounded trace and audit history.

### Conversation Pipeline (Backlog 003)
- Six-stage pipeline: Input Normalization -> Mode Detection -> Memory Recall -> Planning -> Tool Execution -> Response Synthesis.
- `ConversationPipeline` staging with per-stage structured outputs.

### Prompt Assembly (Backlog 004)
- Block-based prompt assembly (`identity`, `policy`, `memory`, `tools`, `workspace`, `reasoning`, `response_format`).
- Token estimation and block compaction support.

### Tool Governance (Backlog 005)
- `ToolSpec` with side-effect level, permission scope, timeout hints.
- `ToolRegistry` unified across local tools and MCP services.
- `ToolPolicy` with allow/deny/mode-aware evaluation.

### Observability Foundation (Backlog 006)
- `TraceEvent` and `AuditEvent` structured in-memory history.
- `infer_audit_event` - automatic audit inference from trace events.

### Memory Write Gate (Backlog 007)
- `MemoryWriteGate` - allow / deny / defer decisions before long-term writes.
- Denial reasons: `low_confidence`, `speculative_content`, `short_lived_context`, `conflict_detected`.
- `memory.write.decided` event emitted for all write candidates.

### Reasoning State Machine (Backlog 008)
- `ReasoningNode` explicit lifecycle states: `pending/running/waiting_tool/waiting_human/succeeded/failed/skipped`.
- Transition validation integrated with workflow recovery primitives.

### Workspace Sandbox MVP (Backlog 009)
- `WorkspaceService` with user-scoped root path and path-escape protection.
- Artifact write, update, list, snapshot operations.
- `workspace.artifact.written` and `workspace.write.blocked` audit events.

### MCP Health & Tool Panel (Backlog 010)
- `MCPServiceHealth` with status, sync timestamps, last error, user visibility.
- `MCPToolDescriptor` for panel/query APIs.
- Gateway endpoints: `mcp.services.list`, `mcp.service.health`, `mcp.service.tools`, `mcp.tools.visible`.

### Memory Recall Policy & Inspector (Backlog 011)
- `MemoryRecallRequest` / `MemoryRecallResult` structured contracts.
- Mode-aware recall policy: `fast / deep / workflow`.
- Recall run inspector: selected items, dropped candidates, filter reasons, metrics.

### Workflow Engine MVP (Backlog 012)
- `WorkflowDefinition`, `WorkflowRun`, `WorkflowStep`, `Checkpoint` schema.
- Step types: `reasoning_step`, `tool_step`, `artifact_step`, `approval_step`, `memory_step`, `summary_step`.
- Engine: start / pause / resume / retry / approve / checkpoint.
- HTTP routes: `/workflow/*`.

### Channel Adapter Framework (Backlog 013)
- Unified adapter interface and metadata model.
- Adapter registry with default channels: `web`, `http_api`, `telegram`.
- Identity normalization, permission check, request/response mapping per channel.

### Skill Layer (Backlog 014)
- `SkillSpec`, `SkillExample`, `SkillEvaluationCase` schema.
- Skill registry with official pack loading and user-aware resolution.
- `tool_allowlist`, `default_mode`, `system_instruction` injected at runtime.
- HTTP: `/api/skills/catalog`, `/api/skills/install`, `/api/skills/activate`.

### Config Schema & Migration (Backlog 015)
- `config_version` root marker.
- `gateway/config_migrations.py` migration module.
- Scoped config access: `get_runtime_config`, `get_user_preferences`, `get_tool_policy_config`.

### Namespace & Security Audit (Backlog 016)
- `security.boundary.violation` event type.
- `SecurityAuditService.build_report` - per-user audit summary.
- HTTP: `GET /api/security/audit/report`, `GET /api/security/audit/events`.
- Enforcement in: memory recall, workspace access, tool execution.

### Memory Backends
- `FlatMemoryStore` - JSONL backend, zero dependencies.
- `SqliteGraphMemoryStore` - SQLite with graph recall via recursive CTE.
- MEF (Memory Exchange Format) - lossless export/import across all backends.
- `MemoryAdapter.migrate_backend` - live backend cutover and dual-write mode.
