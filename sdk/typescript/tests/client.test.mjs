import assert from 'node:assert/strict'
import test from 'node:test'

import { PrometheaClient, PrometheaError } from '../dist/index.js'


function jsonResponse(payload, init = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    statusText: init.statusText,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
}


test('runs.run serializes the public request and authorization header', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000/',
    token: 'secret',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({ response: 'ok', session_id: 's1', status: 'success' })
    },
  })

  const result = await client.runs.run({ message: 'hello', stream: true })

  assert.equal(result.response, 'ok')
  assert.equal(calls[0].url, 'http://localhost:8000/api/chat')
  assert.equal(calls[0].init.method, 'POST')
  assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer secret')
  assert.deepEqual(JSON.parse(calls[0].init.body), { message: 'hello', stream: false })
})


test('files.upload returns an attachment-ready generated UserFile', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        status: 'success',
        file: {
          file_id: 'file-1',
          filename: 'diagram.png',
          bytes: 12,
          content_type: 'image/png',
          modality: 'image',
          text_extraction_status: 'empty_or_unsupported',
        },
      })
    },
  })

  const file = await client.files.upload(
    new Blob(['image-bytes'], { type: 'image/png' }),
    { filename: 'diagram.png', sessionId: 's1' },
  )
  const attachment = client.files.attachment(file)

  assert.equal(calls[0].url, 'http://localhost:8000/api/files/upload')
  assert.ok(calls[0].init.body instanceof FormData)
  assert.equal(file.file_id, 'file-1')
  assert.equal(attachment.file_id, 'file-1')
  assert.equal(attachment.modality, 'image')
})


test('sessions.get maps the existing session envelope to generated Session', async () => {
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => jsonResponse({
      status: 'success',
      session_id: 'space/id',
      session_info: { title: 'Demo', created_at: 10, pinned: true },
      messages: [],
    }),
  })

  const session = await client.sessions.get('space/id')

  assert.deepEqual(session, {
    session_id: 'space/id',
    title: 'Demo',
    created_at: 10,
    pinned: true,
  })
})


test('client.request preserves raw HTTP responses for incremental endpoint adoption', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000/',
    token: 'secret',
    credentials: 'include',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({ detail: 'conflict' }, { status: 409 })
    },
  })

  const response = await client.request('api/config', { method: 'PATCH' })

  assert.equal(response.status, 409)
  assert.equal(calls[0].url, 'http://localhost:8000/api/config')
  assert.equal(calls[0].init.credentials, 'include')
  assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer secret')
})


test('structured HTTP errors become PrometheaError', async () => {
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => jsonResponse({
      status: 'error',
      error: {
        code: 'service_unavailable',
        message: 'Memory unavailable',
        retryable: true,
        trace_id: 'trace-1',
      },
    }, { status: 503 }),
  })

  await assert.rejects(
    () => client.runs.run({ message: 'hello' }),
    (error) => {
      assert.ok(error instanceof PrometheaError)
      assert.equal(error.code, 'service_unavailable')
      assert.equal(error.retryable, true)
      assert.equal(error.traceId, 'trace-1')
      assert.equal(error.status, 503)
      return true
    },
  )
})


test('legacy string errors remain supported', async () => {
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => jsonResponse({ error: 'legacy failure' }, { status: 400 }),
  })

  await assert.rejects(
    () => client.runs.run({ message: 'hello' }),
    (error) => error instanceof PrometheaError && error.message === 'legacy failure',
  )
})


test('runs.stream parses chunked SSE into generated Event values', async () => {
  const encoder = new TextEncoder()
  const chunks = [
    'event: text\ndata: {"type":"text","content":"hel',
    'lo","session_id":"s1"}\n\n',
    'data: {"type":"done","session_id":"s1"}\n\n',
  ]
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
  })

  const events = []
  for await (const event of client.runs.stream({ message: 'hello' })) events.push(event)

  assert.equal(events.length, 2)
  assert.equal(events[0].event_type, 'text')
  assert.equal(events[0].session_id, 's1')
  assert.equal(events[0].payload.content, 'hello')
  assert.equal(events[1].event_type, 'done')
})


test('runs.stream consumes stable server event metadata without changing legacy payload', async () => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(
        'id: req-1:7\nevent: text\ndata: {"type":"text","content":"hello","event_id":"req-1:7","event_type":"text","occurred_at":"2026-08-20T00:00:00+00:00","seq":7,"request_id":"req-1","source":"gateway.http.chat"}\n\n',
      ))
      controller.close()
    },
  })
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
  })

  const events = []
  for await (const event of client.runs.stream({ message: 'hello' })) events.push(event)

  assert.equal(events[0].event_id, 'req-1:7')
  assert.equal(events[0].seq, 7)
  assert.equal(events[0].request_id, 'req-1')
  assert.equal(events[0].source, 'gateway.http.chat')
  assert.equal(events[0].payload.type, 'text')
  assert.equal(events[0].payload.content, 'hello')
})


test('runs.stream maps legacy SSE error content', async () => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(
        'data: {"type":"error","content":"stream failed"}\n\n',
      ))
      controller.close()
    },
  })
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
  })

  await assert.rejects(
    async () => {
      for await (const _event of client.runs.stream({ message: 'hello' })) {
        // The error event must throw before it is exposed as a normal event.
      }
    },
    (error) => error instanceof PrometheaError && error.message === 'stream failed',
  )
})


test('runs.stream preserves nested memory visibility on done events', async () => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(
        'data: {"type":"done","session_id":"s1","memory_visibility":{"feedback_hints":[{"type":"memory_review_needed","proposal_id":"p1"}]}}\n\n',
      ))
      controller.close()
    },
  })
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }),
  })

  const events = []
  for await (const event of client.runs.stream({ message: 'hello' })) events.push(event)

  assert.equal(events[0].event_type, 'done')
  assert.equal(events[0].payload.memory_visibility.feedback_hints[0].proposal_id, 'p1')
})


test('AbortSignal is passed to fetch without SDK policy changes', async () => {
  const controller = new AbortController()
  controller.abort(new DOMException('Cancelled', 'AbortError'))
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (_url, init) => {
      assert.equal(init.signal, controller.signal)
      throw controller.signal.reason
    },
  })

  await assert.rejects(
    () => client.runs.run({ message: 'hello' }, controller.signal),
    (error) => error instanceof DOMException && error.name === 'AbortError',
  )
})


test('workbench.get serializes scope and returns the generated snapshot', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        version: 'workbench.v1',
        scope: { user_id: 'u1', session_id: 's1', task_id: 't1', run_id: null },
        task: null,
        tasks: [],
        runs: [],
        workflow_runs: [],
        timeline: [],
        current_activity: null,
        artifacts: [],
        waiting_actions: [],
        memory_proposals: [],
        recall_runs: [],
        recovery_items: [],
        active_runtime_runs: [],
        cursor: 7,
      })
    },
  })

  const snapshot = await client.workbench.get({ sessionId: 's1', taskId: 't1', afterSeq: 5, limit: 20 })

  assert.equal(snapshot.cursor, 7)
  assert.equal(calls[0].url, 'http://localhost:8000/api/workbench/snapshot?session_id=s1&task_id=t1&after_seq=5&limit=20')
})


test('cognition.get consumes the generated cognition contract', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        status: 'success',
        cognition: {
          version: 'self_model.cognition.v1',
          model_scope: 'self_model.cognition',
          user_id: 'u1',
          items: [{ cognition_id: 'm1', content: 'The user prefers concise answers.' }],
          stats: { total: 1 },
        },
      })
    },
  })

  const bundle = await client.cognition.get(50)

  assert.equal(bundle.items[0].cognition_id, 'm1')
  assert.equal(calls[0].url, 'http://localhost:8000/api/memory/cognition?limit=50')
})


test('task controls serialize revision and return the public task', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        status: 'success',
        task: {
          task_id: 'task/a',
          title: 'Demo',
          objective: '',
          status: 'paused',
          revision: 4,
          session_ids: [],
          source: 'user',
          runs: [],
        },
      })
    },
  })

  const task = await client.tasks.pause('task/a', { expected_revision: 3 })

  assert.equal(task.status, 'paused')
  assert.equal(calls[0].url, 'http://localhost:8000/api/tasks/task%2Fa/pause')
  assert.deepEqual(JSON.parse(calls[0].init.body), { expected_revision: 3 })
})


test('tasks.startRun returns the public run rather than workflow internals', async () => {
  const calls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({
        status: 'success',
        detached: true,
        run: {
          run_id: 'run_1',
          run_type: 'workflow',
          status: 'running',
          attempt_count: 1,
        },
      })
    },
  })

  const run = await client.tasks.startRun('task_1', {
    workflow_id: 'wf.research',
    session_id: 's1',
    expected_revision: 2,
  })

  assert.equal(run.run_id, 'run_1')
  assert.equal(calls[0].url, 'http://localhost:8000/api/tasks/task_1/runs')
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    workflow_id: 'wf.research',
    session_id: 's1',
    expected_revision: 2,
  })
})


test('workbench.stream parses typed snapshot events and forwards the cursor', async () => {
  const snapshot = {
    version: 'workbench.v1',
    scope: { user_id: 'u1', session_id: null, task_id: 't1', run_id: null },
    task: null,
    tasks: [],
    runs: [],
    workflow_runs: [],
    timeline: [],
    current_activity: null,
    artifacts: [],
    waiting_actions: [],
    memory_proposals: [],
    recall_runs: [],
    recovery_items: [],
    active_runtime_runs: [],
    cursor: 12,
  }
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(
        `id: 12\nevent: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`,
      ))
      controller.close()
    },
  })
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url) => {
      assert.equal(url, 'http://localhost:8000/api/workbench/stream?task_id=t1&after_seq=8')
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    },
  })

  const snapshots = []
  for await (const item of client.workbench.stream({ taskId: 't1', afterSeq: 8 })) snapshots.push(item)

  assert.equal(snapshots[0].cursor, 12)
})


test('workbench.watch reconnects from the last snapshot cursor', async () => {
  const urls = []
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url) => {
      urls.push(url)
      const cursor = urls.length
      const snapshot = {
        version: 'workbench.v1',
        scope: { user_id: 'u1', session_id: null, task_id: 't1', run_id: null },
        task: null,
        tasks: [],
        runs: [],
        workflow_runs: [],
        timeline: [],
        current_activity: null,
        artifacts: [],
        waiting_actions: [],
        memory_proposals: [],
        recall_runs: [],
        recovery_items: [],
        active_runtime_runs: [],
        cursor,
      }
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(
            `event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`,
          ))
          controller.close()
        },
      })
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    },
  })

  const cursors = []
  for await (const snapshot of client.workbench.watch(
    { taskId: 't1' },
    { reconnectDelayMs: 0 },
  )) {
    cursors.push(snapshot.cursor)
    if (cursors.length === 2) break
  }

  assert.deepEqual(cursors, [1, 2])
  assert.equal(urls[0], 'http://localhost:8000/api/workbench/stream?task_id=t1&after_seq=0')
  assert.equal(urls[1], 'http://localhost:8000/api/workbench/stream?task_id=t1&after_seq=1')
})

test('canvas.list consumes generated environment contracts', async () => {
  const client = new PrometheaClient({
    baseUrl: 'http://localhost:8000',
    fetch: async (url) => {
      assert.equal(url, 'http://localhost:8000/api/canvas/environments?workspace_id=session-1')
      return Response.json({
        workspace_id: 'session-1',
        environments: [{
          environment_id: 'env-1', name: 'Draft', kind: 'static',
          workspace_id: 'session-1', root: 'draft', entrypoint: 'index.html',
          status: 'running', preview_url: '/api/canvas/session-1/env-1/preview/',
        }],
      })
    },
  })
  const result = await client.canvas.list('session-1')
  assert.equal(result.environments[0].name, 'Draft')
})
