class MetricsManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('metricsModal');
        this.btn = document.getElementById('metricsBtn');
        this.closeBtn = this.modal?.querySelector('.close-modal');
        
        this.bindEvents();
    }
    
    bindEvents() {
        if (!this.btn || !this.modal) return;
        
        this.btn.addEventListener('click', () => this.show());
        this.closeBtn?.addEventListener('click', () => this.hide());
        
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.hide();
        });
    }
    
    async show() {
            this.modal.style.display = 'flex';
        await this.loadMetrics();
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    async loadMetrics() {
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/metrics`);
            const data = await response.json();
            
            if (data.status === 'success') {
                this.updateDisplay(data.metrics);
            }
        } catch (error) {
            console.error('Failed to fetch metrics data:', error);
        }
    }
    
    updateDisplay(metrics) {
        document.getElementById('totalTokens').textContent = metrics.llm.total_tokens.toLocaleString();
        document.getElementById('llmCalls').textContent = metrics.llm.calls;
        document.getElementById('avgLlmTime').textContent = metrics.llm.avg_time_ms;
        document.getElementById('estimatedCost').textContent = metrics.cost.estimated_usd.toFixed(4);
        
        document.getElementById('memoryRecalls').textContent = metrics.memory.recalls;
        document.getElementById('avgMemoryTime').textContent = metrics.memory.avg_time_ms;
        
        document.getElementById('sessionsCount').textContent = metrics.sessions.created;
        document.getElementById('messagesCount').textContent = metrics.sessions.messages;
        const personal = metrics.personal || {};
        const pinnedEl = document.getElementById('pinnedSessions');
        if (pinnedEl) pinnedEl.textContent = String(personal.sessions_pinned || 0);
        const filesEl = document.getElementById('filesCount');
        if (filesEl) filesEl.textContent = String(personal.files_total || 0);
        
        const uptime = metrics.uptime_seconds;
        const hours = Math.floor(uptime / 3600);
        const minutes = Math.floor((uptime % 3600) / 60);
        const secs = uptime % 60;
        document.getElementById('uptime').textContent = hours > 0 ? `${hours}h ${minutes}m` : minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
    }
}

