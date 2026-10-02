import type { CanvasEnvironment, CanvasEnvironmentList } from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'

export class CanvasClient {
  constructor(private readonly transport: HttpTransport) {}

  async list(workspaceId = 'default', signal?: AbortSignal): Promise<CanvasEnvironmentList> {
    const query = new URLSearchParams({ workspace_id: workspaceId })
    const response = await this.transport.send(`/api/canvas/environments?${query.toString()}`, { signal })
    return await response.json() as CanvasEnvironmentList
  }

  previewUrl(environment: CanvasEnvironment): string {
    return environment.preview_url
  }
}
