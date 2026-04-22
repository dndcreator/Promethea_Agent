class AuthManager {
    constructor(apiBaseUrl, onLoginSuccess) {
        this.apiBaseUrl = apiBaseUrl;
        this.onLoginSuccess = onLoginSuccess;
        this.modal = document.getElementById('authModal');
        this.form = document.getElementById('authForm');
        this.title = document.getElementById('authTitle');
        this.submitBtn = document.getElementById('authSubmitBtn');
        this.switchLink = document.getElementById('authSwitchLink');
        this.switchText = document.getElementById('authSwitchText');
        this.agentNameGroup = document.getElementById('agentNameGroup');
        
        this.isRegister = false;
        
        this.bindEvents();
        this.updateLocalizedTexts();
        window.addEventListener("ui-language-changed", () => this.updateLocalizedTexts());
        this.checkAuth();
    }
    
    bindEvents() {
        this.switchLink.addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleMode();
        });
        
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
    }
    
    toggleMode() {
        this.isRegister = !this.isRegister;
        this.updateLocalizedTexts();
    }
    
    checkAuth() {
        const token = window.AppHttp.getAuthToken();
        if (token) {
            this.modal.style.display = 'none';
            if (this.onLoginSuccess) this.onLoginSuccess();
        } else {
            this.modal.style.display = 'flex'; // Use flex layout so the modal stays centered
            this.tryResumeWithCookie();
        }
    }

    async tryResumeWithCookie() {
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/user/profile`);
            if (!response.ok) {
                hideStartupOverlay();
                return;
            }
            const profile = await response.json().catch(() => ({}));
            if (profile?.username) {
                localStorage.setItem('username', String(profile.username));
            }
            this.modal.style.display = 'none';
            if (this.onLoginSuccess) this.onLoginSuccess();
        } catch (_) {
            hideStartupOverlay();
        }
    }
    
    async handleSubmit(e) {
        e.preventDefault();
        const formData = new FormData(this.form);
        const data = Object.fromEntries(formData.entries());
        
        const endpoint = this.isRegister ? '/api/auth/register' : '/api/auth/login';
        
        try {
            this.submitBtn.disabled = true;
            this.submitBtn.textContent = t("ui_thinking");
            
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.detail || t("auth_failed"));
            }
            
            if (this.isRegister) {
                alert(t("auth_register_success"));
                this.toggleMode();
                document.getElementById('username').value = data.username;
                document.getElementById('password').value = '';
            } else {
                window.AppHttp.setAuthToken(result.access_token || '');
                localStorage.setItem('user_id', result.user_id);
                localStorage.setItem('agent_name', result.agent_name);
                if (result.username) {
                    localStorage.setItem('username', result.username);
                }
                
                this.modal.style.display = 'none';
                if (this.onLoginSuccess) this.onLoginSuccess();
                
                const agentName = result.agent_name || 'Promethea';
                alert(t("auth_welcome_back", { agent: agentName }));
            }
            
        } catch (error) {
            alert(error.message);
        } finally {
            this.submitBtn.disabled = false;
            this.submitBtn.textContent = this.isRegister ? t("auth_submit_register") : t("auth_submit_login");
        }
    }

    updateLocalizedTexts() {
        if (this.isRegister) {
            this.title.textContent = t("auth_register");
            this.submitBtn.textContent = t("auth_submit_register");
            this.switchText.textContent = t("auth_has_account");
            this.switchLink.textContent = t("auth_switch_to_login");
            this.agentNameGroup.style.display = 'block';
        } else {
            this.title.textContent = t("auth_login");
            this.submitBtn.textContent = t("auth_submit_login");
            this.switchText.textContent = t("auth_no_account");
            this.switchLink.textContent = t("auth_switch_to_register");
            this.agentNameGroup.style.display = 'none';
        }
    }
    
    async logout(options = {}) {
        const shouldReload = options.reload !== false;
        try {
            await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/auth/logout`, { method: 'POST' });
        } catch (_) {
        }
        window.AppHttp.clearAuthToken();
        localStorage.removeItem('user_id');
        localStorage.removeItem('agent_name');
        localStorage.removeItem('username');
        if (shouldReload) {
            location.reload();
            return;
        }
        this.modal.style.display = 'flex';
    }
}

class TerminalChatApp {
    constructor() {
        this.messageInput = document.getElementById('messageInput');
        this.sendButton = document.getElementById('sendButton');
        this.chatMessages = document.getElementById('chatMessages');
        this.sessionList = document.getElementById('sessionList');
        this.sessionSearchInput = document.getElementById('sessionSearchInput');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.currentSessionEl = document.getElementById('currentSession');
        this.sessionCountEl = document.getElementById('sessionCount');
        this.connectionStatusEl = document.getElementById('connectionStatus');
        this.reasoningPanelEl = document.getElementById('reasoningPanel');
        this.reasoningTreeIdEl = document.getElementById('reasoningTreeId');
        this.reasoningStatusEl = document.getElementById('reasoningStatus');
        this.reasoningStatsEl = document.getElementById('reasoningStats');
        this.reasoningNodesEl = document.getElementById('reasoningNodes');
        this.reasoningSteerInputEl = document.getElementById('reasoningSteerInput');
        this.reasoningSteerBtn = document.getElementById('reasoningSteerBtn');
        this.reasoningStopBtn = document.getElementById('reasoningStopBtn');
        
        this.apiStatusEl = document.getElementById('apiStatus');
        this.memoryStatusEl = document.getElementById('memoryStatus');
        this.toolsLiveCountEl = document.getElementById('toolsLiveCount');
        this.toolsLiveListEl = document.getElementById('toolsLiveList');
        this.toolsLiveMetaEl = document.getElementById('toolsLiveMeta');
        this.toolsFilterInput = document.getElementById('toolsFilterInput');
        this.memorySyncIndicatorEl = document.getElementById('memorySyncIndicator');
        this.memorySyncTextEl = document.getElementById('memorySyncText');
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebarToggle');
        this.avatarPlaceholder = document.getElementById('avatarPlaceholder');
        this.logoutBtn = document.getElementById('logoutBtn');
        
        this.confirmModal = document.getElementById('confirmModal');
        this.confirmToolName = document.getElementById('confirmToolName');
        this.confirmToolArgs = document.getElementById('confirmToolArgs');
        this.approveToolBtn = document.getElementById('approveToolBtn');
        this.rejectToolBtn = document.getElementById('rejectToolBtn');
        this.pendingConfirmation = null;
        
        this.apiBaseUrl = window.AppHttp.resolveApiBase();
        this.currentSessionId = null;
        this.isTyping = false;
        this.memorySyncState = {
            pending: 0,
            queued: 0,
            active: 0,
            idle: true,
            last_error: '',
        };
        this.toolCatalog = [];
        this.statusPollTimer = null;
        this.reasoningPollTimer = null;
        this.currentReasoningTreeId = null;
        this.sessionSearchDebounceTimer = null;
        this.toolCallElements = new Map();
        this.selfEvolveManager = null;
        
        this.authManager = new AuthManager(this.apiBaseUrl, () => this.initializeApp());
        
        this.bindEvents();
    }

    setSelfEvolveManager(manager) {
        this.selfEvolveManager = manager || null;
    }
    
    async fetchWithAuth(url, options = {}) {
        const response = await window.AppHttp.authFetch(url, options);
        if (response.status === 401) {
            await this.authManager.logout({ reload: false });
            throw new Error(t("auth_invalid"));
        }
        return response;
    }
    
    async initializeApp() {
        try {
            await this.refreshCurrentUser();
            this.addWelcomeMessage();
            await this.checkApiStatus();
            await this.refreshSessions();
            this.focusInput();
            
            if (this.statusPollTimer) {
                clearInterval(this.statusPollTimer);
            }
            this.statusPollTimer = setInterval(() => this.checkApiStatus(), 5000);
        } finally {
            hideStartupOverlay();
        }
    }
    
    bindEvents() {
        this.sidebarToggle.addEventListener('click', () => {
            this.sidebar.classList.toggle('open');
        });
        
        document.querySelector('.terminal-container').addEventListener('click', () => {
            if (window.innerWidth <= 768 && this.sidebar.classList.contains('open')) {
                this.sidebar.classList.remove('open');
            }
        });

        this.sendButton.addEventListener('click', () => this.sendMessage());
        
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        this.messageInput.addEventListener('input', () => {
            this.sendButton.disabled = !this.messageInput.value.trim();
        });

        this.selectionMenu = document.getElementById('selectionMenu');
        this.quickAskBtn = document.getElementById('quickAskBtn');
        
        document.addEventListener('mouseup', (e) => this.handleTextSelection(e));
        
        this.quickAskBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent closing the menu when clicking on the button itself
            const selection = window.getSelection();
            const text = selection.toString().trim();
            if (text) {
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                
                const mark = { text: text };
                
                this.showFollowUpBubble(rect, mark);
                
                this.selectionMenu.style.display = 'none';
                window.getSelection().removeAllRanges();
            }
        });
        
        document.addEventListener('mousedown', (e) => {
            if (!this.selectionMenu.contains(e.target) && e.target !== this.quickAskBtn) {
                this.selectionMenu.style.display = 'none';
            }
        });
        
        this.newChatBtn.addEventListener('click', () => {
            this.startNewChat();
        });

        if (this.sessionSearchInput) {
            this.sessionSearchInput.addEventListener('input', () => {
                if (this.sessionSearchDebounceTimer) clearTimeout(this.sessionSearchDebounceTimer);
                this.sessionSearchDebounceTimer = setTimeout(() => this.refreshSessions(), 180);
            });
        }

        if (this.toolsFilterInput) {
            this.toolsFilterInput.addEventListener('input', () => {
                this.renderToolsList(this.toolCatalog || []);
            });
        }
        
        this.messageInput.addEventListener('focus', () => {
            this.messageInput.parentElement.classList.add('is-focused');
        });
        
        this.messageInput.addEventListener('blur', () => {
            this.messageInput.parentElement.classList.remove('is-focused');
        });

        if (this.logoutBtn) {
            this.logoutBtn.addEventListener('click', () => {
                if (this.hasPendingMemorySync()) {
                    const proceed = confirm(
                        `${t("memory_sync_wait_close")}\n${t("memory_sync_running", { pending: this.memorySyncState.pending })}`
                    );
                    if (!proceed) {
                        return;
                    }
                }
                if (confirm(t("logout_confirm"))) {
                    this.authManager.logout();
                }
            });
        }

        window.addEventListener('beforeunload', (e) => {
            if (!this.hasPendingMemorySync()) {
                return;
            }
            e.preventDefault();
            e.returnValue = t("memory_sync_wait_close");
        });

        this.approveToolBtn.addEventListener('click', () => this.handleToolConfirmation('approve'));
        this.rejectToolBtn.addEventListener('click', () => this.handleToolConfirmation('reject'));
        if (this.reasoningStopBtn) {
            this.reasoningStopBtn.addEventListener('click', () => this.stopReasoningTree());
        }
        if (this.reasoningSteerBtn) {
            this.reasoningSteerBtn.addEventListener('click', () => this.steerReasoningTree());
        }
    }

    resetReasoningPanel() {
        this.currentReasoningTreeId = null;
        if (this.reasoningPollTimer) {
            clearInterval(this.reasoningPollTimer);
            this.reasoningPollTimer = null;
        }
        if (this.reasoningPanelEl) this.reasoningPanelEl.classList.add('hidden');
        if (this.reasoningTreeIdEl) this.reasoningTreeIdEl.textContent = '-';
        if (this.reasoningStatusEl) this.reasoningStatusEl.textContent = 'idle';
        if (this.reasoningStatsEl) this.reasoningStatsEl.textContent = 'iter=0, nodes=0';
        if (this.reasoningNodesEl) this.reasoningNodesEl.textContent = '';
        if (this.reasoningSteerInputEl) this.reasoningSteerInputEl.value = '';
    }

    attachReasoningTree(treeId) {
        if (!treeId) return;
        this.currentReasoningTreeId = treeId;
        if (this.reasoningPanelEl) this.reasoningPanelEl.classList.remove('hidden');
        if (this.reasoningTreeIdEl) this.reasoningTreeIdEl.textContent = treeId.slice(0, 12);
        this.pollReasoningTree();
        if (this.reasoningPollTimer) clearInterval(this.reasoningPollTimer);
        this.reasoningPollTimer = setInterval(() => this.pollReasoningTree(), 1000);
    }

    formatReasoningPanelHtml(data) {
        const esc = (value) => String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        const prettyJson = (value) => esc(JSON.stringify(value, null, 2));
        const stats = (data && typeof data.stats === 'object' && data.stats) ? data.stats : {};
        const status = String(data?.status || 'running');
        const termination = String(stats?.termination || '');
        const runtimeOutcome = (stats && typeof stats.runtime_outcome === 'object' && stats.runtime_outcome)
            ? stats.runtime_outcome
            : ((data && typeof data.runtime_outcome === 'object' && data.runtime_outcome) ? data.runtime_outcome : null);
        const runtimeStatus = String(runtimeOutcome?.status || '').toLowerCase();
        const runtimeBadgeClass = runtimeStatus === 'failed'
            ? 'runtime-failed'
            : (runtimeStatus === 'success' ? 'runtime-success' : 'runtime-unsure');
        const statusHtml = `
            <div class="reasoning-tree-header">
                <span class="pill">status: ${esc(status)}</span>
                ${termination ? `<span class="pill">termination: ${esc(termination)}</span>` : ''}
                ${runtimeOutcome ? `<span class="pill ${runtimeBadgeClass}">runtime: ${esc(runtimeStatus || 'unknown')}</span>` : ''}
            </div>
        `;
        let runtimeHtml = '';
        if (runtimeOutcome) {
            const oStatus = String(runtimeOutcome.status || '');
            const oReason = String(runtimeOutcome.reason || '').replace(/\s+/g, ' ').trim();
            const oConf = Number(runtimeOutcome.confidence || 0);
            const suggestion = String(runtimeOutcome.suggestion || '').replace(/\s+/g, ' ').trim();
            runtimeHtml = `
                <details class="reasoning-group" open>
                    <summary>Runtime Outcome</summary>
                    <div class="reasoning-group-body">
                        <div><strong>status</strong>: ${esc(oStatus || 'unknown')}</div>
                        <div><strong>confidence</strong>: ${esc(oConf.toFixed(2))}</div>
                        ${oReason ? `<div><strong>reason</strong>: ${esc(oReason)}</div>` : ''}
                        ${suggestion ? `<div><strong>suggestion</strong>: ${esc(suggestion)}</div>` : ''}
                    </div>
                </details>
            `;
        }

        const topLevelKnown = new Set([
            'tree_id', 'session_id', 'user_id', 'root_goal', 'status',
            'created_at', 'updated_at', 'stats', 'root_node_id', 'node_count',
            'nodes', 'control', 'source',
        ]);
        const topLevelDynamic = {};
        if (data && typeof data === 'object') {
            for (const [k, v] of Object.entries(data)) {
                if (!topLevelKnown.has(k)) topLevelDynamic[k] = v;
            }
        }
        const treeDynamicHtml = Object.keys(topLevelDynamic).length > 0
            ? `
                <details class="reasoning-group">
                    <summary>Dynamic Tree Fields</summary>
                    <div class="reasoning-group-body">
                        <pre>${prettyJson(topLevelDynamic)}</pre>
                    </div>
                </details>
            `
            : '';

        const statsKnown = new Set([
            'iterations', 'memory_calls', 'tool_calls', 'think_calls',
            'tool_failures', 'termination', 'runtime_outcome', 'react_rounds',
            'react_failed_observations',
        ]);
        const statsDynamic = {};
        for (const [k, v] of Object.entries(stats || {})) {
            if (!statsKnown.has(k)) statsDynamic[k] = v;
        }
        const statsDynamicHtml = Object.keys(statsDynamic).length > 0
            ? `
                <details class="reasoning-group">
                    <summary>Dynamic Stats Fields</summary>
                    <div class="reasoning-group-body">
                        <pre>${prettyJson(statsDynamic)}</pre>
                    </div>
                </details>
            `
            : '';

        const nodes = Array.isArray(data?.nodes) ? data.nodes.slice(0, 16) : [];
        let nodesHtml = '';
        if (!nodes.length) {
            nodesHtml = `<div class="reasoning-empty">(empty)</div>`;
        } else {
            const nodeRows = [];
            for (const node of nodes) {
            const nid = String(node?.node_id || '').slice(0, 8);
            const kind = String(node?.kind || '');
            const nstatus = String(node?.status || '');
            const title = String(node?.title || '').replace(/\s+/g, ' ').trim();
                const observation = String(node?.observation || node?.summary || '').trim();

                const nodeKnown = new Set([
                    'node_id', 'parent_id', 'kind', 'title', 'status', 'observation',
                    'summary', 'updated_at', 'prompt', 'children', 'created_at',
                    'metadata', 'tool_calls', 'human_gate', 'verifier_state',
                    'checkpoint', 'evidence', 'result',
                ]);
                const nodeDynamic = {};
                if (node && typeof node === 'object') {
                    for (const [k, v] of Object.entries(node)) {
                        if (!nodeKnown.has(k)) nodeDynamic[k] = v;
                    }
                }
                const compactMeta = {
                    metadata: node?.metadata || {},
                    verifier_state: node?.verifier_state || {},
                    human_gate: node?.human_gate || {},
                    checkpoint: node?.checkpoint || {},
                    result: node?.result || {},
                    ...nodeDynamic,
                };
                const hasMeta = Object.values(compactMeta).some((v) => {
                    if (!v) return false;
                    if (Array.isArray(v)) return v.length > 0;
                    if (typeof v === 'object') return Object.keys(v).length > 0;
                    return true;
                });
                nodeRows.push(`
                    <details class="reasoning-node">
                        <summary>
                            <span class="pill">${esc(nstatus || 'unknown')}</span>
                            <span>${esc(kind)}</span>
                            <code>${esc(nid)}</code>
                            <span>${esc(title)}</span>
                        </summary>
                        <div class="reasoning-group-body">
                            ${observation ? `<div><strong>obs</strong>: ${esc(observation.replace(/\s+/g, ' ').slice(0, 360))}</div>` : ''}
                            ${hasMeta ? `<details class="reasoning-subgroup"><summary>meta</summary><pre>${prettyJson(compactMeta)}</pre></details>` : ''}
                        </div>
                    </details>
                `);
            }
            nodesHtml = nodeRows.join('');
        }

        return `
            <div class="reasoning-tree-view">
                ${statusHtml}
                ${runtimeHtml}
                ${treeDynamicHtml}
                ${statsDynamicHtml}
                <details class="reasoning-group" open>
                    <summary>Nodes (${nodes.length})</summary>
                    <div class="reasoning-group-body">${nodesHtml}</div>
                </details>
            </div>
        `;
    }

    async attachLatestReasoningForSession(sessionId) {
        if (!sessionId) return;
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/reasoning/active?session_id=${encodeURIComponent(sessionId)}&limit=5`);
            if (!response.ok) return;
            const data = await response.json();
            const items = Array.isArray(data?.items) ? data.items : [];
            const active = items.find(item => String(item?.status || '').toLowerCase() === 'running') || items[0];
            if (active?.tree_id) {
                this.attachReasoningTree(active.tree_id);
            }
        } catch (e) {
            console.warn('attach latest reasoning failed:', e);
        }
    }

    async pollReasoningTree() {
        if (!this.currentReasoningTreeId) return;
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/reasoning/tree/${this.currentReasoningTreeId}`);
            if (!response.ok) {
                if (this.reasoningPollTimer) {
                    clearInterval(this.reasoningPollTimer);
                    this.reasoningPollTimer = null;
                }
                return;
            }
            const data = await response.json();
            const status = String(data?.status || 'running');
            const stats = data?.stats || {};
            const iter = stats.iterations || 0;
            const nodes = data?.node_count || 0;
            const toolCalls = stats.tool_calls || 0;
            const thinkCalls = stats.think_calls || 0;
            const memoryCalls = stats.memory_calls || 0;
            const toolFailures = stats.tool_failures || 0;
            const reactRounds = stats.react_rounds || 0;
            if (this.reasoningStatusEl) this.reasoningStatusEl.textContent = status;
            if (this.reasoningStatsEl) {
                this.reasoningStatsEl.textContent = `iter=${iter}, nodes=${nodes}, think=${thinkCalls}, tool=${toolCalls}, mem=${memoryCalls}, fail=${toolFailures}, react=${reactRounds}`;
            }
            if (this.reasoningNodesEl) {
                this.reasoningNodesEl.innerHTML = this.formatReasoningPanelHtml(data);
            }
            if (["succeeded", "failed", "skipped"].includes(status.toLowerCase())) {
                if (this.reasoningPollTimer) {
                    clearInterval(this.reasoningPollTimer);
                    this.reasoningPollTimer = null;
                }
            }
        } catch (e) {
            console.warn('poll reasoning tree failed:', e);
        }
    }

    async stopReasoningTree() {
        if (!this.currentReasoningTreeId) return;
        try {
            await this.fetchWithAuth(`${this.apiBaseUrl}/api/reasoning/tree/${this.currentReasoningTreeId}/stop`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: 'stopped_from_web_ui' }),
            });
            await this.pollReasoningTree();
        } catch (e) {
            console.warn('stop reasoning tree failed:', e);
        }
    }

    async steerReasoningTree() {
        if (!this.currentReasoningTreeId || !this.reasoningSteerInputEl) return;
        const note = this.reasoningSteerInputEl.value.trim();
        if (!note) return;
        try {
            await this.fetchWithAuth(`${this.apiBaseUrl}/api/reasoning/tree/${this.currentReasoningTreeId}/steer`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note }),
            });
            this.reasoningSteerInputEl.value = '';
            await this.pollReasoningTree();
        } catch (e) {
            console.warn('steer reasoning tree failed:', e);
        }
    }
    
    async handleToolConfirmation(action) {
        if (!this.pendingConfirmation) return;
        
        const { session_id, tool_call_id } = this.pendingConfirmation;
        
        this.confirmModal.style.display = 'none';
        
        if (action === 'reject') {
            this.addMessage('assistant', t("ui_rejected"));
            this.sendButton.disabled = false;
            this.isTyping = false;
            this.setAvatarStatus('idle');
        } else {
            this.setAvatarStatus('thinking');
        }

        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/chat/confirm`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: session_id,
                    tool_call_id: tool_call_id,
                    action: action
                })
            });
            
            const data = await response.json();
            
            if (data.status === 'needs_confirmation') {
                this.showConfirmation(data);
            } else if (response.ok && (data.status === 'success' || data.success === true)) {
                this.addMessage('assistant', data.response, {
                    memoryVisibility: data.memory_write_summary || data.memory_visibility || null,
                });
                this.sendButton.disabled = false;
                this.isTyping = false;
                this.setAvatarStatus('idle');
            } else if (data.status === 'rejected') {
            } else {
                throw new Error(data.message || t("auth_failed"));
            }
            
        } catch (error) {
            console.error('Confirmation handling failed:', error);
            this.addMessage('assistant', `${t("auth_failed")}: ${error.message}`);
            this.sendButton.disabled = false;
            this.isTyping = false;
            this.setAvatarStatus('idle');
        }
        
        this.pendingConfirmation = null;
    }

    showConfirmation(data) {
        this.pendingConfirmation = {
            session_id: data.session_id,
            tool_call_id: data.tool_call_id
        };
        
        this.confirmToolName.textContent = data.tool_name || 'Unknown Tool';
        try {
            this.confirmToolArgs.textContent = JSON.stringify(data.args || {}, null, 2);
        } catch (e) {
            this.confirmToolArgs.textContent = String(data.args);
        }
        
        this.confirmModal.style.display = 'flex';
    }
    
    async checkApiStatus() {
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/status`);
            if (response.ok) {
                const data = await response.json();
                this.updateStatus(this.apiStatusEl, true);
                
                if (data.memory_active !== undefined) {
                    this.updateStatus(this.memoryStatusEl, data.memory_active);
                }
                this.updateMemorySyncIndicator(data.memory_sync || null);
                await this.refreshToolsList();
            } else {
                this.updateStatus(this.apiStatusEl, false);
                this.updateStatus(this.memoryStatusEl, false);
                this.updateMemorySyncIndicator(null);
                this.renderToolsList([], t("ui_tools_error"));
            }
        } catch (error) {
            this.updateStatus(this.apiStatusEl, false);
            this.updateStatus(this.memoryStatusEl, false);
            this.updateMemorySyncIndicator(null);
            this.renderToolsList([], t("ui_tools_error"));
            console.warn('Failed to connect to API service');
        }
    }
    
    async checkMemoryStatus() {
        return; 
    }
    
    updateStatus(element, isActive) {
        if (isActive) {
            element.classList.add('active');
            element.classList.remove('error');
        } else {
            element.classList.remove('active');
            element.classList.add('error');
        }
    }

    async refreshToolsList() {
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/status/tools`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            const tools = Array.isArray(data.tools) ? data.tools : [];
            this.toolCatalog = tools;
            this.renderToolsList(tools);
        } catch (error) {
            this.renderToolsList([], t("ui_tools_error"));
        }
    }

    renderToolsList(tools = [], errorMessage = "") {
        if (!this.toolsLiveListEl || !this.toolsLiveCountEl) {
            return;
        }
        const filterText = String(this.toolsFilterInput?.value || "").trim().toLowerCase();
        let visibleTools = Array.isArray(tools) ? tools.slice() : [];
        if (filterText) {
            visibleTools = visibleTools.filter((item) => {
                const name = `${String(item.service_name || "")}.${String(item.tool_name || "")}`.toLowerCase();
                const desc = String(item.description || "").toLowerCase();
                const type = String(item.tool_type || "").toLowerCase();
                return name.includes(filterText) || desc.includes(filterText) || type.includes(filterText);
            });
        }

        this.toolsLiveCountEl.textContent = String(visibleTools.length || 0);
        this.toolsLiveListEl.innerHTML = "";

        if (errorMessage) {
            const empty = document.createElement("div");
            empty.className = "tools-live-empty";
            empty.textContent = errorMessage;
            this.toolsLiveListEl.appendChild(empty);
            if (this.toolsLiveMetaEl) this.toolsLiveMetaEl.textContent = "";
            return;
        }

        if (!visibleTools.length) {
            const empty = document.createElement("div");
            empty.className = "tools-live-empty";
            empty.textContent = t("ui_tools_empty");
            this.toolsLiveListEl.appendChild(empty);
            if (this.toolsLiveMetaEl) this.toolsLiveMetaEl.textContent = "";
            return;
        }
        if (this.toolsLiveMetaEl) {
            const byType = {};
            for (const item of visibleTools) {
                const key = String(item.tool_type || "unknown");
                byType[key] = (byType[key] || 0) + 1;
            }
            const summary = Object.entries(byType)
                .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
                .map(([k, v]) => `${k}:${v}`)
                .join(" | ");
            this.toolsLiveMetaEl.textContent = t("ui_tool_types_summary", { summary });
        }

        const maxVisible = 8;
        const visible = visibleTools.slice(0, maxVisible);
        for (const item of visible) {
            const row = document.createElement("div");
            row.className = "tools-live-item";

            const header = document.createElement("div");
            header.className = "tools-live-item-row";

            const name = document.createElement("div");
            name.className = "tools-live-name";
            const serviceName = String(item.service_name || "");
            const toolName = String(item.tool_name || "");
            name.textContent = serviceName && toolName && serviceName !== toolName
                ? `${serviceName}.${toolName}`
                : (toolName || serviceName || "unknown");

            const type = document.createElement("span");
            type.className = "tools-live-type";
            type.textContent = String(item.tool_type || "unknown");

            header.appendChild(name);
            header.appendChild(type);
            row.appendChild(header);

            const description = String(item.description || "").trim();
            if (description) {
                const desc = document.createElement("div");
                desc.className = "tools-live-desc";
                desc.textContent = description;
                row.appendChild(desc);
            }

            this.toolsLiveListEl.appendChild(row);
        }

        if (visibleTools.length > maxVisible) {
            const more = document.createElement("div");
            more.className = "tools-live-empty";
            more.textContent = t("ui_tools_more", { count: visibleTools.length - maxVisible });
            this.toolsLiveListEl.appendChild(more);
        }
    }

    hasPendingMemorySync() {
        return Number(this.memorySyncState?.pending || 0) > 0;
    }

    updateMemorySyncIndicator(syncStats) {
        if (!this.memorySyncIndicatorEl || !this.memorySyncTextEl) {
            return;
        }

        const fallback = {
            enabled: false,
            pending: 0,
            queued: 0,
            active: 0,
            idle: true,
            last_error: '',
        };
        const nextState = Object.assign({}, fallback, syncStats || {});
        nextState.pending = Number(nextState.pending || 0);
        nextState.queued = Number(nextState.queued || 0);
        nextState.active = Number(nextState.active || 0);
        nextState.idle = Boolean(nextState.idle);
        nextState.last_error = String(nextState.last_error || '');
        this.memorySyncState = nextState;

        this.memorySyncIndicatorEl.classList.remove('idle', 'syncing', 'error');

        let text = t("memory_sync_idle");
        if (!nextState.enabled) {
            this.memorySyncIndicatorEl.classList.add('idle');
        } else if (nextState.last_error) {
            this.memorySyncIndicatorEl.classList.add('error');
            text = `${t("memory_sync_error")}: ${nextState.last_error}`;
        } else if (nextState.pending > 0 || !nextState.idle) {
            this.memorySyncIndicatorEl.classList.add('syncing');
            text = t("memory_sync_running", { pending: nextState.pending });
            if (nextState.active > 0 || nextState.queued > 0) {
                text += ` (${nextState.active} active / ${nextState.queued} queued)`;
            }
        } else {
            this.memorySyncIndicatorEl.classList.add('idle');
        }

        this.memorySyncTextEl.textContent = text;
        this.memorySyncIndicatorEl.title = text;
    }
    
    setAvatarStatus(status) {
        this.avatarPlaceholder.classList.remove('thinking', 'speaking');
        if (status !== 'idle') {
            this.avatarPlaceholder.classList.add(status);
        }
    }
    
    addWelcomeMessage() {
        this.addMessage('assistant', t("app_welcome"));
    }

    getMemoryUiText(key) {
        const zh = {
            hint: '璁板繂',
            title: '鏈疆璁板繂',
            open_workbench: '鎵撳紑璁板繂宸ヤ綔鍙?,
            close: '鍏抽棴',
            empty: '鏈疆娌℃湁鍙睍绀虹殑璁板繂鍙樻洿',
            recall: '鍙洖',
            write: '鍐欏叆',
            review: '寰呯‘璁?,
            feedback: '缁嗚妭',
        };
        const en = {
            hint: 'Memory',
            title: 'Memory (This Turn)',
            open_workbench: 'Open Workbench',
            close: 'Close',
            empty: 'No memory update available for this turn',
            recall: 'Recalled',
            write: 'Saved',
            review: 'Needs review',
            feedback: 'Details',
        };
        const langMap = getCurrentLang() === 'en' ? en : zh;
        return langMap[key] || key;
    }

    normalizeMemorySummary(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const notices = Array.isArray(raw.notices) ? raw.notices.filter((x) => String(x || '').trim()) : [];
        const feedbackHints = Array.isArray(raw.feedback_hints) ? raw.feedback_hints : [];
        const enabled = !!raw.enabled || notices.length > 0 || feedbackHints.length > 0;
        if (!enabled) return null;
        return {
            enabled: true,
            recalled: !!raw.recalled,
            recall_notice: String(raw.recall_notice || ''),
            write_notice: String(raw.write_notice || ''),
            review_notice: String(raw.review_notice || ''),
            notices,
            feedback_hints: feedbackHints,
        };
    }

    attachMemoryHint(messageDiv, rawSummary) {
        const summary = this.normalizeMemorySummary(rawSummary);
        if (!summary) return;
        const esc = (value) => String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        messageDiv.classList.add('with-memory-hint');

        const panel = document.createElement('details');
        panel.className = 'memory-hint-panel';

        const summaryEl = document.createElement('summary');
        summaryEl.className = 'memory-hint-trigger';
        summaryEl.textContent = this.getMemoryUiText('hint');
        panel.appendChild(summaryEl);

        const body = document.createElement('div');
        body.className = 'memory-hint-body';

        const title = document.createElement('div');
        title.className = 'memory-hint-title';
        title.textContent = this.getMemoryUiText('title');
        body.appendChild(title);

        const rows = [];
        if (summary.recall_notice) rows.push([this.getMemoryUiText('recall'), summary.recall_notice]);
        if (summary.write_notice) rows.push([this.getMemoryUiText('write'), summary.write_notice]);
        if (summary.review_notice) rows.push([this.getMemoryUiText('review'), summary.review_notice]);
        if (!rows.length && Array.isArray(summary.notices)) {
            summary.notices.slice(0, 3).forEach((n) => rows.push([this.getMemoryUiText('feedback'), String(n)]));
        }
        if (!rows.length) {
            rows.push([this.getMemoryUiText('feedback'), this.getMemoryUiText('empty')]);
        }

        rows.forEach(([label, text]) => {
            const row = document.createElement('div');
            row.className = 'memory-hint-row';
            row.innerHTML = `<span class="label">${esc(label)}</span><span class="value">${esc(text)}</span>`;
            body.appendChild(row);
        });

        if (Array.isArray(summary.feedback_hints) && summary.feedback_hints.length > 0) {
            const details = document.createElement('div');
            details.className = 'memory-hint-meta';
            const mapped = summary.feedback_hints.slice(0, 3).map((item) => {
                const type = String(item?.type || 'memory');
                const memoryType = String(item?.memory_type || '');
                const preview = String(item?.content_preview || '');
                return `鈥?${type}${memoryType ? ` (${memoryType})` : ''}${preview ? `: ${preview}` : ''}`;
            });
            details.textContent = mapped.join('\n');
            body.appendChild(details);
        }

        const actions = document.createElement('div');
        actions.className = 'memory-hint-actions';

        const openBtn = document.createElement('button');
        openBtn.type = 'button';
        openBtn.className = 'memory-action primary';
        openBtn.textContent = this.getMemoryUiText('open_workbench');
        openBtn.addEventListener('click', () => {
            const btn = document.getElementById('memoryGraphBtn');
            if (btn) btn.click();
        });

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'memory-action';
        closeBtn.textContent = this.getMemoryUiText('close');
        closeBtn.addEventListener('click', () => {
            panel.open = false;
        });

        actions.appendChild(openBtn);
        actions.appendChild(closeBtn);
        body.appendChild(actions);

        panel.appendChild(body);
        messageDiv.appendChild(panel);
    }
    
    addMessage(role, content, options = {}) {
        const animate = options.animate !== false;
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        window.AppHttp.renderMultilineText(contentDiv, content);
        
        messageDiv.appendChild(contentDiv);
        if (role === 'assistant') {
            this.attachMemoryHint(messageDiv, options.memoryVisibility || null);
        }
        this.chatMessages.appendChild(messageDiv);
        
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        
        if (role === 'assistant' && animate) {
            this.addTypingEffect(contentDiv, content);
        }
    }

    async refreshCurrentUser() {
        const usernameEl = document.getElementById('currentUsername');
        if (!usernameEl) return;

        const cached = localStorage.getItem('username');
        if (cached) {
            usernameEl.textContent = `@${cached}`;
        }

        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/user/profile`);
            if (!response.ok) return;
            const data = await response.json();
            const username = (data?.username || '').trim();
            if (username) {
                localStorage.setItem('username', username);
                usernameEl.textContent = `@${username}`;
                return;
            }
        } catch (_) {
        }

        if (!cached) {
            usernameEl.textContent = '@user';
        }
    }
    
    addTypingEffect(element, text) {
        element.innerHTML = '';
        let index = 0;
        const typeSpeed = 30;
        
        const typeWriter = () => {
            if (index < text.length) {
                const char = text[index];
                if (char === '\n') {
                    element.innerHTML += '<br>';
                } else {
                    element.innerHTML += char;
                }
                index++;
                setTimeout(typeWriter, typeSpeed);
            }
        };
        
        typeWriter();
    }
    
    async refreshSessions() {
        try {
            const q = (this.sessionSearchInput?.value || '').trim();
            const qs = q ? `?q=${encodeURIComponent(q)}&limit=200` : '?limit=200';
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions${qs}`);
            if (!response.ok) throw new Error(getCurrentLang() === 'en' ? 'Failed to fetch sessions' : '获取会话列表失败');
            
            const data = await response.json();
            const sessions = data.sessions || [];
            
            this.sessionCountEl.textContent = sessions.length;
            
            this.sessionList.innerHTML = '';
            
            if (sessions.length === 0) {
                const emptyItem = document.createElement('li');
                emptyItem.textContent = getCurrentLang() === 'en' ? 'No sessions yet' : '暂无会话历史';
                emptyItem.style.textAlign = 'center';
                emptyItem.style.color = 'var(--text-muted)';
                emptyItem.style.fontStyle = 'italic';
                this.sessionList.appendChild(emptyItem);
                return;
            }
            
            sessions.forEach(session => {
                const li = document.createElement('li');
                
                const title = session.title && String(session.title).trim()
                    ? String(session.title).trim()
                    : (session.last_message && session.last_message.trim()
                        ? session.last_message.slice(0, 32) + (session.last_message.length > 32 ? '...' : '')
                        : (getCurrentLang() === 'en' ? 'New session' : '新会话'));
                const row = document.createElement('div');
                row.className = 'session-row';

                const titleEl = document.createElement('span');
                titleEl.className = 'session-title';
                titleEl.textContent = title;
                row.appendChild(titleEl);

                const pinBtn = document.createElement('button');
                pinBtn.className = `session-pin-btn ${session.pinned ? 'active' : ''}`;
                pinBtn.textContent = session.pinned ? '鈽? : '鈽?;
                pinBtn.title = session.pinned ? t("ui_unpin") : t("ui_pin");
                pinBtn.addEventListener('click', async (evt) => {
                    evt.preventDefault();
                    evt.stopPropagation();
                    await this.setSessionPinned(session.session_id, !Boolean(session.pinned));
                });
                row.appendChild(pinBtn);
                li.appendChild(row);

                li.title = getCurrentLang() === 'en'
                    ? `Session ID: ${session.session_id}\nCreated: ${new Date(session.created_at * 1000).toLocaleString()}\nMessages: ${session.message_count}`
                    : `会话ID: ${session.session_id}\n创建时间: ${new Date(session.created_at * 1000).toLocaleString()}\n消息数量: ${session.message_count}`;
                li.dataset.sid = session.session_id;
                
                if (this.currentSessionId === session.session_id) {
                    li.classList.add('active');
                }
                
                li.addEventListener('click', () => {
                    this.switchSession(session.session_id);
                });
                
                this.sessionList.appendChild(li);
            });
            
        } catch (error) {
            console.error('刷新会话列表失败:', error);
            this.sessionCountEl.textContent = '?';
        }
    }

    async setSessionPinned(sessionId, pinned) {
        if (!sessionId) return;
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions/${encodeURIComponent(sessionId)}/pin`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pinned: Boolean(pinned) }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            await this.refreshSessions();
        } catch (error) {
            console.warn('set session pinned failed:', error);
        }
    }
    
    async switchSession(sessionId) {
        if (!sessionId || this.currentSessionId === sessionId) return;
        this.resetReasoningPanel();
        
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions/${sessionId}`);
            if (!response.ok) throw new Error(getCurrentLang() === 'en' ? 'Failed to fetch session detail' : '获取会话详情失败');
            
            const data = await response.json();
            
            this.currentSessionId = sessionId;
            this.currentSessionEl.textContent = sessionId.slice(0, 8) + '...';
            
            this.chatMessages.innerHTML = '';
            
            const messages = data.messages || [];
            if (messages.length === 0) {
                this.addWelcomeMessage();
            } else {
                messages.forEach(msg => {
                    this.addMessage(msg.role, msg.content, { animate: false });
                });
            }
            
            Array.from(this.sessionList.children).forEach(li => {
                li.classList.toggle('active', li.dataset.sid === sessionId);
            });
            
            this.focusInput();
            await this.attachLatestReasoningForSession(sessionId);
            
        } catch (error) {
            console.error('切换会话失败:', error);
            this.addMessage('assistant', t("ui_switch_session_fail", { msg: error.message }));
        }
    }
    
    startNewChat() {
        this.currentSessionId = null;
        this.currentSessionEl.textContent = t("ui_not_started");
        this.chatMessages.innerHTML = '';
        this.resetReasoningPanel();
        this.addWelcomeMessage();
        
        Array.from(this.sessionList.children).forEach(li => {
            li.classList.remove('active');
        });
        
        this.focusInput();
    }
    
    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message || this.isTyping) return;
        const streamEnabled = this.isStreamEnabled();
        this.resetReasoningPanel();
        this.selfEvolveManager?.onRunStart({
            sessionId: this.currentSessionId || '',
            message,
        });
        
        this.addMessage('user', message);
        
        this.messageInput.value = '';
        this.sendButton.disabled = true;
        this.isTyping = true;
        
        this.setAvatarStatus('thinking');
        
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = `
            <div class="tool-area"></div>
            <div class="text-area">${t("ui_thinking")}</div>
        `;
        messageDiv.appendChild(contentDiv);
        this.chatMessages.appendChild(messageDiv);
        const toolArea = contentDiv.querySelector('.tool-area');
        const textArea = contentDiv.querySelector('.text-area');
        
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    message: message,
                    session_id: this.currentSessionId || null,
                    stream: streamEnabled
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = (response.headers.get('content-type') || '').toLowerCase();
            if (!streamEnabled || !response.body || contentType.includes('application/json')) {
                const data = await response.json().catch(() => ({}));
                const text = data?.response || data?.content || data?.message || '';
                window.AppHttp.renderMultilineText(textArea, text);
                this.attachMemoryHint(
                    messageDiv,
                    data?.memory_write_summary || data?.memory_visibility || null
                );
                this.setAvatarStatus('idle');
                if (data?.session_id) {
                    this.currentSessionId = data.session_id;
                    this.currentSessionEl.textContent = data.session_id.slice(0, 8) + '...';
                }
                this.selfEvolveManager?.onRunComplete({
                    ...data,
                    user_message: message,
                });
                await this.refreshSessions();
                return;
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            
            textArea.innerHTML = '';  // clear previous thinking placeholder
            
            let doneReceived = false;
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                // Keep the unfinished SSE line in buffer for the next chunk.
                buffer = lines.pop() || '';
                for (const line of lines) {
                    let trimmed = line.trim();
                    if (!trimmed) continue;
                    if (trimmed.startsWith('data:')) {
                        trimmed = trimmed.slice(5).trim();
                    }
                    if (!trimmed || trimmed === '[DONE]') continue;

                    let data;
                    try {
                        data = JSON.parse(trimmed);
                    } catch (e) {
                        console.warn('SSE parse warning:', trimmed, e);
                        continue;
                    }

                    if (data.type === 'text') {
                        fullText += (data.content || '');

                        let displayHtml = fullText.replace(/\n/g, '<br>');

                        if (fullText.includes('<thinking>') && fullText.includes('</thinking>')) {
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;([\s\S]*?)&lt;\/thinking&gt;|<thinking>([\s\S]*?)<\/thinking>/g,
                                (match, p1, p2) => {
                                    const content = p1 || p2;
                                    return `<details class="thought-process">
                                        <summary>${t("ui_thinking_process")}</summary>
                                        <div class="thought-content">${content}</div>
                                    </details>`;
                                }
                            );
                        }

                        textArea.innerHTML = displayHtml;
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;

                        this.setAvatarStatus('speaking');
                    } else if (data.type === 'tool_detected') {
                        const hint = document.createElement('div');
                        hint.className = 'tool-hint';
                        hint.textContent = data.content || t("ui_tool_detected");
                        toolArea.appendChild(hint);
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_start') {
                        const callId = data.call_id || `${Date.now()}_${Math.random()}`;
                        const toolName = data.tool_name || 'tool';
                        const args = data.args || {};

                        const details = document.createElement('details');
                        details.className = 'tool-call running';
                        details.open = false;

                        const summary = document.createElement('summary');
                        summary.textContent = t("ui_tool_running", { name: toolName });

                        const body = document.createElement('div');
                        body.className = 'tool-call-body';
                        const argsPre = document.createElement('pre');
                        argsPre.className = 'tool-call-args';
                        try {
                            argsPre.textContent = JSON.stringify(args, null, 2);
                        } catch (_) {
                            argsPre.textContent = String(args);
                        }

                        const resultPre = document.createElement('pre');
                        resultPre.className = 'tool-call-result';
                        resultPre.textContent = '';

                        body.appendChild(argsPre);
                        body.appendChild(resultPre);
                        details.appendChild(summary);
                        details.appendChild(body);
                        toolArea.appendChild(details);
                        this.toolCallElements.set(callId, { details, summary, resultPre, startedAt: Date.now(), toolName });
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_result') {
                        const callId = data.call_id;
                        const entry = this.toolCallElements.get(callId);
                        const resultText = data.result || '';
                        if (entry) {
                            entry.resultPre.textContent = resultText;
                            entry.details.classList.remove('running');
                            entry.details.classList.add('done');
                            const elapsed = Math.max(0, Date.now() - Number(entry.startedAt || Date.now()));
                            entry.summary.textContent = `${t("ui_tool_done", { name: data.tool_name || entry.toolName || 'tool' })} 路 ${elapsed}ms`;
                        } else {
                            const fallback = document.createElement('pre');
                            fallback.className = 'tool-call-result';
                            fallback.textContent = resultText;
                            toolArea.appendChild(fallback);
                        }
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_error') {
                        this.selfEvolveManager?.onToolError(data);
                        const callId = data.call_id;
                        const entry = this.toolCallElements.get(callId);
                        if (entry) {
                            entry.details.classList.remove('running');
                            entry.details.classList.add('error');
                            const elapsed = Math.max(0, Date.now() - Number(entry.startedAt || Date.now()));
                            entry.summary.textContent = `${t("ui_tool_failed")} 路 ${elapsed}ms`;
                            entry.resultPre.textContent = String(data.content || t("ui_tool_failed"));
                        } else {
                            const err = document.createElement('div');
                            err.className = 'tool-error';
                            err.textContent = data.content || t("ui_tool_failed");
                            toolArea.appendChild(err);
                        }
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'reasoning_meta') {
                        if (data.tree_id) {
                            this.attachReasoningTree(data.tree_id);
                        }
                    } else if (data.type === 'done') {
                        const dedupeText = (text) => {
                            const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
                            const raw = (text || '').trim();
                            if (!raw) return text || '';
                            const paras = raw.split(/\n\s*\n+/).map(s => s.trim()).filter(Boolean);
                            if (!paras.length) return raw;
                            const collapsed = [];
                            for (const p of paras) {
                                if (collapsed.length && norm(collapsed[collapsed.length - 1]) === norm(p)) continue;
                                collapsed.push(p);
                            }
                            if (collapsed.length >= 2 && collapsed.length % 2 === 0) {
                                const mid = collapsed.length / 2;
                                const first = collapsed.slice(0, mid).join('\n\n');
                                const second = collapsed.slice(mid).join('\n\n');
                                if (norm(first) === norm(second)) return first;
                            }
                            return collapsed.join('\n\n');
                        };

                        fullText = dedupeText(fullText);

                        let displayHtml = fullText.replace(/\n/g, '<br>');
                        if (fullText.includes('<thinking>') && fullText.includes('</thinking>')) {
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;([\s\S]*?)&lt;\/thinking&gt;|<thinking>([\s\S]*?)<\/thinking>/g,
                                (match, p1, p2) => {
                                    const content = p1 || p2;
                                    return `<details class="thought-process">
                                        <summary>${t("ui_thinking_process")}</summary>
                                        <div class="thought-content">${content}</div>
                                    </details>`;
                                }
                            );
                        }
                        textArea.innerHTML = displayHtml;

                        this.setAvatarStatus('idle');
                        if (data.session_id) {
                            this.currentSessionId = data.session_id;
                            this.currentSessionEl.textContent = data.session_id.slice(0, 8) + '...';
                        }
                        if (data.status === 'needs_confirmation') {
                            this.showConfirmation({
                                session_id: data.session_id,
                                tool_call_id: data.tool_call_id,
                                tool_name: data.tool_name || 'reasoning.success_label',
                                args: data.args || {}
                            });
                        }
                        if (data.tree_id) {
                            this.attachReasoningTree(data.tree_id);
                        }
                        this.attachMemoryHint(
                            messageDiv,
                            data.memory_write_summary || data.memory_visibility || null
                        );
                        this.selfEvolveManager?.onRunComplete({
                            ...data,
                            user_message: message,
                        });
                        doneReceived = true;
                        break;
                    } else if (data.type === 'error') {
                        throw new Error(data.content || t("ui_error_unknown"));
                    }
                }

                if (doneReceived) break;
            }

            await this.refreshSessions();
            if (!fullText.trim() && this.currentSessionId) {
                await this.recoverAssistantTextFromSession(textArea);
            }
            
        } catch (error) {
            console.error('鍙戦€佹秷鎭け璐?', error);
            window.AppHttp.renderMultilineText(contentDiv, `${t("auth_failed")}: ${error.message}`);
            this.selfEvolveManager?.onToolError({
                tool_name: 'chat_request',
                content: error.message || String(error),
            });
            this.selfEvolveManager?.onRunComplete({
                status: 'error',
                message: error.message || String(error),
                user_message: message,
            });
            this.setAvatarStatus('idle');
        } finally {
            this.sendButton.disabled = false;
            this.isTyping = false;
            this.focusInput();
        }
    }

    isStreamEnabled() {
        const streamToggle = document.getElementById('streamMode');
        if (!streamToggle) return true;
        return !!streamToggle.checked;
    }

    async recoverAssistantTextFromSession(textArea) {
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions/${this.currentSessionId}`);
            if (!response.ok) return;
            const data = await response.json();
            const messages = Array.isArray(data?.messages) ? data.messages : [];
            for (let i = messages.length - 1; i >= 0; i--) {
                const item = messages[i] || {};
                if (item.role === 'assistant' && String(item.content || '').trim()) {
                    window.AppHttp.renderMultilineText(textArea, item.content);
                    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    break;
                }
            }
        } catch (e) {
            console.warn('recover assistant text failed:', e);
        }
    }
    
    focusInput() {
        this.messageInput.focus();
    }
    
    
    showFollowUpBubble(anchorElement, mark) {
        const existingBubble = document.querySelector('.followup-bubble');
        if (existingBubble) {
            existingBubble.remove();
        }
        
        const bubble = document.createElement('div');
        bubble.className = 'followup-bubble';
        bubble.innerHTML = `
            <div class="bubble-header">
                <span>${t("ui_followup_title")}</span>
                <button class="bubble-close">閴?/button>
            </div>
            <div class="bubble-content">
                <p class="selected-text">"${mark.text.substring(0, 50)}${mark.text.length > 50 ? '...' : ''}"</p>
                <div class="quick-actions">
                    <button class="quick-btn" data-type="why">${t("ui_followup_why")}</button>
                    <button class="quick-btn" data-type="risk">${t("ui_followup_risk")}</button>
                    <button class="quick-btn" data-type="alternative">${t("ui_followup_alt")}</button>
                </div>
                <div class="custom-query">
                    <input type="text" placeholder="${t("ui_followup_custom")}" class="custom-input">
                    <button class="send-query-btn">${t("ui_followup_send")}</button>
                </div>
                <div class="bubble-response"></div>
            </div>
        `;
        
        document.body.appendChild(bubble);
        
        let rect;
        if (anchorElement instanceof DOMRect) {
            rect = anchorElement;
        } else if (anchorElement.getBoundingClientRect) {
            rect = anchorElement.getBoundingClientRect();
        } else {
            rect = { left: 0, bottom: 0 }; // Fallback
        }

        bubble.style.position = 'absolute';
        bubble.style.left = `${rect.left}px`;
        bubble.style.top = `${rect.bottom + 5}px`;
        
        bubble.querySelector('.bubble-close').addEventListener('click', () => {
            bubble.remove();
        });
        
        bubble.querySelectorAll('.quick-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const type = btn.getAttribute('data-type');
                await this.sendFollowUpQuery(mark, type, null, bubble);
            });
        });
        
        const customInput = bubble.querySelector('.custom-input');
        const sendBtn = bubble.querySelector('.send-query-btn');
        
        sendBtn.addEventListener('click', async () => {
            const customQuery = customInput.value.trim();
            if (customQuery) {
                await this.sendFollowUpQuery(mark, 'custom', customQuery, bubble);
            }
        });
        
        customInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
                const customQuery = customInput.value.trim();
                if (customQuery) {
                    await this.sendFollowUpQuery(mark, 'custom', customQuery, bubble);
                }
            }
        });
        
        const closeOnClickOutside = (e) => {
            const anchorContains =
                anchorElement &&
                typeof anchorElement.contains === 'function' &&
                anchorElement.contains(e.target);
            if (!bubble.contains(e.target) && !anchorContains) {
                bubble.remove();
                document.removeEventListener('click', closeOnClickOutside);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', closeOnClickOutside);
        }, 100);
        
        const closeOnEsc = (e) => {
            if (e.key === 'Escape') {
                bubble.remove();
                document.removeEventListener('keydown', closeOnEsc);
            }
        };
        document.addEventListener('keydown', closeOnEsc);
    }
    
    async sendFollowUpQuery(mark, queryType, customQuery, bubble) {
        const responseDiv = bubble.querySelector('.bubble-response');
        responseDiv.innerHTML = `<p class="loading">${t("ui_thinking")}</p>`;
        
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/followup`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    selected_text: mark.text,
                    query_type: queryType,
                    custom_query: customQuery,
                    session_id: this.currentSessionId
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                responseDiv.innerHTML = '';
                const answer = document.createElement('p');
                answer.className = 'ai-response';
                window.AppHttp.renderMultilineText(answer, data.response || '');
                responseDiv.appendChild(answer);
            } else {
                throw new Error(getCurrentLang() === 'en' ? 'Follow-up request failed' : '追问请求失败');
            }
        } catch (error) {
            console.error('Follow-up request failed:', error);
            responseDiv.innerHTML = `<p class="error">${t("ui_followup_fail")}</p>`;
        }
    }
    handleTextSelection(e) {
        const selection = window.getSelection();
        const text = selection.toString().trim();
        
        if (!text || !this.chatMessages.contains(e.target)) {
            if (this.selectionMenu.contains(e.target) || e.target === this.quickAskBtn) {
                return;
            }
            this.selectionMenu.style.display = 'none';
            return;
        }
        
        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        const left = rect.left + (rect.width / 2) - 40; // 閹稿鎸崇€硅棄瀹崇痪?0px
        const top = rect.top - 40;
        
        this.selectionMenu.style.left = `${left}px`;
        this.selectionMenu.style.top = `${top}px`;
        this.selectionMenu.style.display = 'block';
    }

}

class MemoryConsoleManager {
    constructor(apiBaseUrl, graphViz) {
        this.apiBaseUrl = apiBaseUrl;
        this.graphViz = graphViz;
        this.modal = document.getElementById('memoryGraphModal');
        this.closeBtn = this.modal.querySelector('.close-modal');
        this.tabButtons = [...this.modal.querySelectorAll('.memory-tab-btn')];
        this.panels = [...this.modal.querySelectorAll('.memory-panel')];
        this.entrySearchInput = document.getElementById('memoryEntrySearchInput');
        this.scopeFilter = document.getElementById('memoryScopeFilter');
        this.entryTypeFilter = document.getElementById('memoryEntryTypeFilter');
        this.entryRefreshBtn = document.getElementById('memoryEntryRefreshBtn');
        this.entryListEl = document.getElementById('memoryEntryList');
        this.entryDetailEl = document.getElementById('memoryEntryDetail');
        this.entryEditBtn = document.getElementById('memoryEntryEditBtn');
        this.entryDeleteBtn = document.getElementById('memoryEntryDeleteBtn');
        this.profileSelect = document.getElementById('memoryProfileSelect');
        this.decisionFilter = document.getElementById('memoryDecisionFilter');
        this.decisionRefreshBtn = document.getElementById('memoryDecisionRefreshBtn');
        this.decisionTimelineEl = document.getElementById('memoryDecisionTimeline');
        this.recallSearchInput = document.getElementById('memoryRecallSearchInput');
        this.recallRefreshBtn = document.getElementById('memoryRecallRefreshBtn');
        this.recallRunListEl = document.getElementById('memoryRecallRunList');
        this.recallDetailEl = document.getElementById('memoryRecallDetail');
        this.proposalModal = document.getElementById('memoryProposalModal');
        this.proposalContentEl = document.getElementById('memoryProposalContent');
        this.proposalConflictEl = document.getElementById('memoryProposalConflict');
        this.proposalConfirmBtn = document.getElementById('memoryProposalConfirmBtn');
        this.proposalIgnoreBtn = document.getElementById('memoryProposalIgnoreBtn');
        this.proposalReduceBtn = document.getElementById('memoryProposalReduceBtn');
        this.selectedEntry = null;
        this.selectedRecallRequestId = null;
        this.activeProposal = null;
        this.pollTimer = null;
        this.bindEvents();
    }

    async apiFetch(path, options = {}) {
        const headers = { ...(options.headers || {}) };
        if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
        const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}${path}`, { ...options, headers });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data?.detail || data?.message || `HTTP ${response.status}`);
        return data;
    }

    bindEvents() {
        this.tabButtons.forEach((btn) => btn.addEventListener('click', () => this.switchTab(btn.dataset.tab || 'console')));
        this.entrySearchInput?.addEventListener('input', () => this.refreshEntries());
        this.scopeFilter?.addEventListener('change', () => this.refreshEntries());
        this.entryTypeFilter?.addEventListener('change', () => this.refreshEntries());
        this.entryRefreshBtn?.addEventListener('click', () => this.refreshEntries());
        this.entryEditBtn?.addEventListener('click', () => this.editSelectedEntry());
        this.entryDeleteBtn?.addEventListener('click', () => this.deleteSelectedEntry());
        this.profileSelect?.addEventListener('change', () => this.updateMemoryProfile());
        this.decisionFilter?.addEventListener('change', () => this.refreshWriteDecisions());
        this.decisionRefreshBtn?.addEventListener('click', () => this.refreshWriteDecisions());
        this.recallSearchInput?.addEventListener('input', () => this.refreshRecallRuns());
        this.recallRefreshBtn?.addEventListener('click', () => this.refreshRecallRuns());
        this.proposalConfirmBtn?.addEventListener('click', () => this.resolveProposal('confirm_write'));
        this.proposalIgnoreBtn?.addEventListener('click', () => this.resolveProposal('ignore_once'));
        this.proposalReduceBtn?.addEventListener('click', () => this.resolveProposal('reduce_similar'));
        this.closeBtn?.addEventListener('click', () => {
            if (this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
            this.hideProposalModal();
        });
        this.modal?.addEventListener('click', (event) => {
            if (event.target === this.modal && this.pollTimer) {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
            }
        });
    }

    switchTab(tabName) {
        const next = String(tabName || 'console');
        this.tabButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === next));
        this.panels.forEach((panel) => panel.classList.toggle('active', panel.dataset.panel === next));
        if (next === 'graph') {
            this.graphViz.onGraphTabVisible();
        }
    }

    async show(sessionId = null, preferredTab = 'graph') {
        await this.graphViz.show(sessionId || null);
        this.switchTab(preferredTab || 'graph');
        await Promise.allSettled([
            this.loadProfile(),
            this.loadCapabilities(),
            this.loadDiagnostics(),
            this.refreshEntries(),
            this.refreshWriteDecisions(),
            this.refreshRecallRuns(),
            this.pollWriteProposals(),
        ]);
        if (this.pollTimer) clearInterval(this.pollTimer);
        this.pollTimer = setInterval(() => this.pollWriteProposals(), 15000);
    }

    async loadCapabilities() {
        try {
            const data = await this.apiFetch('/api/memory/capabilities');
            const supportsGraph = Boolean(data?.capabilities?.supports_graph);
            const graphBtn = this.tabButtons.find((x) => x.dataset.tab === 'graph');
            if (graphBtn) graphBtn.style.display = supportsGraph ? '' : 'none';
            if (!supportsGraph) this.switchTab('console');
        } catch (error) {
            this.switchTab('console');
        }
    }

    async loadProfile() {
        try {
            const data = await this.apiFetch('/api/config');
            const profile = String(data?.config?.memory?.profile || 'balanced');
            if (this.profileSelect) this.profileSelect.value = profile;
        } catch (error) {
            if (this.profileSelect) this.profileSelect.value = 'balanced';
        }
    }

    async loadDiagnostics() {
        try {
            const data = await this.apiFetch('/api/config/diagnose');
            const issues = data?.issues || [];
            const warnings = data?.warnings || [];
            if (!issues.length && !warnings.length) return;
            const lines = [];
            if (issues.length) lines.push(`Issues:\n- ${issues.join('\n- ')}`);
            if (warnings.length) lines.push(`Warnings:\n- ${warnings.join('\n- ')}`);
            if (this.entryDetailEl && !this.selectedEntry) {
                this.entryDetailEl.textContent = `Memory diagnostics:\n${lines.join('\n\n')}`;
            }
        } catch (error) {
        }
    }

    async updateMemoryProfile() {
        const profile = String(this.profileSelect?.value || 'balanced');
        try {
            await this.apiFetch('/api/config/update', {
                method: 'POST',
                body: JSON.stringify({
                    config: { memory: { profile } },
                    validate: false,
                    options: { hot_apply: true },
                }),
            });
        } catch (error) {
            alert(error.message || 'Update profile failed');
        }
    }

    async refreshEntries() {
        if (!this.entryListEl) return;
        this.entryListEl.innerHTML = `<div class="memory-node-item empty">${t("memory_loading")}</div>`;
        try {
            const scope = this.scopeFilter?.value || 'all';
            const type = this.entryTypeFilter?.value || 'all';
            const q = encodeURIComponent((this.entrySearchInput?.value || '').trim());
            const typeQuery = type === 'all' ? '' : `&memory_types=${encodeURIComponent(type)}`;
            const data = await this.apiFetch(`/api/memory/entries?scope=${encodeURIComponent(scope)}${typeQuery}&q=${q}&limit=200`);
            const rows = data?.entries || [];
            if (!rows.length) {
                this.entryListEl.innerHTML = `<div class="memory-node-item empty">${t("memory_no_data")}</div>`;
                return;
            }
            this.entryListEl.innerHTML = '';
            rows.forEach((entry) => {
                const item = document.createElement('div');
                item.className = 'memory-entry-item';
                item.innerHTML = `
                    <div class="title">[${this.escapeHtml(entry.memory_type || 'memory')}] ${this.escapeHtml((entry.content || '').slice(0, 120))}</div>
                    <div class="meta">${this.escapeHtml(String(entry.created_at || '').replace('T', ' ').slice(0, 19))} | ${this.escapeHtml(entry.source_layer || '')}</div>
                `;
                item.addEventListener('click', () => this.selectEntry(entry));
                this.entryListEl.appendChild(item);
            });
        } catch (error) {
            this.entryListEl.innerHTML = `<div class="memory-node-item empty">${this.escapeHtml(error.message || 'load failed')}</div>`;
        }
    }

    selectEntry(entry) {
        this.selectedEntry = entry;
        this.entryDetailEl.innerHTML = `
            <div class="memory-detail-row"><span>ID</span><code>${this.escapeHtml(entry.memory_id || '')}</code></div>
            <div class="memory-detail-row"><span>Type</span><code>${this.escapeHtml(entry.memory_type || '')}</code></div>
            <div class="memory-detail-row"><span>Layer</span><code>${this.escapeHtml(entry.source_layer || '')}</code></div>
            <div class="memory-detail-content">${this.escapeHtml(entry.content || '')}</div>
        `;
    }

    async editSelectedEntry() {
        if (!this.selectedEntry) return;
        const next = window.prompt('Edit memory content', String(this.selectedEntry.content || ''));
        if (next === null) return;
        try {
            await this.apiFetch(`/api/memory/entries/${encodeURIComponent(this.selectedEntry.memory_id)}`, {
                method: 'PATCH',
                body: JSON.stringify({ content: next }),
            });
            await this.refreshEntries();
        } catch (error) {
            alert(error.message || 'Update failed');
        }
    }

    async deleteSelectedEntry() {
        if (!this.selectedEntry) return;
        if (!window.confirm('Delete this memory entry?')) return;
        try {
            await this.apiFetch(`/api/memory/entries/${encodeURIComponent(this.selectedEntry.memory_id)}`, { method: 'DELETE' });
            this.selectedEntry = null;
            await this.refreshEntries();
        } catch (error) {
            alert(error.message || 'Delete failed');
        }
    }

    async refreshWriteDecisions() {
        if (!this.decisionTimelineEl) return;
        this.decisionTimelineEl.innerHTML = `<div class="memory-node-item empty">${t("memory_loading")}</div>`;
        try {
            const decision = this.decisionFilter?.value || '';
            const q = decision ? `?decision=${encodeURIComponent(decision)}&limit=200` : '?limit=200';
            const data = await this.apiFetch(`/api/memory/write-decisions${q}`);
            const rows = (data?.events || []).slice().reverse();
            if (!rows.length) {
                this.decisionTimelineEl.innerHTML = `<div class="memory-node-item empty">${t("memory_no_data")}</div>`;
                return;
            }
            this.decisionTimelineEl.innerHTML = '';
            rows.forEach((item) => {
                const node = document.createElement('div');
                const decisionClass = String(item.decision || '').toLowerCase();
                node.className = `memory-timeline-item ${decisionClass}`;
                node.innerHTML = `
                    <div><strong>${this.escapeHtml(String(item.timestamp || '').replace('T', ' ').slice(0, 19))}</strong> | <code>${this.escapeHtml(item.decision || '')}</code></div>
                    <div>reason: <code>${this.escapeHtml(item.reason || '')}</code> | target: <code>${this.escapeHtml(item.target_memory_layer || '')}</code></div>
                    <div>${this.escapeHtml(item.content_preview || '')}</div>
                `;
                this.decisionTimelineEl.appendChild(node);
            });
        } catch (error) {
            this.decisionTimelineEl.innerHTML = `<div class="memory-node-item empty">${this.escapeHtml(error.message || 'load failed')}</div>`;
        }
    }

    async refreshRecallRuns() {
        if (!this.recallRunListEl) return;
        this.recallRunListEl.innerHTML = `<div class="memory-node-item empty">${t("memory_loading")}</div>`;
        try {
            const data = await this.apiFetch('/api/memory/recall/runs?limit=120');
            let rows = data?.runs || [];
            const q = String(this.recallSearchInput?.value || '').trim().toLowerCase();
            if (q) rows = rows.filter((x) => `${x.request_id || ''} ${x.query_text || ''}`.toLowerCase().includes(q));
            if (!rows.length) {
                this.recallRunListEl.innerHTML = `<div class="memory-node-item empty">${t("memory_no_data")}</div>`;
                return;
            }
            this.recallRunListEl.innerHTML = '';
            rows.slice().reverse().forEach((run) => {
                const item = document.createElement('div');
                item.className = 'memory-entry-item';
                item.innerHTML = `<div class="title">${this.escapeHtml((run.query_text || '').slice(0, 120) || '(empty query)')}</div><div class="meta">${this.escapeHtml(run.request_id || '')}</div>`;
                item.addEventListener('click', () => this.selectRecallRun(run.request_id));
                this.recallRunListEl.appendChild(item);
            });
        } catch (error) {
            this.recallRunListEl.innerHTML = `<div class="memory-node-item empty">${this.escapeHtml(error.message || 'load failed')}</div>`;
        }
    }

    async selectRecallRun(requestId) {
        try {
            const data = await this.apiFetch(`/api/memory/recall/${encodeURIComponent(requestId)}`);
            const run = data?.run || {};
            const selected = run?.memory_records || [];
            const dropped = run?.dropped_candidates || [];
            this.recallDetailEl.innerHTML = `
                <div class="memory-detail-row"><span>Request</span><code>${this.escapeHtml(run.request_id || '')}</code></div>
                <div class="memory-detail-row"><span>Query</span><code>${this.escapeHtml(run.query_text || '')}</code></div>
                <div class="memory-detail-content"><strong>Formatted Context</strong>\n${this.escapeHtml(run.formatted_context || '')}</div>
                <div class="memory-detail-content"><strong>Selected</strong>\n${this.escapeHtml(selected.map((x) => `- [${x.source_layer}] ${x.content}`).join('\n'))}</div>
                <div class="memory-detail-content"><strong>Dropped</strong>\n${this.escapeHtml(dropped.map((x) => `- [${x.reason}] ${x.content}`).join('\n'))}</div>
            `;
        } catch (error) {
            this.recallDetailEl.textContent = error.message || 'load failed';
        }
    }

    async pollWriteProposals() {
        try {
            const data = await this.apiFetch('/api/memory/write-proposals?status=pending&limit=5');
            const rows = data?.proposals || [];
            if (!rows.length) {
                this.hideProposalModal();
                return;
            }
            const top = rows[rows.length - 1];
            if (this.activeProposal?.proposal_id === top.proposal_id) return;
            this.activeProposal = top;
            this.proposalContentEl.textContent = String(top.content || '');
            const conflicts = top.conflict_candidates || [];
            this.proposalConflictEl.textContent = conflicts.length ? `Conflicts:\n${conflicts.map((x) => `- ${x}`).join('\n')}` : 'No conflicts';
            this.proposalModal.style.display = 'flex';
        } catch (error) {
            this.hideProposalModal();
        }
    }

    hideProposalModal() {
        this.activeProposal = null;
        if (this.proposalModal) this.proposalModal.style.display = 'none';
    }

    async resolveProposal(action) {
        if (!this.activeProposal) return;
        try {
            await this.apiFetch(`/api/memory/write-proposals/${encodeURIComponent(this.activeProposal.proposal_id)}/decision`, {
                method: 'POST',
                body: JSON.stringify({ action }),
            });
            this.hideProposalModal();
            await this.refreshEntries();
            await this.refreshWriteDecisions();
        } catch (error) {
            alert(error.message || 'Decision failed');
        }
    }

    escapeHtml(value) {
        return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
}

const STARTUP_OVERLAY_MIN_MS = 800;
const STARTUP_BOOT_TS = Date.now();
let STARTUP_OVERLAY_HIDDEN = false;

function hideStartupOverlay() {
    if (STARTUP_OVERLAY_HIDDEN) return;
    STARTUP_OVERLAY_HIDDEN = true;

    const elapsed = Date.now() - STARTUP_BOOT_TS;
    const delay = Math.max(0, STARTUP_OVERLAY_MIN_MS - elapsed);
    const applyHide = () => {
        const overlay = document.getElementById('startupOverlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
        document.body.classList.remove('app-loading');
    };

    if (delay > 0) {
        setTimeout(applyHide, delay);
        return;
    }
    const overlay = document.getElementById('startupOverlay');
    if (overlay) {
        overlay.style.display = 'none';
    }
    document.body.classList.remove('app-loading');
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => hideStartupOverlay(), 3500);

    try {
        const languageManager = new LanguageManager();
        languageManager.init();

        const app = new TerminalChatApp();
        const selfEvolveManager = new SelfEvolveManager(app.apiBaseUrl);
        app.setSelfEvolveManager(selfEvolveManager);
        const memoryViz = new MemoryGraphVisualization(app.apiBaseUrl);
        const memoryConsole = new MemoryConsoleManager(app.apiBaseUrl, memoryViz);
        const settingsManager = new SettingsManager(app.apiBaseUrl);
        const showcaseManager = new ShowcaseManager();
        const metricsManager = new MetricsManager(app.apiBaseUrl);
        const doctorManager = new DoctorManager(app.apiBaseUrl);
        const avatarManager = new AvatarManager();
        
        const memoryGraphBtn = document.getElementById('memoryGraphBtn');
        if (memoryGraphBtn) {
            memoryGraphBtn.addEventListener('click', (event) => {
                if (event.altKey) {
                    memoryConsole.show(null, 'graph');
                    return;
                }
                memoryConsole.show(app.currentSessionId || null, 'graph');
            });
        }

        window.addEventListener('resize', () => {
            memoryViz.onGraphTabVisible();
        });

        const settingsBtn = document.getElementById('settingsBtn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => {
                settingsManager.show();
            });
        }
        void showcaseManager;
        void metricsManager;
        void doctorManager;
        void avatarManager;
    } catch (error) {
        console.error('UI bootstrap failed:', error);
        hideStartupOverlay();
    }
});

