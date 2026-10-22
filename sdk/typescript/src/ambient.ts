import type { AmbientSettings, AmbientState, AmbientFeedback, AmbientConfirmation } from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'

export class AmbientClient {
  constructor(private readonly transport: HttpTransport) {}

  get(sessionId?: string | null, signal?: AbortSignal): Promise<AmbientState> {
    return this.transport.json(sessionId ? `/api/ambient/${encodeURIComponent(sessionId)}` : '/api/ambient', { signal })
  }

  configure(sessionId: string | null, body: AmbientSettings): Promise<AmbientState> {
    return this.transport.json(sessionId ? `/api/ambient/${encodeURIComponent(sessionId)}` : '/api/ambient', { method: 'PUT', body: JSON.stringify(body) })
  }

  feedback(sessionId: string, body: AmbientFeedback): Promise<AmbientState> {
    return this.transport.json(`/api/ambient/${encodeURIComponent(sessionId)}/feedback`, { method: 'POST', body: JSON.stringify(body) })
  }

  confirm(sessionId: string | null, body: AmbientConfirmation): Promise<AmbientState> {
    return this.transport.json(sessionId ? `/api/ambient/${encodeURIComponent(sessionId)}/confirm` : '/api/ambient/confirm', { method: 'POST', body: JSON.stringify(body) })
  }
}
