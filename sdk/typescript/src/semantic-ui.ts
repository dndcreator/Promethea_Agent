import type { SemanticExpression, SemanticSurface, SemanticUIFeedback, SemanticUIState } from './generated/public-contracts.js'
import type { HttpTransport } from './transport/http.js'

export class SemanticUIClient {
  constructor(private readonly transport: HttpTransport) {}

  get(signal?: AbortSignal): Promise<SemanticUIState> {
    return this.transport.json('/api/semantic-ui', { signal })
  }

  feedback(expressionId: string, command: SemanticUIFeedback, signal?: AbortSignal): Promise<SemanticExpression> {
    return this.transport.json(`/api/semantic-ui/${encodeURIComponent(expressionId)}/feedback`, {
      method: 'POST', body: JSON.stringify(command), signal,
    })
  }

  observeSurface(surface: SemanticSurface, signal?: AbortSignal): Promise<{ ok: boolean }> {
    return this.transport.json('/api/semantic-ui/context', { method: 'POST', body: JSON.stringify(surface), signal, keepalive: true })
  }
}
