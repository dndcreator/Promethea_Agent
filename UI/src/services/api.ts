const DEFAULT_API_BASE = ''

function resolveApiBase(): string {
  const fromWindow = (window as unknown as { __PROMETHEA_API_BASE__?: string }).__PROMETHEA_API_BASE__
  const fromStorage = localStorage.getItem('api_base_url')
  return String(fromWindow || fromStorage || DEFAULT_API_BASE).replace(/\/+$/, '')
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  const base = resolveApiBase()
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export function getAuthToken(): string {
  const sessionToken = sessionStorage.getItem('auth_token')
  if (sessionToken) return sessionToken
  return localStorage.getItem('auth_token') || ''
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

export function buildAuthHeaders(headers?: HeadersInit): HeadersInit {
  const out = new Headers(headers || {})
  const token = getAuthToken()
  if (token && !out.has('Authorization')) out.set('Authorization', `Bearer ${token}`)
  return out
}

export type AuthFetchOptions = RequestInit & {
  suppressAuthExpired?: boolean
}

export async function authFetch(path: string, options: AuthFetchOptions = {}): Promise<Response> {
  const { suppressAuthExpired, ...fetchOptions } = options
  const response = await fetch(buildUrl(path), {
    ...fetchOptions,
    headers: buildAuthHeaders(fetchOptions.headers),
    credentials: fetchOptions.credentials || 'include',
  })
  if (response.status === 401 && !suppressAuthExpired) {
    clearAuthToken()
    window.dispatchEvent(new Event('auth-expired'))
  }
  return response
}

export function getSession(sessionId: string): Promise<Response> {
  return authFetch(`/api/sessions/${encodeURIComponent(sessionId)}`)
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

export function createSelfEvolveTask(goal: string, targetFiles: string[], acceptanceCriteria: string[]): Promise<Response> {
  return authFetch('/api/self-evolve/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal, target_files: targetFiles, acceptance_criteria: acceptanceCriteria }),
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

export function getMemoryWriteDecisions(): Promise<Response> {
  return authFetch('/api/memory/write-decisions?limit=200')
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

export function getMemoryRecallRuns(): Promise<Response> {
  return authFetch('/api/memory/recall/runs?limit=120')
}

export function getMemoryRecallRun(requestId: string): Promise<Response> {
  return authFetch(`/api/memory/recall/${encodeURIComponent(requestId)}`)
}

export function getMemoryGraph(sessionId?: string | null): Promise<Response> {
  return authFetch(sessionId ? `/api/memory/graph/${encodeURIComponent(sessionId)}` : '/api/memory/graph')
}

export function searchMemoryEntries(query: string, limit = 30): Promise<Response> {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  return authFetch(`/api/memory/search?${params.toString()}`)
}

export function searchMemoryGraph(query: string, depth = 1, limitNodes = 80, limitEdges = 160): Promise<Response> {
  const params = new URLSearchParams({
    q: query,
    depth: String(depth),
    limit_nodes: String(limitNodes),
    limit_edges: String(limitEdges),
  })
  return authFetch(`/api/memory/graph/search?${params.toString()}`)
}

export function uploadUserFile(formData: FormData): Promise<Response> {
  return authFetch('/api/files/upload', { method: 'POST', body: formData })
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

export type ChatAttachment = {
  file_id: string
  filename?: string
  modality?: string
  text_extraction_status?: string
}

export async function streamChat(
  message: string,
  sessionId: string | null,
  attachments: ChatAttachment[],
  onEvent: StreamHandler,
  onError: (error: Error) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const response = await authFetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId, stream: true, attachments }),
      signal,
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const contentType = response.headers.get('content-type') || ''
    if (!response.body || contentType.includes('application/json')) {
      const data = await response.json().catch(() => ({}))
      onEvent('text', { content: data.response || data.content || data.message || '' })
      onEvent('done', data)
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let sawDone = false
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        let trimmed = line.trim()
        if (!trimmed) continue
        if (trimmed.startsWith('data:')) trimmed = trimmed.slice(5).trim()
        if (!trimmed || trimmed === '[DONE]') continue
        const data = JSON.parse(trimmed)
        if (String(data.type || '') === 'done') sawDone = true
        onEvent(String(data.type || 'message'), data)
      }
    }
    if (!sawDone) onEvent('done', { status: 'stream_closed' })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    onError(error instanceof Error ? error : new Error(String(error)))
  }
}
