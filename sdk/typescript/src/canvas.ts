import type { CanvasEnvironment, CanvasEnvironmentList, CanvasState, CanvasStateWrite, CanvasInteraction, CanvasSemanticSnapshot } from './generated/public-contracts.js'
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

  private path(environment: Pick<CanvasEnvironment, 'workspace_id' | 'environment_id'>): string {
    return `/api/canvas/${encodeURIComponent(environment.workspace_id)}/${encodeURIComponent(environment.environment_id)}`
  }

  getState(environment: CanvasEnvironment): Promise<CanvasState> {
    return this.transport.json(`${this.path(environment)}/state`)
  }

  setState(environment: CanvasEnvironment, state: CanvasStateWrite): Promise<CanvasState> {
    return this.transport.json(`${this.path(environment)}/state`, { method: 'PUT', body: JSON.stringify(state) })
  }

  semantics(environment: CanvasEnvironment): Promise<CanvasSemanticSnapshot> {
    return this.transport.json(`${this.path(environment)}/semantics`)
  }

  interact(environment: CanvasEnvironment, command: CanvasInteraction): Promise<CanvasState> {
    return this.transport.json(`${this.path(environment)}/interact`, { method: 'POST', body: JSON.stringify(command) })
  }

  retain(environment: CanvasEnvironment): Promise<CanvasEnvironment> {
    return this.transport.json(`${this.path(environment)}/retain`, { method: 'POST' })
  }

  remove(environment: CanvasEnvironment): Promise<unknown> {
    return this.transport.json(this.path(environment), { method: 'DELETE' })
  }

  reportError(environment: CanvasEnvironment, message: string): Promise<unknown> {
    return this.transport.json(`${this.path(environment)}/diagnostics`, { method: 'POST', body: JSON.stringify({ message: message.slice(0, 2000) }) })
  }
}
