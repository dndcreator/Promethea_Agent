class DoctorManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('doctorModal');
        this.btn = document.getElementById('doctorBtn');
        this.closeBtn = this.modal?.querySelector('.close-modal');
        this.outputEl = document.getElementById('doctorOutput');
        this.runBtn = document.getElementById('doctorRunBtn');
        this.fixBtn = document.getElementById('doctorFixConfigBtn');

        this.bindEvents();
    }

    bindEvents() {
        if (!this.btn || !this.modal) return;

        this.btn.addEventListener('click', () => this.show());
        this.closeBtn?.addEventListener('click', () => this.hide());

        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.hide();
        });

        if (this.runBtn) {
            this.runBtn.addEventListener('click', () => this.runDoctor());
        }
        if (this.fixBtn) {
            this.fixBtn.addEventListener('click', () => this.migrateConfig());
        }
    }

    async show() {
            this.modal.style.display = 'flex';
        await this.runDoctor();
    }

    hide() {
        this.modal.style.display = 'none';
    }

    async runDoctor() {
        if (!this.outputEl) return;
        this.outputEl.textContent = `${t("ui_status_running_doctor")}\n`;

        try {
            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/doctor`);
            const data = await response.json();

            const lines = [];
            lines.push(`${getCurrentLang() === 'en' ? 'Status' : '\u72b6\u6001'}: ${data.status || 'unknown'}`);
            lines.push(`${getCurrentLang() === 'en' ? 'Time' : '\u65f6\u95f4'}: ${data.timestamp || ''}`);
            lines.push('');

            const checks = data.checks || {};
            for (const [key, value] of Object.entries(checks)) {
                const ok = value.ok !== false;
                lines.push(`- ${key} => ${ok ? 'OK' : 'ERROR'}`);
                if (value.issues && Array.isArray(value.issues) && value.issues.length > 0) {
                    for (const issue of value.issues) {
                        lines.push(`   - ${issue}`);
                    }
                }
                if (key === 'config_api') {
                    lines.push(`   base_url: ${value.api_base_url}`);
                    lines.push(`   model: ${value.model}`);
                } else if (key === 'memory') {
                    lines.push(`   enabled: ${value.enabled}`);
                    lines.push(`   neo4j_enabled: ${value.neo4j_enabled}`);
                    lines.push(`   warm_layer_enabled: ${value.warm_layer_enabled}`);
                } else if (key === 'plugins') {
                    lines.push(`   plugins_total: ${value.plugins_total}`);
                    lines.push(`   channels_total: ${value.channels_total}`);
                    lines.push(`   services_total: ${value.services_total}`);
                } else if (key === 'mcp') {
                    lines.push(`   services_total: ${value.services_total}`);
                    if (value.services && value.services.length) {
                        lines.push(`   services: ${value.services.join(', ')}`);
                    }
                } else if (key === 'sessions') {
                    lines.push(`   sessions_in_memory: ${value.sessions_in_memory}`);
                    lines.push(`   sessions_file_exists: ${value.sessions_file_exists}`);
                }
                lines.push('');
            }

            this.outputEl.textContent = lines.join('\n');
        } catch (error) {
            this.outputEl.textContent = `${getCurrentLang() === 'en' ? 'Doctor failed' : '\u7cfb\u7edf\u81ea\u68c0\u5931\u8d25'}: ${error.message}`;
        }
    }

    async migrateConfig() {
        if (!this.outputEl) return;
        this.outputEl.textContent = `${t("ui_status_running_migrate")}\n`;

        try {
            const headers = {
                'Content-Type': 'application/json',
            };

            const response = await window.AppHttp.authFetch(`${this.apiBaseUrl}/api/doctor/migrate-config`, {
                method: 'POST',
                headers,
                body: JSON.stringify({}),
            });
            const data = await response.json();

            const lines = [];
            if (response.ok && data.status === 'success') {
                lines.push(`${getCurrentLang() === 'en' ? 'Status' : '\u72b6\u6001'}: success`);
                if (data.message) lines.push(data.message);
                if (data.config_path) lines.push(`${getCurrentLang() === 'en' ? 'Config file' : '\u914d\u7f6e\u6587\u4ef6'}: ${data.config_path}`);
                if (data.backup) lines.push(`${getCurrentLang() === 'en' ? 'Backup created' : '\u5df2\u521b\u5efa\u5907\u4efd'}: ${data.backup}`);
            } else {
                lines.push(`${getCurrentLang() === 'en' ? 'Status' : '\u72b6\u6001'}: ${data.status || 'error'}`);
                lines.push(`${getCurrentLang() === 'en' ? 'Error' : '\u9519\u8bef'}: ${data.message || (getCurrentLang() === 'en' ? 'Migration failed' : '\u4fee\u590d\u5931\u8d25')}`);
                if (data.config_path) lines.push(`${getCurrentLang() === 'en' ? 'Config file' : '\u914d\u7f6e\u6587\u4ef6'}: ${data.config_path}`);
                if (data.backup) lines.push(`${getCurrentLang() === 'en' ? 'Backup' : '\u5907\u4efd'}: ${data.backup}`);
            }

            this.outputEl.textContent = lines.join('\n');
        } catch (error) {
            this.outputEl.textContent = `${getCurrentLang() === 'en' ? 'Doctor fix failed' : '\u7cfb\u7edf\u4fee\u590d\u5931\u8d25'}: ${error.message}`;
        }
    }
}

