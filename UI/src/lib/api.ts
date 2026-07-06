export const getApiBaseUrl = () => {
  const win = window as any;
  return win.__APP_CONFIG__?.apiBaseUrl ||
         win.__PROMETHEA_API_BASE__ ||
         localStorage.getItem('api_base_url') ||
         '';
};

export const getAuthToken = () => sessionStorage.getItem('auth_token');
export const setAuthToken = (token: string) => sessionStorage.setItem('auth_token', token);
export const clearAuthToken = () => sessionStorage.removeItem('auth_token');

export const authFetch = async (endpoint: string, options: RequestInit = {}) => {
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});

  if (token) headers.set('Authorization', `Bearer ${token}`);
  
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${baseUrl}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (response.status === 401) {
    clearAuthToken();
    window.dispatchEvent(new Event('auth-expired'));
  }

  return response;
};

// Chat & Streaming
export const streamChat = async (
  message: string,
  sessionId: string | null,
  onEvent: (event: string, data: any) => void,
  onError: (error: Error) => void
) => {
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (token) headers.set('Authorization', `Bearer ${token}`);

  try {
    const response = await fetch(`${baseUrl}/api/chat`, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify({ message, session_id: sessionId, stream: true })
    });

    if (!response.ok) {
      if (response.status === 401) {
         clearAuthToken();
         window.dispatchEvent(new Event('auth-expired'));
      }
      throw new Error(`API Error: ${response.status}`);
    }
    if (!response.body) throw new Error('No response body');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; 

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          if (dataStr === '[DONE]') {
            onEvent('done', null);
            continue;
          }
          try {
            const payload = JSON.parse(dataStr);
            onEvent(payload?.type || 'message', payload);
          } catch (e) {
            onEvent('message', dataStr);
          }
        }
      }
    }
  } catch (err: any) {
    onError(err);
  }
};

export const confirmToolCall = (sessionId: string, toolCallId: string, action: 'approve'|'reject') => 
  authFetch('/api/chat/confirm', { method: 'POST', body: JSON.stringify({ session_id: sessionId, tool_call_id: toolCallId, action }) });

export const sendFollowup = (data: { selected_text: string, query_type: string, custom_query?: string, session_id: string }) =>
  authFetch('/api/followup', { method: 'POST', body: JSON.stringify(data) });

// Reasoning
export const getActiveReasoning = (sessionId: string) => authFetch(`/api/reasoning/active?session_id=${sessionId}&limit=5`);
export const getReasoningTree = (treeId: string) => authFetch(`/api/reasoning/tree/${treeId}`);
export const stopReasoningTree = (treeId: string, reason: string) => authFetch(`/api/reasoning/tree/${treeId}/stop`, { method: 'POST', body: JSON.stringify({ reason }) });
export const steerReasoningTree = (treeId: string, note: string) => authFetch(`/api/reasoning/tree/${treeId}/steer`, { method: 'POST', body: JSON.stringify({ note }) });

// Status & Sessions
export const getSystemStatus = () => authFetch('/api/status');
export const getToolsList = () => authFetch('/api/status/tools');
export const getSessions = (query: string = '') => authFetch(`/api/sessions?limit=200&q=${encodeURIComponent(query)}`);
export const getSession = (id: string) => authFetch(`/api/sessions/${id}`);
export const pinSession = (id: string, pinned: boolean) => authFetch(`/api/sessions/${id}/pin`, { method: 'POST', body: JSON.stringify({ pinned }) });

// Memory
export const getMemoryCapabilities = () => authFetch('/api/memory/capabilities');
export const getMemoryGraph = (sessionId?: string) => authFetch(sessionId ? `/api/memory/graph/${sessionId}` : '/api/memory/graph');
export const memoryCluster = (sessionId: string) => authFetch(`/api/memory/cluster/${sessionId}`, { method: 'POST' });
export const memorySummarize = (sessionId: string) => authFetch(`/api/memory/summarize/${sessionId}`, { method: 'POST' });
export const memoryDecay = (sessionId: string) => authFetch(`/api/memory/decay/${sessionId}`, { method: 'POST' });
export const memoryCleanup = (sessionId: string) => authFetch(`/api/memory/cleanup/${sessionId}`, { method: 'POST' });
export const getMemoryEntries = (scope: string = '', memoryTypes: string = '', q: string = '') => 
  authFetch(`/api/memory/entries?scope=${scope}&memory_types=${memoryTypes}&q=${encodeURIComponent(q)}&limit=200`);
export const updateMemoryEntry = (id: string, content: string) => authFetch(`/api/memory/entries/${id}`, { method: 'PATCH', body: JSON.stringify({ content }) });
export const deleteMemoryEntry = (id: string) => authFetch(`/api/memory/entries/${id}`, { method: 'DELETE' });
export const getMemoryDecisions = (decision: string = '') => authFetch(`/api/memory/write-decisions?decision=${decision}&limit=200`);
export const getMemoryRecallRuns = () => authFetch('/api/memory/recall/runs?limit=120');
export const getMemoryRecall = (id: string) => authFetch(`/api/memory/recall/${id}`);
export const getMemoryProposals = () => authFetch('/api/memory/write-proposals?status=pending&limit=5');
export const decideMemoryProposal = (id: string, action: string) => authFetch(`/api/memory/write-proposals/${id}/decision`, { method: 'POST', body: JSON.stringify({ action }) });

// Settings
export const getConfig = () => authFetch('/api/config');
export const updateConfig = (config: any, hotApply: boolean = false) => authFetch('/api/config/update', { method: 'POST', body: JSON.stringify({ config, options: { hot_apply: hotApply } }) });
export const diagnoseConfig = () => authFetch('/api/config/diagnose');
export const getUserChannels = () => authFetch('/api/user/channels');
export const bindUserChannel = (channel: string, account_id: string) => authFetch('/api/user/channels/bind', { method: 'POST', body: JSON.stringify({ channel, account_id }) });

// Org Brain
export const getOrgBrainStatus = () => authFetch('/api/org-brain/status');
export const ingestOrgBrainFile = (formData: FormData) => authFetch('/api/org-brain/ingest-file', { method: 'POST', body: formData });

// Plugins
export const getPluginsCatalog = () => authFetch('/api/plugins/catalog');
export const validatePlugin = (pluginId: string, config: any) => authFetch('/api/plugins/validate', { method: 'POST', body: JSON.stringify({ plugin_id: pluginId, config }) });
export const applyPlugin = (pluginId: string, enabled: boolean, config: any, validate: boolean = true) => authFetch('/api/plugins/apply', { method: 'POST', body: JSON.stringify({ plugin_id: pluginId, enabled, config, validate }) });

// Self Evolve
export const getSelfEvolveStatus = () => authFetch('/api/self-evolve/status');
export const createSelfEvolveTask = (goal: string, target_files: string[], acceptance_criteria: string) => 
  authFetch('/api/self-evolve/tasks', { method: 'POST', body: JSON.stringify({ goal, target_files, acceptance_criteria }) });

// Ops
export const getDoctor = () => authFetch('/api/config/diagnose');
export const migrateConfig = () => authFetch('/api/config/reload', { method: 'POST' });
export const getMetrics = () => authFetch('/api/metrics');

// Voice
export const sendVoicePtt = (formData: FormData) => authFetch('/api/voice/ptt', { method: 'POST', body: formData });
