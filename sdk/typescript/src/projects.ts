import type { Project, ProjectList, ProjectWrite } from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'

export class ProjectsClient {
  constructor(private readonly transport: HttpTransport) {}

  list(signal?: AbortSignal): Promise<ProjectList> {
    return this.transport.json('/api/projects', { signal })
  }

  create(body: ProjectWrite): Promise<Project> {
    return this.transport.json('/api/projects', { method: 'POST', body: JSON.stringify(body) })
  }

  rename(projectId: string, body: ProjectWrite): Promise<Project> {
    return this.transport.json(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'PATCH', body: JSON.stringify(body) })
  }

  async delete(projectId: string): Promise<void> {
    await this.transport.send(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' })
  }

  async assignSession(sessionId: string, projectId: string | null): Promise<void> {
    await this.transport.send(`/api/sessions/${encodeURIComponent(sessionId)}/project`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: projectId }) })
  }
}
