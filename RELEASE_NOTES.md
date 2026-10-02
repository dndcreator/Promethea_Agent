# Release Notes

## Unreleased

- Add adaptive cognitive recall inside `SelfModelService`: query-aware passive projection plus an explicit `cognition.recall` capability that consumes one governed Memory candidate pool, preserves critical records through a bounded skip buffer, and applies budgeted decomposition, parallel kernels, and at most two reduction layers. Cognition snapshots remain Run-scoped, cancellable, deadline-bounded, and unable to write Memory directly.
- Reuse completed adaptive cognition as bounded, untrusted Hippocampus replay hints: persist only the synthesis and source memory IDs in replay checkpoint state, batch hints under configurable limits, re-read the original memories before consolidation, and consume hints without promoting them directly to Memory.
- Unify tool discovery without removing runtime extensibility: built-in and community manifests now auto-register into the single `ToolRegistry`, hot reload replaces changed roots and unregisters removed commands, Self Evolve publication reuses that reload path, and only true out-of-process providers remain in the MCP registry. Remove duplicate computer-control proxy actions while preserving their direct content, runtime, and graph tools.
- Remove the remaining historical tool execution detours: external MCP calls now leave `CapabilityService` through one transport method, dead MCP-owned agent handoff and registry aliases are gone, the scheduler manifest targets its canonical service directly, and model-facing tool calls use one registry identifier shape.
- Reduce time to first model token by preparing Self Model, the capability catalog, and optional organization context concurrently, while moving synchronous Neo4j-backed context reads off the async event loop.
- Preserve streaming for ordinary fenced code and non-routing JSON responses by buffering only prefixes that can still be a runtime action envelope.
- Record model time-to-first-token separately from total model latency so provider delay can be distinguished from Runtime preparation cost.
- Promote time and scheduling into a generic Runtime capability: resolve explicit user, client, or host timezones without a fixed regional default, expose interval/instant/calendar triggers, persist creator and workspace context, isolate jobs by user, reclaim interrupted execution through leases, apply explicit misfire policy, and route every background target back through `CapabilityService` and current policy instead of invoking tools out of band.
- Redefine Self Evolve as append-only capability evolution: Agent-authored code is confined to user-owned task staging, validated with required smoke tests and a content digest, atomically published as an immutable version under the generated extension root, hot-registered through the existing tool registry, and executed by a trusted proxy in the process sandbox. Private generated tools remain hidden from other users, and Self Evolve no longer exposes a path for patching Promethea Core.
- Consolidate production capability execution on `CapabilityService`: remove the retired `ToolService` module/name, the unused MCP-log WebSocket, the Gateway computer-control execution facade, and duplicate config-write compatibility routes. Persisted-state migrations remain supported.
- Make the three-pane Web UI responsive: preserve the chat surface on narrow screens, expose Workbench as a dismissible overlay, and keep language switching in the navigation drawer without changing runtime behavior.
- Bind process-environment approval to the exact launch command and inspected environment revision, keep registration command-free, preserve static canvases across restarts, and surface interrupted process environments through the durable Workbench event stream. Keep Canvas content in an opaque-origin iframe, add authenticated multi-method streaming HTTP and WebSocket proxying for local process environments, and prevent external redirect escape.
- Expand CI across Windows, Linux, and macOS sandbox paths and verify generated SDK contracts, SDK build/tests, and React lint/build on every change. Consolidate lazy runtime construction behind `CapabilityService`.
- Promote the former tool boundary into a first-class `CapabilityService` spanning registered tools, policy and approval, workspace-bound computer controllers, the existing process sandbox, and persistent canvas environments. Add restart-aware environment lifecycle, authenticated workspace-confined previews, generated TypeScript contracts and SDK consumption, and a minimal isolated Canvas UI.
- Remove legacy tool-execution bypasses and English name-based risk inference. Conversation, agent handoff, nested Moirai steps, and scheduled jobs now converge on `CapabilityService`; official and MCP tools declare structured side effects, undeclared tools fail closed, and background jobs cannot consume interactive approval implicitly.
- Unify risky-tool confirmation with the execution registry and policy: structured side-effect metadata, including manifest-declared per-action selectors for composite MCP tools, now drives one-shot, exact-call approval through Conversation, Action, `CapabilityService`, and the platform sandbox. Consume pending approvals before execution, preserve reviewed argument snapshots and multi-call consent, reject replay or changed arguments, and keep explicit operator denials as non-overridable ceilings. Command and desktop modes now default to interactive approval rather than broad standing host access.
- Keep browser downloads inside the authenticated workspace through Playwright download events, retain listeners for the controller lifecycle, and expose a bounded wait action without polling arbitrary host folders.
- Bind Runtime tool calls and direct Gateway computer requests to trusted user/workspace context; keep filesystem roots, browser state, element references, and managed processes in that workspace. Bound the controller cache through `SANDBOX__COMPUTER_MAX_WORKSPACES`, preserve active workspaces during eviction, serialize shared desktop operations, and explicitly enable Chromium's process sandbox. Route mouse/keyboard/screenshot capabilities through the screen controller and send browser keypresses to the target browser element instead of the host keyboard. Host desktop control remains opt-in and is not advertised as desktop isolation.
- Keep computer-control command execution cancellable through the shared asynchronous sandbox runner, preserve process failure status, and expose the actual process backend and enforcement in command/code results. Fix browser initialization and apply filesystem policy to browser screenshots and desktop image lookup paths. These checks do not provide desktop isolation.
- Align official command execution with the user/session workspace used by file and code tools, so agents can write, execute, inspect artifacts, and retry within one sandboxed environment; reject caller identity overrides and traversal workspace IDs, clean up per-call Python scripts, and terminate confined subprocesses on task cancellation or timeout without blocking the Gateway event loop.
- Allow read-only filesystem access to registered Desktop, Documents, and Downloads locations while keeping all host mutations outside the workspace denied; resolve paths at the controller boundary and reject recursive host-directory copies.
- Add OS-backed process sandbox providers for Linux (Bubblewrap), macOS (Seatbelt), and native Windows (restricted token, workspace ACL, and kill-on-close job), with a shared fail-closed Python runner used by official command/code tools, computer process control, Self Evolve validation, and Moirai command steps. The Windows provider replaces the earlier Docker Linux VM; it limits writes but does not isolate reads, network, or desktop control.
- Enable the sandbox policy by default and fail closed for unconfined host capabilities: workspace-scoped files remain available, host commands and desktop input require one-shot confirmation, and untracked process control requires explicit operator opt-in. Apply the same checks at direct controller entry points to prevent MCP-wrapper bypasses, and classify confirmation risk from the concrete computer action rather than only its wrapper name.

- Promote Self Model to a first-class read-only Runtime service: it projects governed cognition and active task identity into `RunContext`, supplies a bounded dynamic prompt block, propagates through existing reasoning/tool/workflow context, and leaves Memory, Task, Tool, Reasoning, Workflow, and Self Evolve ownership unchanged; remove the duplicate Self Model and cognition implementation formerly embedded in Self Evolve.
- Remove implementation-oriented explanatory copy from the UI while retaining actionable errors, destructive-action warnings, and restart requirements.
- Make the optional sign-in modal dismissible through its close button, backdrop, or Escape key while preserving guest mode and authentication behavior.
- Unify cognition with Self Model as a user-scoped projection over governed memory, expose it through generated public contracts and the TypeScript SDK, and simplify the former Memory Workbench to Cognition, Memory, and Review views.
- Replace the separate PromptPolicyRouter and language-specific mode heuristics with one configurable, bounded main-model control loop: direct answers take one model call, while memory recall, deeper reasoning, tools, and workflows are selected from the live `CapabilityService` catalog and remain executed by their existing Python services.
- Replace English keyword heuristics in the memory write gate with extractor- and verifier-classified modality and persistence; deterministic code now routes hypothetical, ephemeral, bounded, durable, and unclassified state without language-specific phrase lists.
- Isolate Workflow engine tests from the Runtime's durable `gateway/workflow_state.json`, preventing test runs from inflating and repeatedly rewriting production task history.
- Separate related-memory retrieval from contradiction adjudication in the memory write gate: verifier-classified equivalent memories deduplicate silently, compatible and project-state updates can proceed, and only genuine or profile-sensitive unresolved conflicts require confirmation; semantic keys no longer expand model-provided concepts into noisy word bags.
- Add durable hippocampus replay as a separate idle-time memory maintenance process after normal gated writes: threshold and time-based scheduling, low-frequency recursive revisits, bounded reflection, revisable insights, foreground interruption, checkpoint recovery, and backend-neutral writes through the existing adapter boundary.
- Simplify Workbench into a compact status summary, semantic activity filters, a card-free execution timeline, and controls that appear only while intervention is possible, without changing Runtime events or Task/Reasoning behavior.
- Consolidate web discovery behind the single `web.search` tool, retire the duplicate legacy `websearch` manifest, make providers registry-driven and asynchronously cancellable, expose explicit fallback/order policy, and persist bounded structured search presentation metadata for Workbench replay.
- Add Conversation-native image input routing: try the main model first, fall back only on explicit unsupported-modality errors to an optional per-user multimodal endpoint, preserve OCR/text degradation, and expose typed file upload through the TypeScript SDK.
- Align streaming and non-streaming Run request propagation, add stable metadata to backward-compatible chat SSE frames, keep Workbench session scope isolated, and replace raw workflow/memory records with generated public summaries.
- Publish stable Task/Run and Workbench read contracts, including detached Run start responses, while keeping execution leases, ownership epochs, raw attempts, and recovery tokens inside Python Runtime.
- Add cursor-resumable Workbench SSE, typed Task controls, and Workbench subscriptions to the TypeScript SDK; the existing React Workbench now consumes that stream without owning task lifecycle decisions.
- Present Workbench as a readable state tracker: lifecycle and compatibility events are folded into stable business activities, while transport bookkeeping remains available only in the raw runtime log.
- Replace display-text tool failure guessing with one structured execution result and error contract; legacy strings are interpreted only at the compatibility boundary.
- Derive tool callability from manifest-declared capabilities, live provider readiness, MCP health, and policy, with the same generic check repeated before invocation.
- Add provider-owned semantic filesystem locations and validate their resolved paths through the existing sandbox instead of teaching the router platform paths.
- Emit bounded tool outcome summaries and structured failures into the Runtime Event Log without persisting raw tool payloads.
- Version the Neo4j memory schema and apply an idempotent compatibility backfill once per database.
- Keep model transport payload logging explicitly opt-in and remove duplicate recent-conversation text from runtime context assembly.
- Define a small transport-neutral public contract set for runs, sessions, events, tools, and errors; expose it as JSON Schema while retaining FastAPI OpenAPI and MCP as the HTTP/client and plugin sources of truth.
- Generate committed JSON Schema and TypeScript bindings from the public Pydantic contracts, enforce drift checks in tests, and use generated Run/Attachment types in the existing UI API layer.
- Add a minimal TypeScript SDK for HTTP Run calls, SSE streaming, Session lookup, structured/legacy errors, authorization headers, and cancellation without moving any Agent runtime decisions out of Python; the React chat stream now consumes this SDK through its existing UI adapter.
- Restore timely memory-conflict notices from the asynchronous Workbench projection, and make text-selection follow-up controls dismissible by outside click, scrolling, Escape, or an explicit close button.
- Route the remaining React Runtime HTTP calls through the SDK transport while preserving existing raw `Response` semantics, and remove the unused duplicate legacy UI API client.
- Add a first-class durable Task domain, separate from conversations; explicit workflow executions synchronize task runs while ephemeral reasoning and ReAct traces remain conversation-local.
- Add a bounded Runtime Event Log with restart-stable sequencing, recursive secret redaction, rotated retention, and non-blocking filesystem I/O.
- Give Memory a durable interaction-event cursor and restart replay path; the existing memory write gate remains the final content decision layer.
- Propagate optional `task_id` and `run_id` through conversation, reasoning, memory, tool, workflow, and task lifecycle events for unified Workbench correlation.
- Add a durable Task state machine with update, start-run, pause, resume, and cancel controls.
- Host explicit Workflow runs in a detached TaskRuntime so client disconnects do not stop work, and recover owned running runs from persisted checkpoints after process restart.
- Fence durable Task execution with monotonic revisions, per-Run execution epochs, expiring owner leases, and process Attempts; stale commands and stale workers can no longer commit over newer state while independent Runs remain parallel-capable.
- Persist Workflow Step Attempts before execution, repair open attempts as interrupted after restart, and propagate stable idempotency keys into workflow-managed tool calls.
- Add durable `retry_wait` with exponential backoff and a recovery supervisor so transient provider/tool failures can continue without an attached browser or conversation request.
- Fail loudly on corrupt Task or Workflow state instead of silently replacing durable work with an empty or partial view.
- Replace the UI-side Workbench API join with a backend materialized projection that hydrates from Runtime Event Log and follows new Gateway events incrementally.
- Add persistent, text-anchored follow-up annotations for chat responses.
- Upgrade personal workspace migration toward a portable, verifiable archive format.
- Personal workspace archives intentionally exclude credentials, local browser profiles, process state, and raw service logs.
- Restored workflows that were active on the source device are paused pending an explicit resume.
- Preserve user-visible memory write decisions and pending review records in portable workspace archives.

## Public Preview Release Candidate

This release candidate focuses on making Promethea usable as a local-first cognitive agent runtime with a modern Web UI, graph-first memory, backend-aware first-run behavior, and release-ready documentation.

## Highlights

- Promotional bilingual homepage for Promethea's positioning: beyond memory, toward cognition.
- Vite Web UI connected to the gateway startup script.
- Backend-aware first-run auth flow:
  - Neo4j remains the default and core graph backend.
  - If Neo4j is configured but unavailable, registration is blocked with a clear message instead of silently falling back.
  - The login screen can enter setup/diagnostics mode before sign-in.
- File upload and attachment flow:
  - Text-like files can be extracted and attached to chat.
  - Image files are stored and may use OCR when optional dependencies are available.
  - Stored-only attachments are explicitly described as unavailable to the model instead of being invented.
- Global search across sessions and uploaded files.
- Workflow inspector for definitions, personal runs, recovery, pause/resume, and checkpoints.
- Enterprise Brain visibility now follows `org_brain.enabled`; disabled enterprise features are hidden from the UI.
- Memory visualization and inspector readability improvements.
- Test artifact policy confines runtime test files under `.tmp/pytest-runtime/`.
- User configuration is split into sensitive env values, basic config, and advanced config.
- Prompt assembly uses explicit prompt blocks, with policy routing prepared for need-based block selection.
- `memory/raw_log.jsonl` is documented as the L0 memory layer, not disposable test output.

## Important Behavior

- Full graph-memory behavior requires Neo4j.
- Fallback memory backends remain available, but they are explicit choices, not silent replacements for the default Neo4j experience.
- Changing backend configuration should be followed by a restart.
- Playwright browser control requires installing Playwright browsers separately.
- Multimodal support currently means file storage, text extraction, and optional OCR; it is not guaranteed native vision input for every model/provider.
- Voice input is not part of the supported preview release surface. The current experimental push-to-talk route depends on an OpenAI-compatible audio transcription provider; a DeepSeek-only chat configuration does not provide STT/audio transcription.

## Verification

Release-focused checks run during preparation:

- `python -m pytest`: 500 passed, 5 skipped
- `npm run build` in `UI/`: TypeScript and Vite production build passed
- `npm run lint` in `UI/`: ESLint passed

Manual checks still required before a stable tag:

- Web UI smoke test: first-run status, registration/login, chat, file attachment, global search, memory inspector, workflow inspector, settings save, enterprise feature visibility.
- Neo4j-on and Neo4j-off first-run flows.

## Known Limitations

- This is a public preview / release candidate, not a final stable commercial release.
- Neo4j is strongly recommended for the intended graph-structured memory experience.
- Some advanced integrations depend on optional local services or third-party credentials.
- Frontend development/build can be affected by local Windows Node/esbuild execution policy; verify in a normal local PowerShell environment.
- Voice endpoints may appear in the internal API surface, but they are experimental/provider-dependent and should not be presented as a ready user feature in this release.

## Upgrade Notes

- Copy new environment variables from `env.example` if your local `.env` is old.
- Restart the gateway after changing memory backend or enterprise feature switches.
- Do not commit files under `config/users/`, `logs/`, `workspace/`, `UI/node_modules/`, `.tmp/`, or local test artifact directories.
- Treat `memory/raw_log.jsonl` and `memory/raw_log.state.json` as runtime memory state. Do not clean them as generic logs.
