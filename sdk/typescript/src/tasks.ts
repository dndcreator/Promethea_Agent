import type {
  Task,
  TaskCancelRequest,
  TaskControlRequest,
  TaskListResponse,
  TaskResponse,
  TaskRun,
  TaskRunResponse,
  TaskStartRunRequest,
} from './generated/public-contracts.js'
import { HttpTransport } from './transport/http.js'


export interface TaskListOptions {
  status?: string
  limit?: number
}


export class TasksClient {
  constructor(private readonly transport: HttpTransport) {}

  async get(taskId: string, signal?: AbortSignal): Promise<Task> {
    const response = await this.transport.json<TaskResponse>(
      `/api/tasks/${encodeURIComponent(taskId)}`,
      { signal },
    )
    return response.task
  }

  async list(options: TaskListOptions = {}, signal?: AbortSignal): Promise<Array<Task>> {
    const params = new URLSearchParams()
    if (options.status) params.set('status', options.status)
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    const query = params.size > 0 ? `?${params.toString()}` : ''
    const response = await this.transport.json<TaskListResponse>(`/api/tasks${query}`, { signal })
    return response.tasks ?? []
  }

  async startRun(taskId: string, request: TaskStartRunRequest, signal?: AbortSignal): Promise<TaskRun> {
    const response = await this.transport.json<TaskRunResponse>(
      `/api/tasks/${encodeURIComponent(taskId)}/runs`,
      { method: 'POST', body: JSON.stringify(request), signal },
    )
    return response.run
  }

  async pause(taskId: string, request: TaskControlRequest = {}, signal?: AbortSignal): Promise<Task> {
    return await this.control(taskId, 'pause', request, signal)
  }

  async resume(taskId: string, request: TaskControlRequest = {}, signal?: AbortSignal): Promise<Task> {
    return await this.control(taskId, 'resume', request, signal)
  }

  async cancel(taskId: string, request: TaskCancelRequest = {}, signal?: AbortSignal): Promise<Task> {
    return await this.control(taskId, 'cancel', request, signal)
  }

  private async control(
    taskId: string,
    operation: 'pause' | 'resume' | 'cancel',
    request: TaskControlRequest | TaskCancelRequest,
    signal?: AbortSignal,
  ): Promise<Task> {
    const response = await this.transport.json<TaskResponse>(
      `/api/tasks/${encodeURIComponent(taskId)}/${operation}`,
      { method: 'POST', body: JSON.stringify(request), signal },
    )
    return response.task
  }
}
