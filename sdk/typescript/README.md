# Promethea TypeScript SDK

Thin TypeScript client for the public Promethea Runtime boundary.

```ts
import { PrometheaClient } from '@promethea/sdk'

const client = new PrometheaClient({
  baseUrl: 'http://localhost:8000',
  token: () => localStorage.getItem('auth_token') ?? undefined,
})

const response = await client.runs.run({ message: 'Hello' })

const image = await client.files.upload(file, {
  filename: 'diagram.png',
  sessionId: response.session_id,
})
const visualResponse = await client.runs.run({
  message: 'Explain this diagram',
  session_id: response.session_id,
  attachments: [client.files.attachment(image)],
})

for await (const event of client.runs.stream({ message: 'Research this' })) {
  console.log(event.event_type, event.payload)
}

const session = await client.sessions.get(response.session_id!)

const project = await client.projects.create({ name: 'Research' })
await client.projects.assignSession(response.session_id!, project.project_id)
const projects = await client.projects.list()

for await (const snapshot of client.workbench.watch({ taskId: 'task_123' })) {
  console.log(snapshot.task?.status, snapshot.current_activity)
}

const paused = await client.tasks.pause('task_123', { expected_revision: 4 })

const canvases = await client.canvas.list('session-1')

const ambient = await client.ambient.configure(response.session_id!, {
  enabled: true,
  direction: 'Notice and help with unresolved release blockers',
})
const personalAttention = await client.ambient.get()
if (ambient.pending) {
  await client.ambient.confirm(response.session_id!, {
    run_id: ambient.pending.run_id,
    tool_call_id: ambient.pending.tool_call_id,
    action: 'approve',
  })
}
```

## Streaming And Steering

SSE `text` payloads follow the generated `AnswerUpdate` contract. Apply
`operation: "replace"` as a replacement, including an empty string; omitted
operations remain legacy append-only deltas. `applyAnswerUpdate(current, update)`
implements this projection. A `done.content` string is the authoritative final
answer. Draft text can be withdrawn after action validation or user steering;
clients must not concatenate discarded drafts with a recovered answer.

Use `session_started.conversation_turn_id` to target the current chat execution:

```ts
const commandId = crypto.randomUUID()
const receipt = await client.runs.steer(sessionId, {
  conversation_turn_id: turnId,
  message_id: commandId,
  message: 'Keep the existing files and summarize only.',
}, signal)
```

Retry uncertain delivery with the same ID and message. `queued` confirms durable
receipt, not application; the stream emits `steering` with `status: "applied"`
and `message_ids` after consumption. Saved user messages retain the command ID
and `steering_status`. Stopped/failed turns preserve unconsumed guidance as
`not_applied` rather than claiming execution. Reusing an ID with different text
returns 409. Foreign sessions return 404.

V1 accepts guidance only while that owned Action loop is active. Preparation,
confirmation waiting and finalization are not steerable (409); clients retain
unsent text. Guidance joins the existing model messages at a safe boundary,
withdraws an unexecuted stale proposal and clears its old approvals. It does not
cancel a dispatched tool batch, undo side effects, extend the step budget or
authorize a replacement action. Explicit stop/abort remains separate. This is
current chat-turn control, not a new detached-task scheduler or a WebSocket
command protocol.

## Guest Chat

`client.runs.guestStatus()` reads operator-owned availability and limits.
`client.runs.guest({ messages: [{ role: 'user', content: 'Hello' }] })` performs
temporary text-only chat without an account. It returns a complete model reply,
not an Agent run or a persisted session. Supply an `AbortSignal` as the second
argument to cancel. The server enforces all access and usage limits; the SDK adds
no permissions or model policy. See [Guest Chat Configuration](../../docs/configuration.md#guest-chat).

## Commands

```bash
npm install
npm run generate
npm run generate:check
npm run typecheck
npm test
```

The generated types in `src/generated/public-contracts.ts` come from
`gateway/public_contracts.py` through JSON Schema. Do not edit them manually.

Generation requires Python with Pydantic 2.5 or newer, not a running Gateway or
computer/browser dependencies such as `psutil` and Playwright. The command uses
`PYTHON` when set, then the parent workspace `.venv`, then Python on `PATH`.
An interpreter that starts but lacks Pydantic fails explicitly rather than
silently selecting a different environment. SDK consumers only need the built
TypeScript package; Python is needed for maintaining the generated contracts.

## Scope

The first release supports:

- non-streaming Run requests over HTTP
- streaming Run requests over SSE
- typed file upload and attachment conversion for multimodal Run input
- Session lookup
- Task lookup/list, detached Run start, and revision-aware pause, resume, and cancel commands
- Workbench snapshot queries and cursor-resumable SSE subscriptions
- opt-in Ambient state/configuration, annotation feedback, and exact sensitive-action confirmation
- Semantic UI expression reads, revision-aware choice/dismissal feedback and sequenced, expiring host-view/object reports through `client.semanticUI`; no tool dispatch or approval semantics
- `client.channels` reads account-scoped status, creates verified pairing codes, revokes bindings and inspects/retries persisted replies; it never holds bot credentials or Agent policy. See [channel setup](../../docs/channels/README.md).
- `client.canvas.semantics/interact` use generated component snapshot/command types and current definition/state revisions; only declared local app-state operations. `connectCanvasFrame` supports bounded visible-state watching and teardown, never arbitrary Runtime execution.
- Canvas discovery, app-state reads/optimistic writes, retain/delete, diagnostics,
  and a restricted opaque-frame bridge; no arbitrary tool execution from apps
- bearer-token injection
- structured and legacy error mapping
- `AbortSignal`
- raw endpoint requests through `client.request()` for incremental adoption by
existing TypeScript clients; typed SDK resources remain preferred for stable
public APIs

Chat stream events consume server-provided event IDs, sequence numbers, request
correlation, timestamps, and source metadata when present. The legacy JSON
payload remains available under `event.payload`, including `type`, `content`,
and memory visibility fields.

It does not implement Agent, Memory, Reasoning, Workflow, Prompt, Tool Policy,
authorization, multimodal model selection, or lifecycle decisions. It does not define a
second tool/plugin protocol; external tools continue to use MCP.

Task execution leases, process ownership, activation epochs, and raw attempts
remain internal Python state and are intentionally absent from generated SDK
types. `workbench.watch()` reconnects the transport from the last received
cursor; the Python projection remains the source of task and activity state.
Workbench workflow and memory records are public summaries rather than raw
Python service records.

Gateway WebSocket support is intentionally deferred until its public path and
browser authentication contract are stable.
