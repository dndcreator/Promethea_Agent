import type { MemoryEmbeddingCommand, MemoryEmbeddingStatus } from './generated/public-contracts.js'
import type { HttpTransport } from './transport/http.js'

export class MemoryClient {
  constructor(private readonly transport: HttpTransport) {}

  embeddingStatus(signal?: AbortSignal): Promise<MemoryEmbeddingStatus> {
    return this.transport.json('/api/memory/embedding', { signal })
  }

  controlEmbedding(command: MemoryEmbeddingCommand, signal?: AbortSignal): Promise<MemoryEmbeddingStatus> {
    return this.transport.json('/api/memory/embedding', { method: 'POST', body: JSON.stringify(command), signal })
  }
}
