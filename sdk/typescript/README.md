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

for await (const snapshot of client.workbench.watch({ taskId: 'task_123' })) {
  console.log(snapshot.task?.status, snapshot.current_activity)
}

const paused = await client.tasks.pause('task_123', { expected_revision: 4 })

const canvases = await client.canvas.list('session-1')
```

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

## Scope

The first release supports:

- non-streaming Run requests over HTTP
- streaming Run requests over SSE
- typed file upload and attachment conversion for multimodal Run input
- Session lookup
- Task lookup/list, detached Run start, and revision-aware pause, resume, and cancel commands
- Workbench snapshot queries and cursor-resumable SSE subscriptions
- Canvas environment discovery and authenticated preview URLs
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
