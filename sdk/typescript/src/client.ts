import { RunsClient } from './runs.js'
import { CognitionClient } from './cognition.js'
import { FilesClient } from './files.js'
import { SessionsClient } from './sessions.js'
import { TasksClient } from './tasks.js'
import { HttpTransport, type HttpTransportOptions } from './transport/http.js'
import { WorkbenchClient } from './workbench.js'
import { CanvasClient } from './canvas.js'
import { ProjectsClient } from './projects.js'
import { AmbientClient } from './ambient.js'
import { SemanticUIClient } from './semantic-ui.js'
import { ChannelsClient } from './channels.js'
import { MemoryClient } from './memory.js'

export type PrometheaClientOptions = HttpTransportOptions

export class PrometheaClient {
  readonly runs: RunsClient
  readonly files: FilesClient
  readonly sessions: SessionsClient
  readonly tasks: TasksClient
  readonly workbench: WorkbenchClient
  readonly cognition: CognitionClient
  readonly canvas: CanvasClient
  readonly projects: ProjectsClient
  readonly ambient: AmbientClient
  readonly semanticUI: SemanticUIClient
  readonly channels: ChannelsClient
  readonly memory: MemoryClient
  private readonly transport: HttpTransport

  constructor(options: PrometheaClientOptions) {
    this.transport = new HttpTransport(options)
    this.runs = new RunsClient(this.transport)
    this.files = new FilesClient(this.transport)
    this.sessions = new SessionsClient(this.transport)
    this.tasks = new TasksClient(this.transport)
    this.workbench = new WorkbenchClient(this.transport)
    this.cognition = new CognitionClient(this.transport)
    this.canvas = new CanvasClient(this.transport)
    this.projects = new ProjectsClient(this.transport)
    this.ambient = new AmbientClient(this.transport)
    this.semanticUI = new SemanticUIClient(this.transport)
    this.channels = new ChannelsClient(this.transport)
    this.memory = new MemoryClient(this.transport)
  }

  /** Send an endpoint-specific request while preserving the raw HTTP response. */
  async request(path: string, init: RequestInit = {}): Promise<Response> {
    return await this.transport.request(path, init)
  }
}
