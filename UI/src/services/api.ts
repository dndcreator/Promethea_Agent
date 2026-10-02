import {
  PrometheaClient,
  PrometheaError,
  type Attachment,
  type CognitionBundle,
  type CanvasEnvironmentList,
  type RunRequest,
  type Task,
  type UserFile,
  type WorkbenchSnapshot,
} from '@promethea/sdk'

export type {
  Event as RuntimeEvent,
  ErrorDetail as RuntimeError,
  RunRequest,
  RunResponse,
  Session,
  ToolCall,
  ToolResult,
  Task,
  WorkbenchActivity,
  WorkbenchSnapshot,
  CognitionItem,
  CognitionBundle,
  CanvasEnvironment,
  CanvasEnvironmentList,
} from '@promethea/sdk'

const DEFAULT_API_BASE = ''

function resolveApiBase(): string {
  const fromWindow = (window as unknown as { __PROMETHEA_API_BASE__?: string }).__PROMETHEA_API_BASE__
  const fromStorage = localStorage.getItem('api_base_url')
  return String(fromWindow || fromStorage || DEFAULT_API_BASE).replace(/\/+$/, '')
}

export function getAuthToken(): string {
  const sessionToken = sessionStorage.getItem('auth_token')
  if (sessionToken) return sessionToken
  return localStorage.getItem('auth_token') || ''
}

function createRuntimeClient(): PrometheaClient {
  return new PrometheaClient({
    baseUrl: resolveApiBase(),
    token: getAuthToken,
    credentials: 'include',
  })
}

async function sdkCall<T>(operation: (client: PrometheaClient) => Promise<T>): Promise<T> {
  try {
    return await operation(createRuntimeClient())
  } catch (error) {
    if (error instanceof PrometheaError && error.status === 401) {
      clearAuthToken()
      window.dispatchEvent(new Event('auth-expired'))
    }
    throw error
  }
}

export function setAuthToken(token: string, remember = true): void {
  if (!token) return
  if (remember) {
    localStorage.setItem('auth_token', token)
    sessionStorage.removeItem('auth_token')
  } else {
    sessionStorage.setItem('auth_token', token)
    localStorage.removeItem('auth_token')
  }
}

export function clearAuthToken(): void {
  sessionStorage.removeItem('auth_token')
  localStorage.removeItem('auth_token')
}

export type AuthFetchOptions = RequestInit & {
  suppressAuthExpired?: boolean
}

export async function authFetch(path: string, options: AuthFetchOptions = {}): Promise<Response> {
  const { suppressAuthExpired, ...fetchOptions } = options
  const client = createRuntimeClient()
  const response = await client.request(path, fetchOptions)
  if (response.status === 401 && !suppressAuthExpired) {
    clearAuthToken()
    window.dispatchEvent(new Event('auth-expired'))
  }
  return response
}

export function getSession(sessionId: string): Promise<Response> {
  return authFetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
}

export type FollowupRequest = {
  selected_text: string
  query_type: 'why' | 'risk' | 'alternative' | 'custom'
  custom_query?: string
  session_id: string
  message_id: string
  start_offset: number
  end_offset: number
}

export function sendFollowup(data: FollowupRequest): Promise<Response> {
  return authFetch('/api/followup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getConfig(): Promise<Response> {
  return authFetch('/api/config')
}

export function updateConfig(config: unknown): Promise<Response> {
  return authFetch('/api/config/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, options: { hot_apply: true } }),
  })
}

export function getRuntimeSecrets(): Promise<Response> {
  return authFetch('/api/config/secrets')
}

export function updateRuntimeSecrets(values: Record<string, string>): Promise<Response> {
  return authFetch('/api/config/secrets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
}

export function deleteCurrentUserAccount(): Promise<Response> {
  return authFetch('/api/user/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  })
}

export function getMetrics(): Promise<Response> {
  return authFetch('/api/metrics')
}

export function getDoctor(): Promise<Response> {
  return authFetch('/api/doctor')
}

export function getBootstrap(): Promise<Response> {
  return authFetch('/api/bootstrap')
}

export function getWelcome(lang?: string): Promise<Response> {
  const query = lang ? `?lang=${encodeURIComponent(lang)}` : ''
  return authFetch(`/api/welcome${query}`)
}

export function getCurrentAvatar(): Promise<Response> {
  return authFetch('/api/avatar/current')
}

export function uploadAvatar(formData: FormData): Promise<Response> {
  return authFetch('/api/avatar/upload', { method: 'POST', body: formData })
}

export function setAvatarEnabled(enabled: boolean): Promise<Response> {
  return authFetch('/api/avatar/current', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
}

export function clearCurrentAvatar(): Promise<Response> {
  return authFetch('/api/avatar/current', { method: 'DELETE' })
}

export async function loadAvatarAsset(assetUrl: string): Promise<Blob> {
  const response = await authFetch(assetUrl)
  if (!response.ok) throw new Error(`avatar asset status ${response.status}`)
  return response.blob()
}

export function migrateConfig(): Promise<Response> {
  return authFetch('/api/doctor/migrate-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export function getSelfEvolveStatus(): Promise<Response> {
  return authFetch('/api/self-evolve/status')
}

export type SelfEvolveCommandDraft = {
  command: string
  description: string
  test_args: Record<string, unknown>
}

export function createSelfEvolveTask(payload: {
  goal: string
  capability_id: string
  version: string
  description: string
  commands: SelfEvolveCommandDraft[]
  acceptance_criteria?: string[]
}): Promise<Response> {
  return authFetch('/api/self-evolve/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function refreshSelfEvolveSelfModel(maxCharsPerFile = 5000): Promise<Response> {
  return authFetch('/api/self-evolve/self-model/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_chars_per_file: maxCharsPerFile }),
  })
}

export function getMemoryEntries(query = ''): Promise<Response> {
  const params = new URLSearchParams({ scope: 'all', limit: '200' })
  if (query.trim()) params.set('q', query.trim())
  return authFetch(`/api/memory/entries?${params.toString()}`)
}

export async function getCognitionBundle(): Promise<CognitionBundle> {
  return sdkCall((client) => client.cognition.get(200))
}

export function listCanvasEnvironments(workspaceId = 'default'): Promise<CanvasEnvironmentList> {
  return sdkCall((client) => client.canvas.list(workspaceId))
}

export function updateMemoryEntry(memoryId: string, content: string): Promise<Response> {
  return authFetch(`/api/memory/entries/${encodeURIComponent(memoryId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export function deleteMemoryEntry(memoryId: string): Promise<Response> {
  return authFetch(`/api/memory/entries/${encodeURIComponent(memoryId)}`, { method: 'DELETE' })
}

export function getMemoryWriteProposals(status = 'pending'): Promise<Response> {
  return authFetch(`/api/memory/write-proposals?status=${encodeURIComponent(status)}&limit=200`)
}

export type MemoryProposalAction = 'confirm_write' | 'confirm_write_keep_existing' | 'ignore_once' | 'reduce_similar'

export function decideMemoryWriteProposal(proposalId: string, action: MemoryProposalAction): Promise<Response> {
  return authFetch(`/api/memory/write-proposals/${encodeURIComponent(proposalId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
}

export function searchMemoryEntries(query: string, limit = 30): Promise<Response> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return authFetch(`/api/memory/search?${params.toString()}`)
}

export function uploadUserFile(file: Blob, filename: string, sessionId?: string | null): Promise<UserFile> {
  return sdkCall((client) => client.files.upload(file, {
    filename,
    sessionId: sessionId || undefined,
  }))
}

export function listUserFiles(query = '', limit = 50): Promise<Response> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (query.trim()) params.set('q', query.trim())
  return authFetch(`/api/files?${params.toString()}`)
}

export function unifiedSearch(query: string): Promise<Response> {
  return authFetch(`/api/search?q=${encodeURIComponent(query)}&limit_sessions=20&limit_files=20`)
}

export function listWorkflows(limit = 50): Promise<Response> {
  return authFetch(`/api/workflow/list?limit=${encodeURIComponent(String(limit))}`)
}

export function listPersonalWorkflowRuns(limit = 50): Promise<Response> {
  return authFetch(`/api/personal/workflow/runs?limit=${encodeURIComponent(String(limit))}`)
}

export function listWorkflowRecovery(limit = 50): Promise<Response> {
  return authFetch(`/api/personal/workflow/recovery?limit=${encodeURIComponent(String(limit))}`)
}

export function getWorkflowRun(workflowRunId: string): Promise<Response> {
  return authFetch(`/api/workflow/run/${encodeURIComponent(workflowRunId)}`)
}

export function pauseWorkflowRun(workflowRunId: string): Promise<Response> {
  return authFetch(`/api/workflow/pause/${encodeURIComponent(workflowRunId)}`, { method: 'POST' })
}

export function resumeWorkflowRun(workflowRunId: string): Promise<Response> {
  return authFetch(`/api/workflow/resume/${encodeURIComponent(workflowRunId)}`, { method: 'POST' })
}

export function getWorkflowCheckpoints(workflowRunId: string): Promise<Response> {
  return authFetch(`/api/workflow/checkpoints/${encodeURIComponent(workflowRunId)}`)
}

export function getWorkbenchSnapshot(sessionId?: string | null, taskId?: string | null, runId?: string | null): Promise<WorkbenchSnapshot> {
  return sdkCall((client) => client.workbench.get({ sessionId, taskId, runId, limit: 160 }))
}

export async function* watchWorkbenchSnapshots(
  sessionId?: string | null,
  taskId?: string | null,
  runId?: string | null,
  signal?: AbortSignal,
): AsyncGenerator<WorkbenchSnapshot> {
  try {
    yield* createRuntimeClient().workbench.watch(
      { sessionId, taskId, runId, limit: 160 },
      {},
      signal,
    )
  } catch (error) {
    if (error instanceof PrometheaError && error.status === 401) {
      clearAuthToken()
      window.dispatchEvent(new Event('auth-expired'))
    }
    throw error
  }
}

export function pauseTask(taskId: string, expectedRevision?: number): Promise<Task> {
  return sdkCall((client) => client.tasks.pause(taskId, { expected_revision: expectedRevision }))
}

export function resumeTask(taskId: string, expectedRevision?: number): Promise<Task> {
  return sdkCall((client) => client.tasks.resume(taskId, { expected_revision: expectedRevision }))
}

export function cancelTask(taskId: string, reason = 'user_cancelled', expectedRevision?: number): Promise<Task> {
  return sdkCall((client) => client.tasks.cancel(taskId, { reason, expected_revision: expectedRevision }))
}

export function getSoulConfig(): Promise<Response> {
  return authFetch('/api/config/soul')
}

export function getOrgBrainStatus(): Promise<Response> {
  return authFetch('/api/org-brain/status')
}

export function ingestOrgBrainFile(formData: FormData): Promise<Response> {
  return authFetch('/api/org-brain/ingest-file', { method: 'POST', body: formData })
}

export function getPluginCatalog(): Promise<Response> {
  return authFetch('/api/plugins/catalog')
}

export function applyPluginConfig(pluginId: string, enabled: boolean, config: unknown): Promise<Response> {
  return authFetch('/api/plugins/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plugin_id: pluginId, enabled, config, validate: true }),
  })
}

export function getExtensionCatalog(): Promise<Response> {
  return authFetch('/api/extensions/catalog')
}

export function reloadExtensions(): Promise<Response> {
  return authFetch('/api/extensions/reload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export function getPersonalTemplates(): Promise<Response> {
  return authFetch('/api/personal/templates/catalog')
}

export function applyPersonalTemplate(templateId: string): Promise<Response> {
  return authFetch('/api/personal/templates/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ template_id: templateId, enable: true, activate: true, start_workflow: false }),
  })
}

export function exportPersonalBundle(): Promise<Response> {
  return authFetch('/api/personal/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_messages: true, include_memory: true, include_files: true, include_file_content: false }),
  })
}

export function importPersonalBundle(bundle: unknown, merge: boolean): Promise<Response> {
  return authFetch('/api/personal/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle, merge, restore_config: true, restore_sessions: true, restore_memory: true, restore_files: true }),
  })
}

export function confirmToolCall(sessionId: string, toolCallId: string, action: 'approve' | 'reject'): Promise<Response> {
  return authFetch('/api/chat/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, tool_call_id: toolCallId, action }),
  })
}

export function getActiveReasoning(sessionId: string): Promise<Response> {
  return authFetch(`/api/reasoning/active?session_id=${encodeURIComponent(sessionId)}&limit=5`)
}

export function exportPersonalWorkspaceArchive(): Promise<Response> {
  return authFetch('/api/personal/workspace/archive', { method: 'POST' })
}

export function restorePersonalWorkspaceArchive(file: File, merge = false): Promise<Response> {
  const form = new FormData()
  form.append('archive', file, file.name)
  return authFetch(`/api/personal/workspace/restore?merge=${merge ? 'true' : 'false'}`, {
    method: 'POST',
    body: form,
  })
}

export function getReasoningHistory(sessionId?: string | null, limit = 30): Promise<Response> {
  const params = new URLSearchParams({
    include_pending: 'true',
    limit: String(limit),
  })
  if (sessionId) params.set('session_id', sessionId)
  return authFetch(`/api/reasoning/active?${params.toString()}`)
}

export function getReasoningTree(treeId: string): Promise<Response> {
  return authFetch(`/api/reasoning/tree/${encodeURIComponent(treeId)}`)
}

export function stopReasoningTree(treeId: string, reason: string): Promise<Response> {
  return authFetch(`/api/reasoning/tree/${encodeURIComponent(treeId)}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export function steerReasoningTree(treeId: string, note: string): Promise<Response> {
  return authFetch(`/api/reasoning/tree/${encodeURIComponent(treeId)}/steer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
}

export function sendVoicePtt(formData: FormData): Promise<Response> {
  return authFetch('/api/voice/ptt', { method: 'POST', body: formData })
}

type StreamHandler = (event: string, data: unknown) => void

export type ChatAttachment = Attachment & { file_id: string }

export async function streamChat(
  message: string,
  sessionId: string | null,
  attachments: ChatAttachment[],
  onEvent: StreamHandler,
  onError: (error: Error) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const runRequest: RunRequest = {
      message,
      session_id: sessionId,
      stream: true,
      attachments,
      metadata: {
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
    }
    const client = createRuntimeClient()
    let sawDone = false
    for await (const event of client.runs.stream(runRequest, signal)) {
      if (event.event_type === 'done') sawDone = true
      onEvent(event.event_type, event.payload)
    }
    if (!sawDone) onEvent('done', { status: 'stream_closed' })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if (error instanceof PrometheaError && error.status === 401) {
      clearAuthToken()
      window.dispatchEvent(new Event('auth-expired'))
    }
    onError(error instanceof Error ? error : new Error(String(error)))
  }
}
