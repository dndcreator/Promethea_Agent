import type { Event, RunRequest, RunResponse } from './generated/public-contracts.js'
import { errorFromPayload } from './errors.js'
import { HttpTransport } from './transport/http.js'
import { parseSse, type SseMessage } from './transport/sse.js'

type JsonObject = Record<string, unknown>

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function decodeData(message: SseMessage): unknown {
  if (message.data === '[DONE]') return { type: 'done' }
  try {
    return JSON.parse(message.data)
  } catch {
    return { content: message.data }
  }
}

function runtimeEvent(message: SseMessage, payload: unknown): Event {
  const body = isObject(payload) ? payload : { value: payload }
  return {
    event_id: typeof body.event_id === 'string' ? body.event_id : message.id,
    event_type: message.event ?? String(body.event_type ?? body.type ?? 'message'),
    occurred_at: typeof body.occurred_at === 'string' ? body.occurred_at : undefined,
    seq: typeof body.seq === 'number' ? body.seq : undefined,
    session_id: typeof body.session_id === 'string' ? body.session_id : undefined,
    run_id: typeof body.run_id === 'string' ? body.run_id : undefined,
    task_id: typeof body.task_id === 'string' ? body.task_id : undefined,
    request_id: typeof body.request_id === 'string' ? body.request_id : undefined,
    trace_id: typeof body.trace_id === 'string' ? body.trace_id : undefined,
    source: typeof body.source === 'string' ? body.source : undefined,
    payload: body,
  }
}

export class RunsClient {
  constructor(private readonly transport: HttpTransport) {}

  async run(request: RunRequest, signal?: AbortSignal): Promise<RunResponse> {
    return await this.transport.json<RunResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ ...request, stream: false }),
      signal,
    })
  }

  async *stream(request: RunRequest, signal?: AbortSignal): AsyncGenerator<Event> {
    const response = await this.transport.send('/api/chat', {
      method: 'POST',
      headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, stream: true }),
      signal,
    })
    const contentType = response.headers.get('content-type') ?? ''
    if (!contentType.includes('text/event-stream')) {
      const payload = await response.json() as RunResponse
      yield { event_type: 'done', session_id: payload.session_id, payload: { ...payload } }
      return
    }
    for await (const message of parseSse(response, signal)) {
      const payload = decodeData(message)
      const event = runtimeEvent(message, payload)
      if (event.event_type === 'error') throw errorFromPayload(payload)
      yield event
    }
  }
}
