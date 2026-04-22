class SelfEvolveManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('selfEvolveModal');
        this.openBtn = document.getElementById('selfEvolveBtn');
        this.closeBtn = this.modal?.querySelector('.close-modal') || null;
        this.refreshBtn = document.getElementById('selfEvolveRefreshBtn');
        this.statusLine = document.getElementById('selfEvolveStatusLine');
        this.issuesEl = document.getElementById('selfEvolveIssues');
        this.optionsEl = document.getElementById('selfEvolveOptions');
        this.resultEl = document.getElementById('selfEvolveResult');

        this.enabled = false;
        this.profile = {};
        this.activeRun = null;
        this.latestIssues = [];
        this.latestOptions = [];
        this.lastPromptTs = 0;
        this.promptCooldownMs = 30000;

        this.bindEvents();
    }

    bindEvents() {
        this.openBtn?.addEventListener('click', () => this.show());
        this.closeBtn?.addEventListener('click', () => this.hide());
        this.refreshBtn?.addEventListener('click', () => this.refreshStatus());
        this.optionsEl?.addEventListener('click', (event) => this.handleOptionAction(event));
        this.modal?.addEventListener('click', (event) => {
            if (event.target === this.modal) this.hide();
        });
    }

    async show() {
        if (!this.modal) return;
        this.modal.style.display = 'flex';
        await this.refreshStatus();
        this.renderIssues(this.latestIssues);
        this.renderOptions(this.latestOptions);
    }

    hide() {
        if (!this.modal) return;
        this.modal.style.display = 'none';
    }

    getAuthHeaders() {
        return window.AppHttp?.buildAuthHeaders ? window.AppHttp.buildAuthHeaders() : {};
    }

    async refreshStatus() {
        try {
            this.setStatusLine('Status: loading...');
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/self-evolve/status`, {
                headers: this.getAuthHeaders(),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || `HTTP ${response.status}`);
            }
            const summary = data?.self_evolve || {};
            this.enabled = !!summary.enabled;
            this.profile = summary.profile || {};
            const total = Number(summary?.task_stats?.total || 0);
            const state = this.enabled ? 'enabled' : 'disabled';
            this.setStatusLine(`Status: ${state} | tasks=${total}`);
            this.writeResult({ status: 'success', action: 'status', payload: summary });
            return summary;
        } catch (error) {
            this.setStatusLine(`Status: error (${error.message || String(error)})`);
            this.writeResult({ status: 'error', action: 'status', error: error.message || String(error) });
            return null;
        }
    }

    setStatusLine(text) {
        if (this.statusLine) this.statusLine.textContent = String(text || '');
    }

    writeResult(payload) {
        if (!this.resultEl) return;
        this.resultEl.textContent = JSON.stringify(payload || {}, null, 2);
    }

    onRunStart({ sessionId = '', message = '' } = {}) {
        this.activeRun = {
            sessionId: String(sessionId || ''),
            message: String(message || ''),
            startedAt: Date.now(),
            issues: [],
        };
    }

    onToolError(data) {
        if (!this.activeRun) return;
        const toolName = String(data?.tool_name || 'tool');
        const content = String(data?.content || 'tool error');
        this.activeRun.issues.push({
            type: 'tool_error',
            title: `Tool failed: ${toolName}`,
            detail: content,
            severity: 'high',
            ts: Date.now(),
        });
    }

    onRunComplete(payload = {}) {
        if (!this.activeRun) return;
        const normalized = payload && typeof payload === 'object' ? payload : {};
        this.collectCompletionIssues(normalized);
        const issues = Array.isArray(this.activeRun.issues) ? this.activeRun.issues.slice() : [];
        this.latestIssues = issues;
        const options = this.buildOptions(issues, normalized);
        this.latestOptions = options;
        this.renderIssues(issues);
        this.renderOptions(options);
        this.tryPromptForEvolution(issues, options);
        this.activeRun = null;
    }

    collectCompletionIssues(payload) {
        if (!this.activeRun) return;
        const status = String(payload.status || '').toLowerCase();
        if (status === 'needs_confirmation') {
            this.activeRun.issues.push({
                type: 'risk_confirmation',
                title: 'Execution blocked by confirmation gate',
                detail: 'A risky action required confirmation. Policy and explanation may need refinement.',
                severity: 'medium',
                ts: Date.now(),
            });
        }

        const runtime = (payload.stats && payload.stats.runtime_outcome) || payload.runtime_outcome || null;
        if (runtime && String(runtime.status || '').toLowerCase() === 'failed') {
            this.activeRun.issues.push({
                type: 'runtime_failed',
                title: 'Runtime outcome failed',
                detail: String(runtime.reason || 'Runtime failed without explicit reason'),
                severity: 'high',
                ts: Date.now(),
            });
        }

        const toolFailures = Number(payload?.stats?.tool_failures || 0);
        if (toolFailures > 0) {
            this.activeRun.issues.push({
                type: 'tool_failure_count',
                title: `Tool failures detected (${toolFailures})`,
                detail: 'Multiple tool failures occurred in one action cycle.',
                severity: toolFailures >= 2 ? 'high' : 'medium',
                ts: Date.now(),
            });
        }
    }

    buildOptions(issues, payload) {
        const hasToolError = issues.some((x) => x.type === 'tool_error' || x.type === 'tool_failure_count');
        const hasRuntimeFail = issues.some((x) => x.type === 'runtime_failed');
        const hasGate = issues.some((x) => x.type === 'risk_confirmation');
        const message = String(payload?.user_message || '');

        const options = [];
        if (hasToolError) {
            options.push({
                id: 'tool-hardening',
                title: 'Tool hardening and fallback',
                summary: 'Strengthen tool retries, timeout handling, and deterministic fallback.',
                goal: `Improve tool reliability for frequent failure patterns.${message ? ` Context: ${message.slice(0, 120)}` : ''}`,
                target_files: ['gateway/tool_service.py', 'gateway/tool_strategy.py', 'UI/script.js'],
                acceptance_criteria: [
                    'Tool failure paths include retry and explicit fallback strategy',
                    'User-facing error summary is concise and actionable',
                    'Regression tests cover the observed failure type',
                ],
            });
        }
        if (hasRuntimeFail) {
            options.push({
                id: 'runtime-triage',
                title: 'Runtime failure triage loop',
                summary: 'Introduce structured failure diagnosis and one-click remediation path.',
                goal: 'Add runtime failure triage summary and auto-suggested remediation workflow.',
                target_files: ['gateway/reasoning_service.py', 'gateway/conversation_service.py', 'UI/script.js'],
                acceptance_criteria: [
                    'Failed runtime outcome emits structured reason codes',
                    'UI presents clear remediation options for failed outcomes',
                    'Core scenario has passing tests',
                ],
            });
        }
        if (hasGate) {
            options.push({
                id: 'policy-ux',
                title: 'Risk confirmation UX evolution',
                summary: 'Improve pre-check explanation and reduce avoidable confirmation friction.',
                goal: 'Refine sensitive-action explanation quality and confirmation routing precision.',
                target_files: ['gateway/tool_policy.py', 'gateway/server.py', 'UI/script.js'],
                acceptance_criteria: [
                    'User sees risk reason before confirmation',
                    'Unnecessary confirmations are reduced for low-risk actions',
                    'Policy decisions remain auditable',
                ],
            });
        }

        if (!options.length && issues.length) {
            options.push({
                id: 'general-hardening',
                title: 'General robustness hardening',
                summary: 'Convert observed issues into a focused reliability task.',
                goal: 'Stabilize recent failure patterns observed in action execution.',
                target_files: ['gateway/conversation_service.py', 'UI/script.js'],
                acceptance_criteria: [
                    'Issue can be reproduced and validated with tests',
                    'Execution path has clear fallback behavior',
                ],
            });
        }
        return options.slice(0, 4);
    }

    tryPromptForEvolution(issues, options) {
        if (!this.enabled) return;
        if (!Array.isArray(issues) || !issues.length) return;
        if (!Array.isArray(options) || !options.length) return;
        const highSignals = issues.filter((x) => x.severity === 'high').length;
        if (highSignals === 0 && issues.length < 2) return;

        const now = Date.now();
        if (now - this.lastPromptTs < this.promptCooldownMs) return;
        this.lastPromptTs = now;

        this.show();
        this.writeResult({
            status: 'candidate_detected',
            message: 'Potential evolution direction detected. Choose one option to create a controlled task.',
            issue_count: issues.length,
            options: options.map((x) => ({ id: x.id, title: x.title })),
        });
    }

    renderIssues(issues) {
        if (!this.issuesEl) return;
        const rows = Array.isArray(issues) ? issues : [];
        if (!rows.length) {
            this.issuesEl.innerHTML = '<div class="self-evolve-item">No issue signals collected yet.</div>';
            return;
        }
        this.issuesEl.innerHTML = '';
        rows.forEach((item) => {
            const node = document.createElement('div');
            node.className = 'self-evolve-item';
            node.innerHTML = `
                <div class="self-evolve-item-title">${this.escapeHtml(item.title || 'Issue')}</div>
                <div class="self-evolve-item-meta">severity=${this.escapeHtml(item.severity || 'low')} | type=${this.escapeHtml(item.type || '')}</div>
                <div>${this.escapeHtml(item.detail || '')}</div>
            `;
            this.issuesEl.appendChild(node);
        });
    }

    renderOptions(options) {
        if (!this.optionsEl) return;
        const rows = Array.isArray(options) ? options : [];
        if (!rows.length) {
            this.optionsEl.innerHTML = '<div class="self-evolve-item">No evolution options available.</div>';
            return;
        }
        this.optionsEl.innerHTML = '';
        rows.forEach((item) => {
            const node = document.createElement('div');
            node.className = 'self-evolve-item';
            node.innerHTML = `
                <div class="self-evolve-item-title">${this.escapeHtml(item.title || 'Option')}</div>
                <div class="self-evolve-item-meta">${this.escapeHtml(item.summary || '')}</div>
                <div class="self-evolve-item-actions">
                    <button type="button" class="btn-primary" data-self-evolve-action="create-task" data-self-evolve-option="${this.escapeHtml(item.id)}">Choose This Option</button>
                </div>
            `;
            this.optionsEl.appendChild(node);
        });
    }

    handleOptionAction(event) {
        const btn = event.target?.closest?.('button[data-self-evolve-action]');
        if (!btn) return;
        const action = String(btn.dataset.selfEvolveAction || '');
        const optionId = String(btn.dataset.selfEvolveOption || '');
        const option = this.latestOptions.find((x) => x.id === optionId);
        if (!option) return;
        if (action === 'create-task') {
            this.createTaskFromOption(option);
        }
    }

    async createTaskFromOption(option) {
        if (!this.enabled) {
            this.writeResult({
                status: 'blocked',
                reason: 'self_evolve_disabled',
                message: 'Enable self_evolve first in settings (experimental).',
            });
            return;
        }
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/self-evolve/tasks`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify({
                    goal: option.goal,
                    target_files: option.target_files,
                    acceptance_criteria: option.acceptance_criteria || [],
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || `HTTP ${response.status}`);
            }
            this.writeResult({
                status: 'success',
                action: 'create_task',
                option: option.id,
                task: data?.task || null,
            });
            await this.refreshStatus();
        } catch (error) {
            this.writeResult({
                status: 'error',
                action: 'create_task',
                option: option.id,
                error: error.message || String(error),
            });
        }
    }

    escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}

window.SelfEvolveManager = SelfEvolveManager;
