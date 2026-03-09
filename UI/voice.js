(function () {
    function getAuthHeaders(extra) {
        const headers = extra ? { ...extra } : {};
        const token = localStorage.getItem('auth_token');
        if (token) headers['Authorization'] = `Bearer ${token}`;
        return headers;
    }

    function resolveApiBase() {
        return 'http://127.0.0.1:8000';
    }

    function appendMessage(role, content) {
        const chat = document.getElementById('chatMessages');
        if (!chat) return;
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role === 'user' ? 'user' : 'assistant'}`;
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = String(content || '').replace(/\n/g, '<br>');
        messageDiv.appendChild(contentDiv);
        chat.appendChild(messageDiv);
        chat.scrollTop = chat.scrollHeight;
    }

    function updateSession(sessionId) {
        if (!sessionId) return;
        window.__voiceCurrentSessionId = sessionId;
        const el = document.getElementById('currentSession');
        if (el) {
            el.textContent = sessionId.slice(0, 8) + '...';
            el.dataset.sessionId = sessionId;
        }
    }

    function getCurrentSession() {
        if (window.__voiceCurrentSessionId) return window.__voiceCurrentSessionId;
        const el = document.getElementById('currentSession');
        if (el && el.dataset && el.dataset.sessionId) return el.dataset.sessionId;
        return null;
    }

    async function playBase64Audio(audioBase64, mimeType) {
        if (!audioBase64) return;
        try {
            const bin = atob(audioBase64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
            const blob = new Blob([bytes], { type: mimeType || 'audio/mpeg' });
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            audio.onended = () => URL.revokeObjectURL(url);
            audio.onerror = () => URL.revokeObjectURL(url);
            await audio.play();
        } catch (err) {
            console.warn('voice playback failed:', err);
        }
    }

    class VoicePTT {
        constructor() {
            this.apiBase = resolveApiBase();
            this.button = document.getElementById('voiceButton');
            this.isRecording = false;
            this.mediaRecorder = null;
            this.mediaStream = null;
            this.audioChunks = [];
            this.locked = false;
            if (this.button) this.bind();
        }

        bind() {
            this.button.addEventListener('mousedown', () => this.start());
            this.button.addEventListener('mouseup', () => this.stop());
            this.button.addEventListener('mouseleave', () => this.stop());
            this.button.addEventListener('touchstart', (e) => {
                e.preventDefault();
                this.start();
            }, { passive: false });
            this.button.addEventListener('touchend', (e) => {
                e.preventDefault();
                this.stop();
            }, { passive: false });
        }

        setRecording(flag) {
            this.isRecording = flag;
            if (!this.button) return;
            if (flag) {
                this.button.classList.add('recording');
                this.button.title = 'Release to send';
            } else {
                this.button.classList.remove('recording');
                this.button.title = 'Push to talk';
            }
        }

        async start() {
            if (this.locked || this.isRecording) return;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                appendMessage('assistant', 'Voice capture is not supported in this browser.');
                return;
            }
            try {
                this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
                this.mediaRecorder = mime ? new MediaRecorder(this.mediaStream, { mimeType: mime }) : new MediaRecorder(this.mediaStream);
                this.audioChunks = [];
                this.mediaRecorder.ondataavailable = (event) => {
                    if (event.data && event.data.size > 0) this.audioChunks.push(event.data);
                };
                this.mediaRecorder.onstop = async () => {
                    const blob = new Blob(this.audioChunks, { type: this.mediaRecorder.mimeType || 'audio/webm' });
                    this.audioChunks = [];
                    await this.send(blob);
                };
                this.mediaRecorder.start();
                this.setRecording(true);
            } catch (err) {
                appendMessage('assistant', `Failed to start recording: ${err.message}`);
                this.cleanupStream();
            }
        }

        stop() {
            if (!this.isRecording) return;
            this.setRecording(false);
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
            } else {
                this.cleanupStream();
            }
        }

        cleanupStream() {
            if (this.mediaStream) {
                this.mediaStream.getTracks().forEach((track) => track.stop());
            }
            this.mediaStream = null;
            this.mediaRecorder = null;
        }

        async send(blob) {
            this.cleanupStream();
            if (!blob || blob.size < 400) return;
            this.locked = true;
            this.button.disabled = true;
            try {
                const form = new FormData();
                form.append('audio', blob, 'voice.webm');
                form.append('session_id', getCurrentSession() || '');
                form.append('speak', 'true');

                const provider = (localStorage.getItem('voice_tts_provider') || '').trim();
                const voice = (localStorage.getItem('voice_tts_voice') || '').trim();
                const format = (localStorage.getItem('voice_tts_format') || '').trim();
                const speed = (localStorage.getItem('voice_tts_speed') || '').trim();
                const stability = (localStorage.getItem('voice_tts_stability') || '').trim();
                const similarity = (localStorage.getItem('voice_tts_similarity_boost') || '').trim();
                const style = (localStorage.getItem('voice_tts_style') || '').trim();
                const speakerBoost = (localStorage.getItem('voice_tts_speaker_boost') || '').trim();
                if (provider) form.append('tts_provider', provider);
                if (voice) form.append('tts_voice', voice);
                if (format) form.append('tts_format', format);
                if (speed) form.append('tts_speed', speed);
                if (stability) form.append('tts_stability', stability);
                if (similarity) form.append('tts_similarity_boost', similarity);
                if (style) form.append('tts_style', style);
                if (speakerBoost) form.append('tts_use_speaker_boost', speakerBoost);

                const res = await fetch(`${this.apiBase}/api/voice/ptt`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: form,
                });

                const data = await res.json();
                if (!res.ok || data.status !== 'success') {
                    throw new Error(data.detail || data.message || 'Voice request failed');
                }

                const transcript = data.transcript || '';
                const turn = data.turn || {};
                const answer = turn.response || '';

                if (transcript) appendMessage('user', transcript);
                if (answer) appendMessage('assistant', answer);
                if (turn.session_id) updateSession(turn.session_id);

                if (data.tts && data.tts.audio_base64) {
                    await playBase64Audio(data.tts.audio_base64, data.tts.mime);
                }
            } catch (err) {
                appendMessage('assistant', `Voice interaction failed: ${err.message}`);
            } finally {
                this.locked = false;
                this.button.disabled = false;
            }
        }
    }

    window.addEventListener('DOMContentLoaded', () => {
        if (!document.getElementById('voiceButton')) return;
        window.__voicePTT = new VoicePTT();
    });
})();

