class SettingsManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('settingsModal');
        this.closeBtn = this.modal.querySelector('.close-modal');
        this.form = document.getElementById('settingsForm');
        this.loadingEl = document.querySelector('.settings-loading');
        this.resetBtn = document.getElementById('resetBtn');
        this.originalConfig = null;
        
        this.closeBtn.addEventListener('click', () => this.hide());
        this.modal.addEventListener('click', (event) => {
            if (event.target === this.modal) this.hide();
        });
        
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
        this.resetBtn.addEventListener('click', () => this.loadConfig());
        this.memoryStoreBackend = document.getElementById('memoryStoreBackend');
        this.memoryStoreBackend?.addEventListener('change', () => this.updateMemoryBackendFields());
        this.orgBrainStatusBtn = document.getElementById('orgBrainStatusBtn');
        this.orgBrainUploadBtn = document.getElementById('orgBrainUploadBtn');
        this.orgBrainResult = document.getElementById('orgBrainResult');
        this.orgBrainFileInput = document.getElementById('orgBrainFileInput');
        this.personalTemplateSelect = document.getElementById('personalTemplateSelect');
        this.personalTemplateRefreshBtn = document.getElementById('personalTemplateRefreshBtn');
        this.personalTemplateApplyBtn = document.getElementById('personalTemplateApplyBtn');
        this.personalTemplateStartWorkflow = document.getElementById('personalTemplateStartWorkflow');
        this.personalExportBtn = document.getElementById('personalExportBtn');
        this.personalImportBtn = document.getElementById('personalImportBtn');
        this.personalRecoveryBtn = document.getElementById('personalRecoveryBtn');
        this.personalImportFile = document.getElementById('personalImportFile');
        this.personalImportMerge = document.getElementById('personalImportMerge');
        this.personalOpsResult = document.getElementById('personalOpsResult');
        this.personalRecoveryActions = document.getElementById('personalRecoveryActions');
        this.lastRecoveryRuns = [];
        this.pluginCatalogRefreshBtn = document.getElementById('pluginCatalogRefreshBtn');
        this.pluginCatalogContainer = document.getElementById('pluginCatalogContainer');
        this.pluginCatalogResult = document.getElementById('pluginCatalogResult');
        this.pluginFormState = new Map();
        this.selfEvolveEnabled = document.getElementById('selfEvolveEnabled');
        
        document.getElementById('bindBtn').addEventListener('click', () => this.handleBindChannel());
        this.orgBrainStatusBtn?.addEventListener('click', () => this.fetchOrgBrainStatus());
        this.orgBrainUploadBtn?.addEventListener('click', () => this.uploadOrgBrainFile());
        this.personalTemplateRefreshBtn?.addEventListener('click', () => this.refreshPersonalTemplates());
        this.personalTemplateApplyBtn?.addEventListener('click', () => this.applyPersonalTemplate());
        this.personalExportBtn?.addEventListener('click', () => this.exportPersonalBundle());
        this.personalImportBtn?.addEventListener('click', () => this.importPersonalBundle());
        this.personalRecoveryBtn?.addEventListener('click', () => this.fetchPersonalRecovery());
        this.personalRecoveryActions?.addEventListener('click', (event) => this.handleRecoveryActionClick(event));
        this.pluginCatalogRefreshBtn?.addEventListener('click', () => this.loadPluginCatalog());
        this.pluginCatalogContainer?.addEventListener('click', (event) => this.handlePluginCatalogClick(event));
        this.selfEvolveEnabled?.addEventListener('change', () => this.confirmEnableSelfEvolve());
        window.addEventListener('ui-language-changed', () => {
            this.renderPersonalRecoveryActions(this.lastRecoveryRuns);
        });
    }
    
    async show() {
            this.modal.style.display = 'flex';
        await this.loadConfig();
        await this.loadBoundChannels();
        await this.refreshPersonalTemplates();
        await this.loadPluginCatalog();
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    async loadConfig() {
        try {
            this.loadingEl.style.display = 'block';
            this.form.style.display = 'none';
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/config`);
            const data = await response.json();
            
            if (response.ok && (data.status === 'success' || data.success === true)) {
                const mergedConfig = { ...(data.config || {}) };
                if (data.soul && typeof data.soul === 'object') {
                    mergedConfig.soul = data.soul;
                }
                this.originalConfig = mergedConfig;
                this.populateForm(mergedConfig);
            }
                this.loadingEl.style.display = 'none';
                this.form.style.display = 'block';
            
        } catch (error) {
            this.loadingEl.innerHTML = `<p style="color: #ff4141;">${t("ui_settings_load_fail", { msg: error.message })}</p>`;
        }
    }
    
    async loadBoundChannels() {
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/user/channels`);
            const data = await response.json();
            
            const listEl = document.getElementById('boundChannelsList');
            listEl.innerHTML = '';
            
            if (data.status === 'success' && data.channels) {
                for (const [channel, accountId] of Object.entries(data.channels)) {
                    const item = document.createElement('div');
                    item.className = 'bound-item';
                    item.innerHTML = `
                        <span class="channel-icon">${this.getChannelIcon(channel)}</span>
                        <span class="channel-name">${channel}</span>
                        <span class="account-id">${accountId}</span>
                        <span class="status-badge">${getCurrentLang() === 'en' ? 'Bound' : '\u5df2\u7ed1\u5b9a'}</span>
                    `;
                    listEl.appendChild(item);
                }
            }
        } catch (error) {
            console.error('Failed to load bound channels:', error);
        }
    }
    
    getChannelIcon(channel) {
        const icons = {
            'telegram': 'TG',
            'wechat': 'WX',
            'dingtalk': 'DT',
            'feishu': 'FS'
        };
        return icons[channel] || 'Bind';
    }
    
    async handleBindChannel() {
        const channel = document.getElementById('bindChannelType').value;
        const accountId = document.getElementById('bindAccountId').value.trim();
        
        if (!accountId) {
            alert(t("ui_bind_need_id"));
            return;
        }
        
        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/user/channels/bind`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ channel, account_id: accountId })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                alert(t("ui_bind_success"));
                document.getElementById('bindAccountId').value = '';
                this.loadBoundChannels();
            } else {
                throw new Error(data.detail || (getCurrentLang() === 'en' ? 'Bind failed' : '绑定失败'));
            }
        } catch (error) {
            alert(t("ui_bind_fail", { msg: error.message }));
        }
    }
    
    populateForm(config) {
        const apiConfig = (config && config.api) || {};
        const systemConfig = (config && config.system) || {};
        const memoryConfig = (config && config.memory) || {};
        const neo4jConfig = (memoryConfig && memoryConfig.neo4j) || {};
        const memoryApiConfig = (memoryConfig && memoryConfig.api) || {};
        const warmLayerConfig = (memoryConfig && memoryConfig.warm_layer) || {};
        const coldLayerConfig = (memoryConfig && memoryConfig.cold_layer) || {};
        const migrationConfig = (memoryConfig && memoryConfig.migration) || {};
        const personaConfig = (config && config.persona) || {};
        const soulConfig = (personaConfig && personaConfig.soul) || (config && config.soul) || {};
        const orgBrainConfig = (config && config.org_brain) || {};
        const selfEvolveConfig = (config && config.self_evolve) || {};

        this.setFieldValue('userAgentName', config.agent_name || '');
        this.setFieldValue('userSystemPrompt', config.system_prompt || '');
        this.setFieldValue('soulPromptReadonly', soulConfig.content || '');
        const soulMetaEl = document.getElementById('soulPromptMeta');
        if (soulMetaEl) {
            const ver = soulConfig.version || 1;
            const updatedAt = soulConfig.updated_at || '';
            soulMetaEl.textContent = updatedAt ? `v${ver} · updated ${updatedAt}` : `v${ver}`;
        }

        const userApi = (config.user && config.user.api) || {};
        this.setFieldValue('userBaseUrl', userApi.base_url || '');
        this.setFieldValue('userModel', userApi.model || '');
        this.setFieldValue('userTemperature', userApi.temperature || '');
        this.setFieldValue('userMaxTokens', userApi.max_tokens || '');

        this.setFieldValue('baseUrl', apiConfig.base_url || '');
        this.setFieldValue('model', apiConfig.model || '');
        this.setFieldValue('temperature', apiConfig.temperature ?? '');
        this.setFieldValue('maxTokens', apiConfig.max_tokens ?? '');
        this.setFieldValue('maxHistoryRounds', apiConfig.max_history_rounds ?? '');
        
        this.setFieldValue('streamMode', this.toBoolean(systemConfig.stream_mode), 'checkbox');
        this.setFieldValue('debugMode', this.toBoolean(systemConfig.debug), 'checkbox');
        this.setFieldValue('logLevel', systemConfig.log_level || 'INFO');
        
        this.setFieldValue('memoryEnabled', this.toBoolean(memoryConfig.enabled), 'checkbox');
        this.setFieldValue('memoryStoreBackend', memoryConfig.store_backend || 'neo4j');
        this.setFieldValue('neo4jEnabled', this.toBoolean(neo4jConfig.enabled), 'checkbox');
        this.setFieldValue('neo4jUri', neo4jConfig.uri || '');
        this.setFieldValue('neo4jUsername', neo4jConfig.username || '');
        this.setFieldValue('neo4jDatabase', neo4jConfig.database || '');
        this.setFieldValue('memoryUseMainApi', this.toBoolean(memoryApiConfig.use_main_api, true), 'checkbox');
        this.setFieldValue('memoryBaseUrl', memoryApiConfig.base_url || '');
        this.setFieldValue('memoryModel', memoryApiConfig.model || '');
        this.setFieldValue('sqliteGraphPath', memoryConfig.sqlite_graph_path || '');
        this.setFieldValue('flatMemoryPath', memoryConfig.flat_memory_path || '');
        this.setFieldValue('migrationMode', migrationConfig.mode || 'off');
        this.setFieldValue('migrationSourceBackend', migrationConfig.source_backend || '');
        this.setFieldValue('migrationTargetBackend', migrationConfig.target_backend || '');
        this.setFieldValue('migrationCheckpoint', migrationConfig.checkpoint || '');
        this.setFieldValue('warmLayerEnabled', this.toBoolean(warmLayerConfig.enabled), 'checkbox');
        this.setFieldValue('clusteringThreshold', warmLayerConfig.clustering_threshold ?? '');
        this.setFieldValue('minClusterSize', warmLayerConfig.min_cluster_size ?? '');
        this.setFieldValue('maxSummaryLength', coldLayerConfig.max_summary_length ?? '');
        this.setFieldValue('compressionThreshold', coldLayerConfig.compression_threshold ?? '');
        this.setFieldValue('orgBrainEnabled', this.toBoolean(orgBrainConfig.enabled), 'checkbox');
        this.setFieldValue('orgBrainOrgId', orgBrainConfig.org_id || '');
        this.setFieldValue('orgBrainAudienceDefault', orgBrainConfig.audience_default || '');
        this.setFieldValue('orgBrainRecallPriority', orgBrainConfig.recall_priority || 'blend');
        this.setFieldValue('orgBrainConfirmationQueue', this.toBoolean(orgBrainConfig.confirmation_queue, true), 'checkbox');
        this.setFieldValue('selfEvolveEnabled', this.toBoolean(selfEvolveConfig.enabled), 'checkbox');
        this.setFieldValue('selfEvolveMaxTasksList', selfEvolveConfig.max_tasks_list ?? 50);
        this.setFieldValue('selfEvolveContextChars', selfEvolveConfig.max_context_chars_per_file ?? 4000);
        this.setFieldValue('selfEvolveValidateTimeout', selfEvolveConfig.max_validate_timeout_seconds ?? 180);
        this.updateMemoryBackendFields();
    }

    confirmEnableSelfEvolve() {
        const enabledEl = this.selfEvolveEnabled;
        if (!enabledEl || !enabledEl.checked) return;
        const warning = [
            'Self Evolution Lab is experimental and may cause unstable behavior.',
            'Recommended: use a separate account with isolated agent profile and memory for trials.',
            '',
            'Do you want to enable it now?',
        ].join('\n');
        const ok = window.confirm(warning);
        if (!ok) {
            enabledEl.checked = false;
        }
    }

    toBoolean(value, defaultValue = false) {
        if (typeof value === 'boolean') return value;
        if (value == null) return defaultValue;
        if (typeof value === 'number') return value !== 0;
        if (typeof value === 'string') {
            const normalized = value.trim().toLowerCase();
            if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
            if (['0', 'false', 'no', 'off', ''].includes(normalized)) return false;
        }
        return Boolean(value);
    }
    
    setFieldValue(fieldId, value, type = 'input') {
        const field = document.getElementById(fieldId);
        if (!field) return;
        
        if (type === 'checkbox') {
            field.checked = value;
        } else {
            field.value = value;
        }
    }
    
    async handleSubmit(event) {
        event.preventDefault();
        
        const config = this.normalizeConfigForGateway(this.buildConfigObject());
        const hotApply = !!document.getElementById('settingsHotApply')?.checked;
        const headers = {
            'Content-Type': 'application/json',
        };
        
        try {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = true;
            submitBtn.textContent = t("ui_save_progress");
            
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/config/update`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ config, options: { hot_apply: hotApply } })
            });

            const data = await response.json();
            
            if (response.ok && (data.status === 'success' || data.success === true)) {
                if (config.agent_name) {
                    localStorage.setItem('agent_name', config.agent_name);
                }
                alert(t("ui_save_success"));
                this.hide();
            } else {
                throw new Error(data.message || (getCurrentLang() === 'en' ? 'Save failed' : '保存失败'));
            }
        } catch (error) {
            alert(t("ui_save_fail", { msg: error.message }));
        } finally {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = false;
            submitBtn.textContent = t("ui_save_btn");
        }
    }
    
    buildConfigObject() {
        const config = {};
        const setNestedValue = (target, path, value) => {
            const parts = path.split('.');
            let current = target;
            for (let i = 0; i < parts.length - 1; i++) {
                if (!current[parts[i]] || typeof current[parts[i]] !== 'object') {
                    current[parts[i]] = {};
                }
                current = current[parts[i]];
            }
            current[parts[parts.length - 1]] = value;
        };

        const fields = this.form.querySelectorAll('[name]');
        fields.forEach((field) => {
            const name = field.name;
            if (!name) return;

            if (field.type === 'checkbox') {
                setNestedValue(config, name, field.checked);
                return;
            }

            if (field.type === 'number') {
                if (field.value === '') return;
                const parsed = Number(field.value);
                if (!Number.isNaN(parsed)) {
                    setNestedValue(config, name, parsed);
                }
                return;
            }

            setNestedValue(config, name, field.value);
        });

        return config;
    }

    normalizeConfigForGateway(config) {
        const normalized = { ...config };
        const userConfig = normalized.user || {};

        if (typeof userConfig.agent_name === 'string') {
            normalized.agent_name = userConfig.agent_name;
        }
        if (typeof userConfig.system_prompt === 'string') {
            normalized.system_prompt = userConfig.system_prompt;
        }

        if (userConfig.api && typeof userConfig.api === 'object') {
            normalized.user = { ...normalized.user, api: userConfig.api };
        } else {
            delete normalized.user;
        }

        return normalized;
    }

    updateMemoryBackendFields() {
        const backend = document.getElementById('memoryStoreBackend')?.value || 'neo4j';
        const neo4jUriRow = document.getElementById('basicNeo4jUriRow');
        if (neo4jUriRow) {
            neo4jUriRow.style.display = backend === 'neo4j' ? 'block' : 'none';
        }
    }

    getAuthHeaders() {
        return window.AppHttp.buildAuthHeaders();
    }

    renderOrgBrainResult(payload) {
        if (!this.orgBrainResult) return;
        this.orgBrainResult.textContent = JSON.stringify(payload || {}, null, 2);
    }

    async fetchOrgBrainStatus() {
        try {
            this.renderOrgBrainResult({ status: 'loading' });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/org-brain/status`, {
                headers: this.getAuthHeaders(),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'status request failed');
            }
            this.renderOrgBrainResult(data);
        } catch (error) {
            this.renderOrgBrainResult({ status: 'error', error: error.message || String(error) });
        }
    }

    async uploadOrgBrainFile() {
        const file = this.orgBrainFileInput?.files?.[0];
        if (!file) {
            alert('Please choose a file first.');
            return;
        }
        const form = new FormData();
        form.append('file', file);
        const sourceDocId = (document.getElementById('orgBrainSourceDocId')?.value || '').trim();
        const orgId = (document.getElementById('orgBrainOrgId')?.value || '').trim();
        const audience = (document.getElementById('orgBrainAudienceInput')?.value || '').trim();
        const register = (document.getElementById('orgBrainRegisterInput')?.value || '').trim();
        if (sourceDocId) form.append('source_doc_id', sourceDocId);
        if (orgId) form.append('org_id', orgId);
        if (audience) form.append('audience', audience);
        if (register) form.append('register', register);
        form.append('use_llm', 'true');

        try {
            this.renderOrgBrainResult({ status: 'uploading', filename: file.name, bytes: file.size });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/org-brain/ingest-file`, {
                method: 'POST',
                headers: this.getAuthHeaders(),
                body: form,
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'upload failed');
            }
            this.renderOrgBrainResult(data);
        } catch (error) {
            this.renderOrgBrainResult({ status: 'error', error: error.message || String(error) });
        }
    }

    renderPersonalOpsResult(payload) {
        if (!this.personalOpsResult) return;
        this.personalOpsResult.textContent = JSON.stringify(payload || {}, null, 2);
    }

    renderPersonalRecoveryActions(runs) {
        if (!this.personalRecoveryActions) return;
        const rows = Array.isArray(runs) ? runs : [];
        this.lastRecoveryRuns = rows;
        this.personalRecoveryActions.innerHTML = '';
        if (!rows.length) {
            const empty = document.createElement('span');
            empty.className = 'settings-hint';
            empty.textContent = t("ui_personal_recovery_empty");
            this.personalRecoveryActions.appendChild(empty);
            return;
        }
        const title = document.createElement('span');
        title.className = 'settings-hint';
        title.textContent = t("ui_personal_recovery_actions");
        this.personalRecoveryActions.appendChild(title);
        for (const row of rows) {
            if (!row || !row.workflow_run_id) continue;
            const runId = String(row.workflow_run_id);
            const status = String(row.status || '');
            const stepId = String(row.retry_step_id || row.current_step_id || '');
            const chip = document.createElement('span');
            chip.className = 'status-badge';
            chip.textContent = `${runId} · ${status}`;
            this.personalRecoveryActions.appendChild(chip);

            const action = String(row.recommended_action || '').toLowerCase();
            if (action === 'resume') {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn-secondary';
                btn.dataset.recoveryAction = 'resume';
                btn.dataset.runId = runId;
                btn.textContent = t("ui_personal_action_resume");
                this.personalRecoveryActions.appendChild(btn);
            } else if (action === 'retry') {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn-secondary';
                btn.dataset.recoveryAction = 'retry';
                btn.dataset.runId = runId;
                btn.dataset.stepId = stepId;
                btn.textContent = t("ui_personal_action_retry");
                this.personalRecoveryActions.appendChild(btn);
            }
        }
    }

    async handleRecoveryActionClick(event) {
        const btn = event.target?.closest?.('button[data-recovery-action]');
        if (!btn) return;
        const action = String(btn.dataset.recoveryAction || '');
        const runId = String(btn.dataset.runId || '');
        const stepId = String(btn.dataset.stepId || '');
        if (!runId) return;
        if (action === 'resume') {
            await this.resumeWorkflowRun(runId);
            return;
        }
        if (action === 'retry') {
            await this.retryWorkflowStep(runId, stepId);
        }
    }

    async resumeWorkflowRun(runId) {
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/workflow/resume/${encodeURIComponent(runId)}`, {
                method: 'POST',
                headers: this.getAuthHeaders(),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'resume failed');
            }
            this.renderPersonalOpsResult({
                status: 'success',
                action: 'workflow_resume',
                run_id: runId,
                message: t("ui_personal_recovery_resume_done", { run_id: runId }),
                payload: data,
            });
            await this.fetchPersonalRecovery();
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'workflow_resume', run_id: runId, error: error.message || String(error) });
        }
    }

    async retryWorkflowStep(runId, stepId) {
        if (!stepId) {
            this.renderPersonalOpsResult({
                status: 'error',
                action: 'workflow_retry',
                run_id: runId,
                error: 'missing step_id for retry',
            });
            return;
        }
        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/workflow/retry`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify({ workflow_run_id: runId, step_id: stepId }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'retry failed');
            }
            this.renderPersonalOpsResult({
                status: 'success',
                action: 'workflow_retry',
                run_id: runId,
                step_id: stepId,
                message: t("ui_personal_recovery_retry_done", { run_id: runId, step_id: stepId }),
                payload: data,
            });
            await this.fetchPersonalRecovery();
        } catch (error) {
            this.renderPersonalOpsResult({
                status: 'error',
                action: 'workflow_retry',
                run_id: runId,
                step_id: stepId,
                error: error.message || String(error),
            });
        }
    }

    async refreshPersonalTemplates() {
        if (!this.personalTemplateSelect) return;
        try {
            this.renderPersonalRecoveryActions([]);
            this.renderPersonalOpsResult({ status: 'loading_templates', message: t("ui_personal_templates_load") });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/personal/templates/catalog`, {
                headers: this.getAuthHeaders(),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'template catalog request failed');
            }
            const templates = Array.isArray(data?.templates) ? data.templates : [];
            this.personalTemplateSelect.innerHTML = '';
            for (const item of templates) {
                if (!item || !item.template_id) continue;
                const option = document.createElement('option');
                option.value = String(item.template_id);
                const label = `${item.kind || 'template'} :: ${item.name || item.template_id}`;
                option.textContent = label;
                this.personalTemplateSelect.appendChild(option);
            }
            if (!this.personalTemplateSelect.options.length) {
                const option = document.createElement('option');
                option.value = '';
                option.textContent = t("ui_personal_template_empty");
                this.personalTemplateSelect.appendChild(option);
            }
            this.renderPersonalOpsResult({
                status: 'success',
                action: 'template_catalog_loaded',
                total: templates.length,
                counts: data?.counts || {},
                notice: data?.notice || '',
            });
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'template_catalog_loaded', error: error.message || String(error) });
        }
    }

    async applyPersonalTemplate() {
        const templateId = String(this.personalTemplateSelect?.value || '').trim();
        if (!templateId) {
            alert(t("ui_personal_choose_template"));
            return;
        }
        const startWorkflow = !!this.personalTemplateStartWorkflow?.checked;
        const body = {
            template_id: templateId,
            enable: true,
            activate: true,
            start_workflow: startWorkflow,
        };
        try {
            this.renderPersonalOpsResult({ status: 'applying_template', template_id: templateId });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/personal/templates/apply`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify(body),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'template apply failed');
            }
            this.renderPersonalOpsResult(data);
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'template_apply', error: error.message || String(error) });
        }
    }

    async exportPersonalBundle() {
        try {
            this.renderPersonalOpsResult({ status: 'exporting_bundle' });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/personal/export`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify({
                    include_messages: true,
                    include_memory: true,
                    include_files: true,
                    include_file_content: false,
                }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'export failed');
            }
            const bundle = data?.bundle || {};
            const stamp = String(bundle.generated_at || new Date().toISOString()).replace(/[:.]/g, '-');
            const filename = `personal_bundle_${stamp}.json`;
            const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            this.renderPersonalOpsResult({
                status: 'success',
                action: 'bundle_exported',
                filename,
                bundle_version: bundle.bundle_version || '',
                generated_at: bundle.generated_at || '',
            });
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'bundle_exported', error: error.message || String(error) });
        }
    }

    async importPersonalBundle() {
        const file = this.personalImportFile?.files?.[0];
        if (!file) {
            alert(t("ui_personal_choose_bundle"));
            return;
        }
        try {
            this.renderPersonalOpsResult({ status: 'importing_bundle', filename: file.name, bytes: file.size });
            const text = await file.text();
            const bundle = JSON.parse(text || '{}');
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/personal/import`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify({
                    bundle,
                    merge: !!this.personalImportMerge?.checked,
                    restore_config: true,
                    restore_sessions: true,
                    restore_memory: true,
                    restore_files: true,
                }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'import failed');
            }
            this.renderPersonalOpsResult(data);
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'bundle_imported', error: error.message || String(error) });
        }
    }

    async fetchPersonalRecovery() {
        try {
            this.renderPersonalOpsResult({ status: 'loading_workflow_recovery', message: t("ui_personal_recovery") });
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/personal/workflow/recovery?limit=50`, {
                headers: this.getAuthHeaders(),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'recovery query failed');
            }
            this.renderPersonalOpsResult(data);
            this.renderPersonalRecoveryActions(data?.runs || []);
        } catch (error) {
            this.renderPersonalOpsResult({ status: 'error', action: 'workflow_recovery', error: error.message || String(error) });
            this.renderPersonalRecoveryActions([]);
        }
    }

    renderPluginOpsResult(payload) {
        if (!this.pluginCatalogResult) return;
        this.pluginCatalogResult.textContent = JSON.stringify(payload || {}, null, 2);
    }

    _resolvePluginFields(plugin) {
        const uiSchema = (plugin && typeof plugin.uiSchema === 'object' && plugin.uiSchema) || {};
        const uiFields = Array.isArray(uiSchema.fields) ? uiSchema.fields : [];
        if (uiFields.length) {
            return uiFields
                .filter((f) => f && f.key)
                .map((f) => ({
                    key: String(f.key),
                    type: String(f.type || 'text'),
                    label: String(f.label || f.key),
                    options: Array.isArray(f.options) ? f.options : [],
                    placeholder: String(f.placeholder || ''),
                }));
        }

        const schema = (plugin && typeof plugin.configSchema === 'object' && plugin.configSchema) || {};
        const properties = (schema && typeof schema.properties === 'object' && schema.properties) || {};
        return Object.entries(properties).map(([key, desc]) => {
            const row = (desc && typeof desc === 'object' && desc) || {};
            const ty = String(row.type || 'text');
            let fieldType = 'text';
            if (ty === 'boolean') fieldType = 'boolean';
            else if (ty === 'number' || ty === 'integer') fieldType = 'number';
            else if (ty === 'object' || ty === 'array') fieldType = 'json';
            else if (Array.isArray(row.enum)) fieldType = 'select';
            return {
                key: String(key),
                label: String(row.title || key),
                type: fieldType,
                options: Array.isArray(row.enum) ? row.enum : [],
                placeholder: '',
            };
        });
    }

    _buildPluginFieldInput(field, value) {
        const wrap = document.createElement('div');
        wrap.className = 'plugin-field';
        const label = document.createElement('label');
        label.textContent = field.label || field.key;
        wrap.appendChild(label);

        let input = null;
        const typ = String(field.type || 'text');
        if (typ === 'boolean') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = !!value;
        } else if (typ === 'select') {
            input = document.createElement('select');
            const opts = Array.isArray(field.options) ? field.options : [];
            opts.forEach((o) => {
                const op = document.createElement('option');
                op.value = String(o);
                op.textContent = String(o);
                input.appendChild(op);
            });
            input.value = value == null ? '' : String(value);
        } else if (typ === 'number') {
            input = document.createElement('input');
            input.type = 'number';
            input.value = value == null ? '' : String(value);
        } else if (typ === 'json') {
            input = document.createElement('textarea');
            input.value = value == null ? '' : JSON.stringify(value, null, 2);
        } else {
            input = document.createElement('input');
            input.type = 'text';
            input.value = value == null ? '' : String(value);
        }

        if (field.placeholder && typeof field.placeholder === 'string' && input.tagName !== 'SELECT') {
            input.placeholder = field.placeholder;
        }
        input.dataset.pluginFieldKey = field.key;
        input.dataset.pluginFieldType = typ;
        wrap.appendChild(input);
        return { wrap, input };
    }

    _extractPluginConfig(pluginId) {
        const state = this.pluginFormState.get(pluginId);
        if (!state) return { enabled: true, config: {} };
        const config = {};
        for (const [key, input] of state.inputs.entries()) {
            const ty = String(input.dataset.pluginFieldType || 'text');
            if (ty === 'boolean') {
                config[key] = !!input.checked;
            } else if (ty === 'number') {
                const raw = String(input.value || '').trim();
                if (raw === '') continue;
                const num = Number(raw);
                if (!Number.isNaN(num)) config[key] = num;
            } else if (ty === 'json') {
                const raw = String(input.value || '').trim();
                if (raw === '') {
                    config[key] = {};
                } else {
                    config[key] = JSON.parse(raw);
                }
            } else {
                config[key] = input.value;
            }
        }
        return { enabled: !!state.enabledEl.checked, config };
    }

    async _validatePluginConfig(pluginId, config) {
        const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/plugins/validate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...this.getAuthHeaders(),
            },
            body: JSON.stringify({ plugin_id: pluginId, config }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data?.detail?.message || data?.detail || data?.message || 'plugin validation failed');
        }
        return data;
    }

    async _applyPluginConfig(pluginId) {
        try {
            const payload = this._extractPluginConfig(pluginId);
            const validation = await this._validatePluginConfig(pluginId, payload.config);
            if (!validation?.ok) {
                throw new Error((validation?.errors || ['plugin validation failed']).join('; '));
            }
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/plugins/apply`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...this.getAuthHeaders(),
                },
                body: JSON.stringify({
                    plugin_id: pluginId,
                    enabled: payload.enabled,
                    config: payload.config,
                    validate: true,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.detail?.message || data?.detail || data?.message || 'plugin apply failed');
            }
            this.renderPluginOpsResult({ status: 'success', action: 'plugin_apply', plugin_id: pluginId, payload: data });
            await this.loadPluginCatalog();
        } catch (error) {
            this.renderPluginOpsResult({ status: 'error', action: 'plugin_apply', plugin_id: pluginId, error: error.message || String(error) });
        }
    }

    async _validatePluginFromUi(pluginId) {
        try {
            const payload = this._extractPluginConfig(pluginId);
            const data = await this._validatePluginConfig(pluginId, payload.config);
            this.renderPluginOpsResult({ status: data?.ok ? 'success' : 'error', action: 'plugin_validate', plugin_id: pluginId, payload: data });
        } catch (error) {
            this.renderPluginOpsResult({ status: 'error', action: 'plugin_validate', plugin_id: pluginId, error: error.message || String(error) });
        }
    }

    handlePluginCatalogClick(event) {
        const btn = event.target?.closest?.('button[data-plugin-action]');
        if (!btn) return;
        const action = String(btn.dataset.pluginAction || '');
        const pluginId = String(btn.dataset.pluginId || '');
        if (!pluginId) return;
        if (action === 'apply') {
            this._applyPluginConfig(pluginId);
            return;
        }
        if (action === 'validate') {
            this._validatePluginFromUi(pluginId);
        }
    }

    async loadPluginCatalog() {
        if (!this.pluginCatalogContainer) return;
        try {
            this.pluginCatalogContainer.innerHTML = `<div class="settings-hint">${t("memory_loading")}</div>`;
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/plugins/catalog`, {
                headers: this.getAuthHeaders(),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.detail || data?.message || 'plugin catalog request failed');
            }
            const plugins = Array.isArray(data?.plugins) ? data.plugins : [];
            this.pluginFormState.clear();
            this.pluginCatalogContainer.innerHTML = '';
            if (!plugins.length) {
                this.pluginCatalogContainer.innerHTML = `<div class="settings-hint">No plugins discovered.</div>`;
            }

            for (const plugin of plugins) {
                const card = document.createElement('div');
                card.className = 'plugin-card';
                card.dataset.pluginId = plugin.id;

                const head = document.createElement('div');
                head.className = 'plugin-card-head';
                const title = document.createElement('div');
                title.className = 'plugin-card-title';
                title.textContent = `${plugin.name || plugin.id} (${plugin.id})`;
                head.appendChild(title);
                const enabledWrap = document.createElement('label');
                enabledWrap.className = 'checkbox-group';
                const enabled = document.createElement('input');
                enabled.type = 'checkbox';
                enabled.checked = !!plugin.enabled;
                enabledWrap.appendChild(enabled);
                const enabledText = document.createElement('span');
                enabledText.textContent = getCurrentLang() === 'en' ? 'Enabled' : '已启用';
                enabledWrap.appendChild(enabledText);
                head.appendChild(enabledWrap);
                card.appendChild(head);

                const meta = document.createElement('div');
                meta.className = 'plugin-card-meta';
                meta.textContent = `${plugin.kind || 'plugin'} | ${plugin.version || '0.0.0'} | ${plugin.status || ''}`;
                card.appendChild(meta);

                const fieldsWrap = document.createElement('div');
                fieldsWrap.className = 'plugin-fields';
                const inputs = new Map();
                const fields = this._resolvePluginFields(plugin).filter((f) => f.key !== 'enabled');
                const configRow = (plugin && typeof plugin.config === 'object' && plugin.config) || {};
                for (const field of fields) {
                    const value = configRow[field.key];
                    const built = this._buildPluginFieldInput(field, value);
                    inputs.set(field.key, built.input);
                    fieldsWrap.appendChild(built.wrap);
                }
                card.appendChild(fieldsWrap);

                const actions = document.createElement('div');
                actions.className = 'plugin-card-actions';
                const validateBtn = document.createElement('button');
                validateBtn.type = 'button';
                validateBtn.className = 'btn-secondary';
                validateBtn.dataset.pluginAction = 'validate';
                validateBtn.dataset.pluginId = plugin.id;
                validateBtn.textContent = getCurrentLang() === 'en' ? 'Validate' : '校验';
                actions.appendChild(validateBtn);
                const applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'btn-primary';
                applyBtn.dataset.pluginAction = 'apply';
                applyBtn.dataset.pluginId = plugin.id;
                applyBtn.textContent = getCurrentLang() === 'en' ? 'Apply' : '应用';
                actions.appendChild(applyBtn);
                card.appendChild(actions);

                this.pluginFormState.set(plugin.id, {
                    enabledEl: enabled,
                    inputs,
                });
                this.pluginCatalogContainer.appendChild(card);
            }

            this.renderPluginOpsResult({
                status: 'success',
                action: 'plugin_catalog_loaded',
                total: plugins.length,
                diagnostics: Array.isArray(data?.diagnostics) ? data.diagnostics : [],
            });
        } catch (error) {
            this.pluginCatalogContainer.innerHTML = '';
            this.renderPluginOpsResult({ status: 'error', action: 'plugin_catalog_loaded', error: error.message || String(error) });
        }
    }
}

