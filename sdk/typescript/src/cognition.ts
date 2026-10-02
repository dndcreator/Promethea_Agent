import type { CognitionBundle, CognitionResponse } from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'


export class CognitionClient {
  constructor(private readonly transport: HttpTransport) {}

  async get(limit = 200, signal?: AbortSignal): Promise<CognitionBundle> {
    const params = new URLSearchParams({ limit: String(limit) })
    const payload = await this.transport.json<CognitionResponse>(`/api/memory/cognition?${params.toString()}`, { signal })
    return payload.cognition
  }
}
