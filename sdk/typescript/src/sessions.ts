import type { Session } from './generated/public-contracts.js'
import { PrometheaError } from './errors.js'
import { HttpTransport } from './transport/http.js'

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export class SessionsClient {
  constructor(private readonly transport: HttpTransport) {}

  async get(sessionId: string, signal?: AbortSignal): Promise<Session> {
    const payload = await this.transport.json<Record<string, unknown>>(
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      { signal },
    )
    const info = isObject(payload.session_info) ? payload.session_info : payload
    const resolvedId = typeof payload.session_id === 'string' ? payload.session_id : sessionId
    if (!resolvedId) {
      throw new PrometheaError({
        code: 'invalid_response',
        message: 'Session response did not include a session_id',
      })
    }
    return { ...info, session_id: resolvedId } as Session
  }
}
