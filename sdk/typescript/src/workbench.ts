import type { WorkbenchSnapshot } from './generated/public-contracts.js'
import { PrometheaError } from './errors.js'
import { HttpTransport } from './transport/http.js'
import { parseSse } from './transport/sse.js'


export interface WorkbenchQuery {
  sessionId?: string | null
  taskId?: string | null
  runId?: string | null
  afterSeq?: number
  limit?: number
}

export interface WorkbenchWatchOptions {
  reconnectDelayMs?: number
}


export class WorkbenchClient {
  constructor(private readonly transport: HttpTransport) {}

  async get(query: WorkbenchQuery = {}, signal?: AbortSignal): Promise<WorkbenchSnapshot> {
    return await this.transport.json<WorkbenchSnapshot>(this.path('/api/workbench/snapshot', query), { signal })
  }

  async *stream(query: WorkbenchQuery = {}, signal?: AbortSignal): AsyncGenerator<WorkbenchSnapshot> {
    const response = await this.transport.send(this.path('/api/workbench/stream', query), {
      headers: { Accept: 'text/event-stream' },
      signal,
    })
    for await (const message of parseSse(response, signal)) {
      if (message.event && message.event !== 'snapshot') continue
      yield JSON.parse(message.data) as WorkbenchSnapshot
    }
  }

  async *watch(
    query: WorkbenchQuery = {},
    options: WorkbenchWatchOptions = {},
    signal?: AbortSignal,
  ): AsyncGenerator<WorkbenchSnapshot> {
    let cursor = query.afterSeq ?? 0
    const reconnectDelayMs = Math.max(0, options.reconnectDelayMs ?? 1000)
    while (!signal?.aborted) {
      try {
        for await (const snapshot of this.stream({ ...query, afterSeq: cursor }, signal)) {
          cursor = Math.max(cursor, snapshot.cursor ?? 0)
          yield snapshot
        }
      } catch (error) {
        if (signal?.aborted) return
        if (error instanceof PrometheaError && !error.retryable) throw error
      }
      await wait(reconnectDelayMs, signal)
    }
  }

  private path(base: string, query: WorkbenchQuery): string {
    const params = new URLSearchParams()
    if (query.sessionId) params.set('session_id', query.sessionId)
    if (query.taskId) params.set('task_id', query.taskId)
    if (query.runId) params.set('run_id', query.runId)
    if (query.afterSeq !== undefined) params.set('after_seq', String(query.afterSeq))
    if (query.limit !== undefined) params.set('limit', String(query.limit))
    const suffix = params.size > 0 ? `?${params.toString()}` : ''
    return `${base}${suffix}`
  }
}


async function wait(delayMs: number, signal?: AbortSignal): Promise<void> {
  if (delayMs <= 0) return
  if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError')
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, delayMs)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
