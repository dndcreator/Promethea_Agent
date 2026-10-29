import {
  PrometheaClient,
  PrometheaError,
  type Attachment,
  type CognitionBundle,
  type CanvasEnvironmentList,
  type RunRequest,
  type Task,
  type UserFile,
  type Project,
  type Session,
  type WorkbenchSnapshot,
  type GuestChatMessage,
  type GuestChatStatus,
  type AmbientSettings,
  type AmbientFeedback,
  type AmbientConfirmation,
  type SemanticSurface,
  type SemanticUIFeedback,
  type ChannelPairingRequest,
  type MemoryEmbeddingCommand,
  type RunSteerRequest,
} from '@promethea/sdk'

export type {
  AnswerUpdate,
  RunSteerResponse,
  MemoryEmbeddingStatus,
  AmbientState,
  Event as RuntimeEvent,
  GuestChatStatus,
  ErrorDetail as RuntimeError,
  RunRequest,
  RunResponse,
  Session,
  Project,
  ToolCall,
  ToolResult,
  Task,
  WorkbenchActivity,
  WorkbenchReference,
  WorkbenchSnapshot,
  CognitionItem,
  CognitionBundle,
  CanvasEnvironment,
  CanvasEnvironmentList,
  SemanticExpression,
  ChannelAccount,
  ChannelPairing,
} from '@promethea/sdk'

export const getAmbient = (sessionId: string | null, signal?: AbortSignal) => sdkCall((client) => client.ambient.get(sessionId, signal))
export const setAmbient = (sessionId: string | null, settings: AmbientSettings) => sdkCall((client) => client.ambient.configure(sessionId, settings))
export const sendAmbientFeedback = (sessionId: string, feedback: AmbientFeedback) => sdkCall((client) => client.ambient.feedback(sessionId, feedback))
export const confirmAmbient = (sessionId: string | null, command: AmbientConfirmation) => sdkCall((client) => client.ambient.confirm(sessionId, command))
export const sendSemanticFeedback = (expressionId: string, command: SemanticUIFeedback) => sdkCall((client) => client.semanticUI.feedback(expressionId, command))
export const observeSemanticSurface = (surface: SemanticSurface, signal?: AbortSignal) => sdkCall((client) => client.semanticUI.observeSurface(surface, signal))
export const listChannelAccounts = (signal?: AbortSignal) => sdkCall((client) => client.channels.list(signal))
export const pairChannelAccount = (command: ChannelPairingRequest, signal?: AbortSignal) => sdkCall((client) => client.channels.pair(command, signal))
export const unbindChannelAccount = (channel: string, signal?: AbortSignal) => sdkCall((client) => client.channels.unbind(channel, signal))
export const getMemoryEmbedding = (signal?: AbortSignal) => sdkCall((client) => client.memory.embeddingStatus(signal))
export const controlMemoryEmbedding = (command: MemoryEmbeddingCommand, signal?: AbortSignal) => sdkCall((client) => client.memory.controlEmbedding(command, signal))
export const steerChat = (sessionId: string, command: RunSteerRequest, signal?: AbortSignal) => sdkCall((client) => client.runs.steer(sessionId, command, signal))

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

function createRuntimeClient(token = getAuthToken()): PrometheaClient {
  return new PrometheaClient({
    baseUrl: resolveApiBase(),
    token,
    credentials: 'include',
  })
}

async function sdkCall<T>(operation: (client: PrometheaClient) => Promise<T>): Promise<T> {
  const token = getAuthToken()
  try {
    return await operation(createRuntimeClient(token))
  } catch (error) {
    if (error instanceof PrometheaError && error.status === 401) {
      expireAuthToken(token)
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

function expireAuthToken(expectedToken: string): void {
  if (!expectedToken || getAuthToken() !== expectedToken) return
  clearAuthToken()
  window.dispatchEvent(new Event('auth-expired'))
}

export type AuthFetchOptions = RequestInit & {
  suppressAuthExpired?: boolean
}

export async function authFetch(path: string, options: AuthFetchOptions = {}): Promise<Response> {
  const { suppressAuthExpired, ...fetchOptions } = options
  const token = getAuthToken()
  const client = createRuntimeClient(token)
  const response = await client.request(path, fetchOptions)
  if (response.status === 401 && !suppressAuthExpired) {
    expireAuthToken(token)
  }
  return response
}

export function getSession(sessionId: string): Promise<Response> {
  return authFetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
}

export async function listSessions(signal?: AbortSignal): Promise<Session[]> {
  const response = await authFetch('/api/sessions?limit=1000', { signal })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data = await response.json()
  return Array.isArray(data.sessions) ? data.sessions : []
}

export function listProjects(signal?: AbortSignal): Promise<Project[]> {
  return sdkCall(async (client) => (await client.projects.list(signal)).projects || [])
}

export function createProject(name: string): Promise<Project> {
  return sdkCall((client) => client.projects.create({ name }))
}

export function renameProject(projectId: string, name: string): Promise<Project> {
  return sdkCall((client) => client.projects.rename(projectId, { name }))
}

export function deleteProject(projectId: string): Promise<void> {
  return sdkCall((client) => client.projects.delete(projectId))
}

export function assignSessionProject(sessionId: string, projectId: string | null): Promise<void> {
  return sdkCall((client) => client.projects.assignSession(sessionId, projectId))
}

export async function setSessionPinned(sessionId: string, pinned: boolean): Promise<void> {
  const response = await authFetch(`/api/sessions/${encodeURIComponent(sessionId)}/pin`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned }),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
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

export function getConfig(signal?: AbortSignal): Promise<Response> {
  return authFetch('/api/config', { signal })
}

export function updateConfig(config: unknown): Promise<Response> {
  return authFetch('/api/config/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, options: { hot_apply: true } }),
  })
}

export function getRuntimeSecrets(signal?: AbortSignal): Promise<Response> {
  return authFetch('/api/config/secrets', { signal })
}

export function updateRuntimeSecrets(values: Record<string, string>, remove: string[] = []): Promise<Response> {
  return authFetch('/api/config/secrets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, remove }),
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

export function getWelcome(lang?: string, visitId?: string, signal?: AbortSignal): Promise<Response> {
  const query = new URLSearchParams()
  if (lang) query.set('lang', lang)
  if (visitId) query.set('visit_id', visitId)
  return authFetch(`/api/welcome?${query}`, { signal })
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

export function getCanvasClient() {
  return createRuntimeClient().canvas
}

export function getSemanticUIClient() {
  return createRuntimeClient().semanticUI
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

export function unifiedSearch(query: string, signal?: AbortSignal): Promise<Response> {
  return authFetch(`/api/search?q=${encodeURIComponent(query)}&limit_sessions=20&limit_files=20`, { signal })
}

export async function readApiResponse<T = any>(response: Response): Promise<T> {
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const message = data?.error_detail?.message || data?.detail?.message || data?.detail || data?.error || `HTTP ${response.status}`
    throw new Error(typeof message === 'string' ? message : `HTTP ${response.status}`)
  }
  return data as T
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

export function getWorkbenchArtifact(workspaceId: string, path: string, signal?: AbortSignal): Promise<Blob> {
  return sdkCall((client) => client.workbench.artifact(workspaceId, path, signal))
}

export async function* watchWorkbenchSnapshots(
  sessionId?: string | null,
  taskId?: string | null,
  runId?: string | null,
  signal?: AbortSignal,
): AsyncGenerator<WorkbenchSnapshot> {
  const token = getAuthToken()
  try {
    yield* createRuntimeClient(token).workbench.watch(
      { sessionId, taskId, runId, limit: 160 },
      {},
      signal,
    )
  } catch (error) {
    if (error instanceof PrometheaError && error.status === 401) {
      expireAuthToken(token)
    }
    throw error
  }
}

export function pauseTask(taskId: string, expectedRevision?: number): Promise<Task> {
  return sdkCall((client) => client.tasks.pause(taskId, { expected_revision: expectedRevision }))
}

export function listTasks(signal?: AbortSignal): Promise<Task[]> {
  return sdkCall((client) => client.tasks.list({ limit: 100 }, signal))
}

export function getTask(taskId: string, signal?: AbortSignal): Promise<Task> {
  return sdkCall((client) => client.tasks.get(taskId, signal))
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

export function listOrgBrainDocuments(status?: string): Promise<Response> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return authFetch(`/api/org-brain/documents${query}`)
}

export function reviewOrgBrainRevision(revisionId: string, approve: boolean): Promise<Response> {
  return authFetch('/api/org-brain/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revision_id: revisionId, approve }),
  })
}

export function exportOrgBrain(): Promise<Response> {
  return authFetch('/api/org-brain/export')
}

export function importOrgBrain(bundle: unknown): Promise<Response> {
  return authFetch('/api/org-brain/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle }),
  })
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

export type StreamHandler = (event: string, data: unknown) => void

export type ChatAttachment = Attachment & { file_id: string }

export async function streamChat(
  message: string,
  sessionId: string | null,
  attachments: ChatAttachment[],
  onEvent: StreamHandler,
  onError: (error: Error) => void,
  signal?: AbortSignal,
  multiAgent = false,
): Promise<void> {
  const token = getAuthToken()
  try {
    const runRequest: RunRequest = {
      message,
      session_id: sessionId,
      stream: true,
      attachments,
      metadata: {
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        ui_language: document.documentElement.lang || navigator.language,
        multi_agent: multiAgent,
      },
    }
    const client = createRuntimeClient(token)
    let terminal = false
    for await (const event of client.runs.stream(runRequest, signal)) {
      if (event.event_type === 'done' || event.event_type === 'error') terminal = true
      onEvent(event.event_type, event.payload)
    }
    if (!terminal && !signal?.aborted) onError(new Error('STREAM_INTERRUPTED'))
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if (error instanceof PrometheaError && error.status === 401) {
      expireAuthToken(token)
    }
    onError(error instanceof Error ? error : new Error(String(error)))
  }
}

export function getGuestChatStatus(signal?: AbortSignal): Promise<GuestChatStatus> {
  return createRuntimeClient('').runs.guestStatus(signal)
}

export async function sendGuestChat(
  messages: GuestChatMessage[], onEvent: StreamHandler, onError: (error: Error) => void, signal?: AbortSignal,
): Promise<void> {
  try {
    const result = await createRuntimeClient('').runs.guest({ messages }, signal)
    if (signal?.aborted) return
    onEvent('text', { content: result.response })
    onEvent('done', { status: 'success', usage: result.usage })
  } catch (error) {
    if (signal?.aborted) return
    onError(error instanceof Error ? error : new Error(String(error)))
  }
}
