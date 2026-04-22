class ShowcaseManager {
    constructor() {
        this.modal = document.getElementById('showcaseModal');
        this.btn = document.getElementById('showcaseBtn');
        this.closeBtn = this.modal?.querySelector('.close-modal');
        this.copyBtn = document.getElementById('showcaseCopyBtn');
        this.bindEvents();
    }

    bindEvents() {
        if (!this.btn || !this.modal) return;
        this.btn.addEventListener('click', () => this.show());
        this.closeBtn?.addEventListener('click', () => this.hide());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.hide();
        });
        this.copyBtn?.addEventListener('click', () => this.copyDemoCommands());
    }

    show() {
        this.modal.style.display = 'flex';
    }

    hide() {
        this.modal.style.display = 'none';
    }

    async copyDemoCommands() {
        const blocks = Array.from(this.modal?.querySelectorAll('.showcase-card pre') || []);
        const text = blocks.map((node) => node.textContent || '').join('\n\n');
        try {
            await navigator.clipboard.writeText(text);
            this.copyBtn.textContent = getCurrentLang() === 'en' ? 'Copied' : '已复制';
            setTimeout(() => {
                this.copyBtn.textContent = t("ui_showcase_copy");
            }, 1200);
        } catch (e) {
            console.warn('copy demo commands failed:', e);
        }
    }
}

