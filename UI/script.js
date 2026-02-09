// 认证管理
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
        if (this.isRegister) {
            this.title.textContent = '📝 注册';
            this.submitBtn.textContent = '注册并创建 Agent';
            this.switchText.textContent = '已有账号？';
            this.switchLink.textContent = '去登录';
            this.agentNameGroup.style.display = 'block';
        } else {
            this.title.textContent = '🔐 登录';
            this.submitBtn.textContent = '登录';
            this.switchText.textContent = '还没有账号？';
            this.switchLink.textContent = '去注册';
            this.agentNameGroup.style.display = 'none';
        }
    }
    
    checkAuth() {
        const token = localStorage.getItem('auth_token');
        if (token) {
            this.modal.style.display = 'none';
            if (this.onLoginSuccess) this.onLoginSuccess();
        } else {
            this.modal.style.display = 'flex'; // 使用 flex 以正确居中
        }
    }
    
    async handleSubmit(e) {
        e.preventDefault();
        const formData = new FormData(this.form);
        const data = Object.fromEntries(formData.entries());
        
        const endpoint = this.isRegister ? '/api/auth/register' : '/api/auth/login';
        
        try {
            this.submitBtn.disabled = true;
            this.submitBtn.textContent = '处理中...';
            
            const response = await fetch(`${this.apiBaseUrl}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.detail || '操作失败');
            }
            
            if (this.isRegister) {
                alert('注册成功，请登录');
                this.toggleMode();
                // 自动填充用户名
                document.getElementById('username').value = data.username;
                document.getElementById('password').value = '';
            } else {
                localStorage.setItem('auth_token', result.access_token);
                localStorage.setItem('user_id', result.user_id);
                localStorage.setItem('agent_name', result.agent_name);
                
                this.modal.style.display = 'none';
                if (this.onLoginSuccess) this.onLoginSuccess();
                
                // 欢迎提示
                const agentName = result.agent_name || 'Promethea';
                alert(`欢迎回来！${agentName} 已准备就绪。`);
            }
            
        } catch (error) {
            alert(error.message);
        } finally {
            this.submitBtn.disabled = false;
            this.submitBtn.textContent = this.isRegister ? '注册并创建 Agent' : '登录';
        }
    }
    
    logout() {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user_id');
        localStorage.removeItem('agent_name');
        location.reload();
    }
}

class TerminalChatApp {
    constructor() {
        this.messageInput = document.getElementById('messageInput');
        this.sendButton = document.getElementById('sendButton');
        this.chatMessages = document.getElementById('chatMessages');
        this.sessionList = document.getElementById('sessionList');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.currentSessionEl = document.getElementById('currentSession');
        this.sessionCountEl = document.getElementById('sessionCount');
        this.connectionStatusEl = document.getElementById('connectionStatus');
        
        // 新增UI元素
        this.apiStatusEl = document.getElementById('apiStatus');
        this.memoryStatusEl = document.getElementById('memoryStatus');
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebarToggle');
        this.avatarPlaceholder = document.getElementById('avatarPlaceholder');
        this.logoutBtn = document.getElementById('logoutBtn');
        
        // 确认模态窗口
        this.confirmModal = document.getElementById('confirmModal');
        this.confirmToolName = document.getElementById('confirmToolName');
        this.confirmToolArgs = document.getElementById('confirmToolArgs');
        this.approveToolBtn = document.getElementById('approveToolBtn');
        this.rejectToolBtn = document.getElementById('rejectToolBtn');
        this.pendingConfirmation = null;
        
        this.apiBaseUrl = 'http://127.0.0.1:8000';
        this.currentSessionId = null;
        this.isTyping = false;
        // tool_call 显示：call_id -> DOM element
        this.toolCallElements = new Map();
        
        // 初始化认证管理器
        this.authManager = new AuthManager(this.apiBaseUrl, () => this.initializeApp());
        
        this.bindEvents();
        // this.initializeApp(); // 移到登录成功后调用
    }
    
    async fetchWithAuth(url, options = {}) {
        const token = localStorage.getItem('auth_token');
        const headers = options.headers || {};
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        options.headers = headers;
        
        const response = await fetch(url, options);
        if (response.status === 401) {
            this.authManager.logout();
            throw new Error('认证失效，请重新登录');
        }
        return response;
    }
    
    async initializeApp() {
        this.addWelcomeMessage();
        await this.checkApiStatus();
        await this.refreshSessions();
        this.focusInput();
        
        // 定期检查状态（每30秒）
        setInterval(() => this.checkApiStatus(), 30000);
    }
    
    bindEvents() {
        // 侧边栏切换
        this.sidebarToggle.addEventListener('click', () => {
            this.sidebar.classList.toggle('open');
        });
        
        // 点击主区域关闭侧边栏（移动端）
        document.querySelector('.terminal-container').addEventListener('click', () => {
            if (window.innerWidth <= 768 && this.sidebar.classList.contains('open')) {
                this.sidebar.classList.remove('open');
            }
        });

        // 发送按钮点击事件
        this.sendButton.addEventListener('click', () => this.sendMessage());
        
        // 回车键发送
        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        // 输入框变化时启用/禁用发送按钮
        this.messageInput.addEventListener('input', () => {
            this.sendButton.disabled = !this.messageInput.value.trim();
        });

        // 选中文本追问机制
        this.selectionMenu = document.getElementById('selectionMenu');
        this.quickAskBtn = document.getElementById('quickAskBtn');
        
        document.addEventListener('mouseup', (e) => this.handleTextSelection(e));
        
        // 点击追问按钮
        this.quickAskBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // 防止触发文档点击关闭选单
            const selection = window.getSelection();
            const text = selection.toString().trim();
            if (text) {
                // 获取选区矩形，用于定位气泡
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                
                // 构造虚拟mark对象
                const mark = { text: text };
                
                // 调用气泡显示逻辑
                this.showFollowUpBubble(rect, mark);
                
                // 隐藏悬浮按钮
                this.selectionMenu.style.display = 'none';
                window.getSelection().removeAllRanges();
            }
        });
        
        // 隐藏选单
        document.addEventListener('mousedown', (e) => {
            if (!this.selectionMenu.contains(e.target) && e.target !== this.quickAskBtn) {
                this.selectionMenu.style.display = 'none';
            }
        });
        
        // 新建会话
        this.newChatBtn.addEventListener('click', () => {
            this.startNewChat();
        });
        
        // 自动聚焦输入框
        this.messageInput.addEventListener('focus', () => {
            this.messageInput.parentElement.style.boxShadow = '0 0 20px var(--glow)';
        });
        
        this.messageInput.addEventListener('blur', () => {
            this.messageInput.parentElement.style.boxShadow = '0 0 15px var(--shadow)';
        });

        // 登出按钮
        if (this.logoutBtn) {
            this.logoutBtn.addEventListener('click', () => {
                if (confirm('确定要退出登录吗？')) {
                    this.authManager.logout();
                }
            });
        }

        // 确认模态窗口事件
        this.approveToolBtn.addEventListener('click', () => this.handleToolConfirmation('approve'));
        this.rejectToolBtn.addEventListener('click', () => this.handleToolConfirmation('reject'));
    }
    
    async handleToolConfirmation(action) {
        if (!this.pendingConfirmation) return;
        
        const { session_id, tool_call_id } = this.pendingConfirmation;
        
        // 隐藏模态窗口
        this.confirmModal.style.display = 'none';
        
        // 如果是拒绝，直接结束
        if (action === 'reject') {
            this.addMessage('assistant', '❌ 已拒绝执行该操作。');
            this.sendButton.disabled = false;
            this.isTyping = false;
            this.setAvatarStatus('idle');
        } else {
            // 如果是批准，继续显示思考状态
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
                // 再次需要确认（链式调用）
                this.showConfirmation(data);
            } else if (data.status === 'success') {
                // 显示结果
                this.addMessage('assistant', data.response);
                this.sendButton.disabled = false;
                this.isTyping = false;
                this.setAvatarStatus('idle');
            } else if (data.status === 'rejected') {
                // 已拒绝
            } else {
                throw new Error(data.message || '操作失败');
            }
            
        } catch (error) {
            console.error('确认操作失败:', error);
            this.addMessage('assistant', `操作失败: ${error.message}`);
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
        
        this.confirmModal.style.display = 'block';
    }
    
    async checkApiStatus() {
        try {
            // 优先访问后端真实状态接口（挂在 /api 下）
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/status`);
            if (response.ok) {
                const data = await response.json();
                this.updateStatus(this.apiStatusEl, true);
                
                // 检查记忆系统状态（直接使用后端返回的真实状态）
                if (data.memory_active !== undefined) {
                    this.updateStatus(this.memoryStatusEl, data.memory_active);
                }
            } else {
                this.updateStatus(this.apiStatusEl, false);
                this.updateStatus(this.memoryStatusEl, false);
            }
        } catch (error) {
            this.updateStatus(this.apiStatusEl, false);
            this.updateStatus(this.memoryStatusEl, false);
            console.log('❌ 无法连接到API服务');
        }
    }
    
    // Deprecated
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
    
    setAvatarStatus(status) {
        // status: 'thinking' | 'speaking' | 'idle'
        this.avatarPlaceholder.classList.remove('thinking', 'speaking');
        if (status !== 'idle') {
            this.avatarPlaceholder.classList.add(status);
        }
    }
    
    addWelcomeMessage() {
        this.addMessage('assistant', '欢迎使用普罗米娅AI助手！\n\n我是你的智能对话伙伴，可以帮你：\n• 回答问题\n• 分析文档\n• 编写代码\n• 创意写作\n\n开始对话吧！');
    }
    
    addMessage(role, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        // 处理换行符
        let formattedContent = content.replace(/\n/g, '<br>');
        
        contentDiv.innerHTML = formattedContent;
        
        messageDiv.appendChild(contentDiv);
        this.chatMessages.appendChild(messageDiv);
        
        // 滚动到底部
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        
        // 添加打字机效果
        if (role === 'assistant') {
            this.addTypingEffect(contentDiv, content);
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
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions`);
            if (!response.ok) throw new Error('获取会话列表失败');
            
            const data = await response.json();
            const sessions = data.sessions || [];
            
            // 更新会话数量
            this.sessionCountEl.textContent = sessions.length;
            
            // 清空并重新渲染会话列表
            this.sessionList.innerHTML = '';
            
            if (sessions.length === 0) {
                const emptyItem = document.createElement('li');
                emptyItem.textContent = '暂无会话历史';
                emptyItem.style.textAlign = 'center';
                emptyItem.style.color = 'var(--text-muted)';
                emptyItem.style.fontStyle = 'italic';
                this.sessionList.appendChild(emptyItem);
                return;
            }
            
            sessions.forEach(session => {
                const li = document.createElement('li');
                
                // 生成会话标题（使用最后一条消息的前20个字符）
                const title = session.last_message && session.last_message.trim() 
                    ? session.last_message.slice(0, 20) + (session.last_message.length > 20 ? '...' : '')
                    : '新的会话';
                
                li.textContent = title;
                li.title = `会话ID: ${session.session_id}\n创建时间: ${new Date(session.created_at * 1000).toLocaleString()}\n消息数量: ${session.message_count}`;
                li.dataset.sid = session.session_id;
                
                // 高亮当前会话
                if (this.currentSessionId === session.session_id) {
                    li.classList.add('active');
                }
                
                // 点击切换会话
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
    
    async switchSession(sessionId) {
        if (!sessionId || this.currentSessionId === sessionId) return;
        
        try {
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions/${sessionId}`);
            if (!response.ok) throw new Error('获取会话详情失败');
            
            const data = await response.json();
            
            // 更新当前会话
            this.currentSessionId = sessionId;
            this.currentSessionEl.textContent = sessionId.slice(0, 8) + '...';
            
            // 清空消息区域并加载历史
            this.chatMessages.innerHTML = '';
            
            const messages = data.messages || [];
            if (messages.length === 0) {
                this.addWelcomeMessage();
            } else {
                messages.forEach(msg => {
                    this.addMessage(msg.role, msg.content);
                });
            }
            
            // 更新侧边栏高亮
            Array.from(this.sessionList.children).forEach(li => {
                li.classList.toggle('active', li.dataset.sid === sessionId);
            });
            
            // 聚焦输入框
            this.focusInput();
            
        } catch (error) {
            console.error('切换会话失败:', error);
            this.addMessage('assistant', `切换会话失败: ${error.message}`);
        }
    }
    
    startNewChat() {
        this.currentSessionId = null;
        this.currentSessionEl.textContent = '未开始';
        this.chatMessages.innerHTML = '';
        this.addWelcomeMessage();
        
        // 清除侧边栏高亮
        Array.from(this.sessionList.children).forEach(li => {
            li.classList.remove('active');
        });
        
        this.focusInput();
    }
    
    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message || this.isTyping) return;
        
        // 添加用户消息
        this.addMessage('user', message);
        
        // 清空输入框并禁用发送按钮
        this.messageInput.value = '';
        this.sendButton.disabled = true;
        this.isTyping = true;
        
        // 设置思考状态
        this.setAvatarStatus('thinking');
        
        // 创建AI消息容器（用于流式更新）
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        // 分离：工具调用区 + 文本区（避免互相覆盖）
        contentDiv.innerHTML = `
            <div class="tool-area"></div>
            <div class="text-area">正在思考...</div>
        `;
        messageDiv.appendChild(contentDiv);
        this.chatMessages.appendChild(messageDiv);
        const toolArea = contentDiv.querySelector('.tool-area');
        const textArea = contentDiv.querySelector('.text-area');
        
        try {
            // 调用后端API（流式）
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    message: message,
                    session_id: this.currentSessionId || null,
                    stream: true  // 启用流式
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            // 处理SSE流式响应
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            
            textArea.innerHTML = '';  // 清空"正在思考"
            
            let doneReceived = false;
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';  // 保留不完整的行

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;

                    let data;
                    try {
                        data = JSON.parse(trimmed);
                    } catch (e) {
                        console.warn('解析SSE数据失败:', trimmed, e);
                        continue;
                    }

                    if (data.type === 'text') {
                        // 流式文本
                        fullText += (data.content || '');

                        // 处理思考标签渲染
                        let displayHtml = fullText.replace(/\n/g, '<br>');

                        // 检查是否有闭合的思考标签
                        if (fullText.includes('<thinking>') && fullText.includes('</thinking>')) {
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;([\s\S]*?)&lt;\/thinking&gt;|<thinking>([\s\S]*?)<\/thinking>/g,
                                (match, p1, p2) => {
                                    const content = p1 || p2;
                                    return `<details class="thought-process">
                                        <summary>💭 深度思考过程</summary>
                                        <div class="thought-content">${content}</div>
                                    </details>`;
                                }
                            );
                        } else if (fullText.includes('<thinking>')) {
                            // 正在思考中（未闭合）
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;[\s\S]*|<thinking>[\s\S]*/,
                                '<div class="thinking-status">🧠 正在深度思考...</div>'
                            );
                        }

                        textArea.innerHTML = displayHtml;
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;

                        // 设置说话状态
                        this.setAvatarStatus('speaking');
                    } else if (data.type === 'tool_detected') {
                        // 模型已检测到工具调用（还没拿到具体工具参数）
                        const hint = document.createElement('div');
                        hint.className = 'tool-hint';
                        hint.textContent = data.content || '检测到工具调用...';
                        toolArea.appendChild(hint);
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_start') {
                        // 工具调用开始：显示折叠面板（类似 ChatGPT 工具过程）
                        const callId = data.call_id || `${Date.now()}_${Math.random()}`;
                        const toolName = data.tool_name || 'tool';
                        const args = data.args || {};

                        const details = document.createElement('details');
                        details.className = 'tool-call';
                        details.open = false;

                        const summary = document.createElement('summary');
                        summary.textContent = `🔧 调用工具：${toolName}（运行中）`;

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
                        this.toolCallElements.set(callId, { details, summary, resultPre });
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_result') {
                        const callId = data.call_id;
                        const entry = this.toolCallElements.get(callId);
                        const resultText = data.result || '';
                        if (entry) {
                            entry.resultPre.textContent = resultText;
                            entry.summary.textContent = `🔧 调用工具：${data.tool_name || 'tool'}（已完成）`;
                            // 默认折叠；用户可展开查看参数与输出
                        } else {
                            // 容错：如果找不到对应卡片，直接追加一条
                            const fallback = document.createElement('pre');
                            fallback.className = 'tool-call-result';
                            fallback.textContent = resultText;
                            toolArea.appendChild(fallback);
                        }
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_error') {
                        const err = document.createElement('div');
                        err.className = 'tool-error';
                        err.textContent = data.content || '工具调用失败';
                        toolArea.appendChild(err);
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'done') {
                        // done 时对最终文本做一次“重复输出”去重并重绘，避免留下 A\n\nA 这种结果
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

                        // 复用现有渲染逻辑（思考标签/换行）
                        let displayHtml = fullText.replace(/\n/g, '<br>');
                        if (fullText.includes('<thinking>') && fullText.includes('</thinking>')) {
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;([\s\S]*?)&lt;\/thinking&gt;|<thinking>([\s\S]*?)<\/thinking>/g,
                                (match, p1, p2) => {
                                    const content = p1 || p2;
                                    return `<details class="thought-process">
                                        <summary>💭 深度思考过程</summary>
                                        <div class="thought-content">${content}</div>
                                    </details>`;
                                }
                            );
                        } else if (fullText.includes('<thinking>')) {
                            displayHtml = displayHtml.replace(
                                /&lt;thinking&gt;[\s\S]*|<thinking>[\s\S]*/,
                                '<div class="thinking-status">🧠 正在深度思考...</div>'
                            );
                        }
                        textArea.innerHTML = displayHtml;

                        this.setAvatarStatus('idle');
                        if (data.session_id) {
                            this.currentSessionId = data.session_id;
                            this.currentSessionEl.textContent = data.session_id.slice(0, 8) + '...';
                        }
                        doneReceived = true;
                        break;
                    } else if (data.type === 'error') {
                        throw new Error(data.content || '未知错误');
                    }
                }

                if (doneReceived) break;
            }

            // 流式完成后刷新一次会话列表即可
            await this.refreshSessions();
            
        } catch (error) {
            console.error('发送消息失败:', error);
            contentDiv.innerHTML = `抱歉，发送消息时出现了错误: ${error.message}`;
            this.setAvatarStatus('idle');
        }
        
        // 重新启用发送按钮
        this.sendButton.disabled = false;
        this.isTyping = false;
        this.focusInput();
    }
    
    focusInput() {
        this.messageInput.focus();
    }
    
    
    showFollowUpBubble(anchorElement, mark) {
        /**
         * 显示追问气泡
         */
        // 移除已存在的气泡
        const existingBubble = document.querySelector('.followup-bubble');
        if (existingBubble) {
            existingBubble.remove();
        }
        
        // 创建气泡
        const bubble = document.createElement('div');
        bubble.className = 'followup-bubble';
        bubble.innerHTML = `
            <div class="bubble-header">
                <span>💬 针对此内容追问</span>
                <button class="bubble-close">✕</button>
            </div>
            <div class="bubble-content">
                <p class="selected-text">"${mark.text.substring(0, 50)}${mark.text.length > 50 ? '...' : ''}"</p>
                <div class="quick-actions">
                    <button class="quick-btn" data-type="why">❓ 为什么</button>
                    <button class="quick-btn" data-type="risk">⚠️ 有啥坑</button>
                    <button class="quick-btn" data-type="alternative">🔄 替代方案</button>
                </div>
                <div class="custom-query">
                    <input type="text" placeholder="或者自定义追问..." class="custom-input">
                    <button class="send-query-btn">发送</button>
                </div>
                <div class="bubble-response"></div>
            </div>
        `;
        
        // 定位气泡
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
        
        // 绑定事件
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
        
        // 点击外部关闭
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
        
        // ESC键关闭
        const closeOnEsc = (e) => {
            if (e.key === 'Escape') {
                bubble.remove();
                document.removeEventListener('keydown', closeOnEsc);
            }
        };
        document.addEventListener('keydown', closeOnEsc);
    }
    
    async sendFollowUpQuery(mark, queryType, customQuery, bubble) {
        /**
         * 发送追问请求
         */
        const responseDiv = bubble.querySelector('.bubble-response');
        responseDiv.innerHTML = '<p class="loading">正在思考...</p>';
        
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
                responseDiv.innerHTML = `<p class="ai-response">${data.response}</p>`;
            } else {
                throw new Error('追问请求失败');
            }
        } catch (error) {
            console.error('追问失败:', error);
            responseDiv.innerHTML = '<p class="error">追问失败，请重试</p>';
        }
    }
    handleTextSelection(e) {
        /**
         * 处理文本选中事件
         */
        const selection = window.getSelection();
        const text = selection.toString().trim();
        
        // 如果没有选中文本，或选区不在聊天区域内
        if (!text || !this.chatMessages.contains(e.target)) {
            // 如果点击的是悬浮按钮本身，不要隐藏
            if (this.selectionMenu.contains(e.target) || e.target === this.quickAskBtn) {
                return;
            }
            this.selectionMenu.style.display = 'none';
            return;
        }
        
        // 显示悬浮按钮
        const range = selection.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        
        // 计算位置：在选区上方中间
        const left = rect.left + (rect.width / 2) - 40; // 按钮宽度约80px
        const top = rect.top - 40;
        
        this.selectionMenu.style.left = `${left}px`;
        this.selectionMenu.style.top = `${top}px`;
        this.selectionMenu.style.display = 'block';
    }

}

// 记忆图可视化
class MemoryGraphVisualization {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('memoryGraphModal');
        this.closeBtn = this.modal.querySelector('.close-modal');
        this.graphCanvas = document.getElementById('graphCanvas');
        this.graphStats = document.getElementById('graphStats');
        
        this.closeBtn.onclick = () => this.hide();
        window.onclick = (event) => {
            if (event.target === this.modal) this.hide();
        };
    }
    
    async show(sessionId) {
        if (!sessionId) {
            alert('请先开始一个会话');
            return;
        }
        
            this.modal.style.display = 'flex';
        this.graphStats.innerHTML = '<p>正在加载记忆图...</p>';
        this.graphCanvas.innerHTML = '';
        
        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(`${this.apiBaseUrl}/api/memory/graph/${sessionId}`, { headers });
            let data = null;
            try {
                data = await response.json();
            } catch (e) {
                data = null;
            }

            // 后端错误（例如 Neo4j 未启动/连接失败）时，避免前端因 stats 不存在而崩溃
            if (!response.ok) {
                const detail = data?.detail || data?.message || `HTTP ${response.status}`;
                this.graphStats.innerHTML = `<p style="color: #ff4141;">加载失败: ${detail}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            // 兼容后端返回 {status:"disabled"/"error"} 等情况
            if (!data || (data.status && data.status !== 'success')) {
                const msg = data?.message || (data?.status === 'disabled' ? '记忆系统未启用或未就绪' : '加载失败');
                this.graphStats.innerHTML = `<p style="color: #ffaa00;">${msg}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            this.renderStats(data.stats || null);
            this.renderGraph(data.nodes || [], data.edges || []);
        } catch (error) {
            this.graphStats.innerHTML = `<p style="color: #ff4141;">加载失败: ${error.message}</p>`;
        }
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    renderStats(stats) {
        // stats 可能为空（例如后端报错返回 detail），这里做兜底避免字段不存在
        if (!stats) {
            stats = { total_nodes: 0, total_edges: 0, layers: { hot: 0, warm: 0, cold: 0 } };
        }
        if (!stats.layers) stats.layers = { hot: 0, warm: 0, cold: 0 };
        this.graphStats.innerHTML = `
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 15px;">
                <div style="background: var(--bg-primary); padding: 10px; border-radius: 5px;">
                    <strong style="color: var(--accent);">总节点:</strong> <span style="color: var(--text-primary);">${stats.total_nodes}</span>
                </div>
                <div style="background: var(--bg-primary); padding: 10px; border-radius: 5px;">
                    <strong style="color: var(--accent);">总关系:</strong> <span style="color: var(--text-primary);">${stats.total_edges}</span>
                </div>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">
                <div style="background: var(--bg-primary); padding: 10px; border-radius: 5px; border-left: 3px solid #ff4141;">
                    <strong style="color: #ff4141;">热层 (Hot)</strong><br/>
                    <span style="color: var(--text-primary); font-size: 20px;">${stats.layers.hot || 0}</span> 节点
                </div>
                <div style="background: var(--bg-primary); padding: 10px; border-radius: 5px; border-left: 3px solid #ffaa00;">
                    <strong style="color: #ffaa00;">温层 (Warm)</strong><br/>
                    <span style="color: var(--text-primary); font-size: 20px;">${stats.layers.warm || 0}</span> 节点
                </div>
                <div style="background: var(--bg-primary); padding: 10px; border-radius: 5px; border-left: 3px solid #00ccff;">
                    <strong style="color: #00ccff;">冷层 (Cold)</strong><br/>
                    <span style="color: var(--text-primary); font-size: 20px;">${stats.layers.cold || 0}</span> 节点
                </div>
            </div>
        `;
    }
    
    renderGraph(nodes, edges) {
        const width = this.graphCanvas.clientWidth;
        const height = this.graphCanvas.clientHeight;
        
        // 清空画布
        d3.select('#graphCanvas').selectAll('*').remove();
        
        const svg = d3.select('#graphCanvas')
            .append('svg')
            .attr('width', width)
            .attr('height', height);
        
        // 添加渐变定义（神经元光晕效果）
        const defs = svg.append('defs');
        
        // 热层渐变（红色）
        const hotGradient = defs.append('radialGradient').attr('id', 'hot-glow');
        hotGradient.append('stop').attr('offset', '0%').attr('stop-color', '#ff4141').attr('stop-opacity', 1);
        hotGradient.append('stop').attr('offset', '100%').attr('stop-color', '#ff4141').attr('stop-opacity', 0);
        
        // 温层渐变（橙色）
        const warmGradient = defs.append('radialGradient').attr('id', 'warm-glow');
        warmGradient.append('stop').attr('offset', '0%').attr('stop-color', '#ffaa00').attr('stop-opacity', 1);
        warmGradient.append('stop').attr('offset', '100%').attr('stop-color', '#ffaa00').attr('stop-opacity', 0);
        
        // 冷层渐变（蓝色）
        const coldGradient = defs.append('radialGradient').attr('id', 'cold-glow');
        coldGradient.append('stop').attr('offset', '0%').attr('stop-color', '#00ccff').attr('stop-opacity', 1);
        coldGradient.append('stop').attr('offset', '100%').attr('stop-color', '#00ccff').attr('stop-opacity', 0);
        
        // 层级颜色映射
        const layerColors = {
            0: '#ff4141',  // 热层：红色
            1: '#ffaa00',  // 温层：橙色
            2: '#00ccff'   // 冷层：蓝色
        };
        
        const layerGlows = {
            0: 'url(#hot-glow)',
            1: 'url(#warm-glow)',
            2: 'url(#cold-glow)'
        };
        
        // 力导向布局（类似神经网络）
        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(d => {
                // 根据层级调整距离
                const sourceLayer = d.source.layer || 0;
                const targetLayer = d.target.layer || 0;
                return 80 + Math.abs(sourceLayer - targetLayer) * 40;
            }))
            .force('charge', d3.forceManyBody().strength(-500))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => 15 + d.layer * 5 + d.importance * 15))
            .force('y', d3.forceY().y(d => {
                // 根据层级分布 Y 位置（热层在下，冷层在上）
                const layerHeight = height / 4;
                return height - (d.layer + 1) * layerHeight;
            }).strength(0.3));
        
        // 绘制连接线（带动画效果）
        const link = svg.append('g')
            .attr('class', 'links')
            .selectAll('line')
            .data(edges)
            .enter().append('line')
            .attr('stroke', d => {
                // 根据源节点层级着色
                const sourceNode = nodes.find(n => n.id === d.source.id || n.id === d.source);
                return sourceNode ? layerColors[sourceNode.layer] || '#00ff41' : '#00ff41';
            })
            .attr('stroke-opacity', d => 0.3 + d.weight * 0.3)
            .attr('stroke-width', d => Math.max(0.5, d.weight * 2))
            .style('filter', 'blur(0.5px)');
        
        const nodeGroup = svg.append('g')
            .attr('class', 'nodes')
            .selectAll('g')
            .data(nodes)
            .enter().append('g')
            .attr('class', 'node')
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));
        
        // 外部光晕（神经元效果）
        nodeGroup.append('circle')
            .attr('r', d => 20 + d.layer * 5 + d.importance * 20)
            .attr('fill', d => layerGlows[d.layer] || 'url(#hot-glow)')
            .attr('opacity', 0.3)
            .style('pointer-events', 'none');
        
        // 主节点
        nodeGroup.append('circle')
            .attr('r', d => 8 + d.layer * 2 + d.importance * 8)
            .attr('fill', d => layerColors[d.layer] || '#00ff41')
            .attr('stroke', d => d3.rgb(layerColors[d.layer] || '#00ff41').brighter(1))
            .attr('stroke-width', 2)
            .attr('opacity', d => 0.7 + d.importance * 0.3)
            .style('filter', 'drop-shadow(0 0 5px ' + (d => layerColors[d.layer] || '#00ff41') + ')');
        
        // 内核（模拟神经元核心）
        nodeGroup.append('circle')
            .attr('r', d => 3 + d.importance * 3)
            .attr('fill', '#ffffff')
            .attr('opacity', 0.8);
        
        // 文本标签
        nodeGroup.append('text')
            .text(d => {
                // 根据节点类型简化显示
                if (d.type === 'concept') return '💡';
                if (d.type === 'summary') return '📝';
                if (d.type === 'entity') return d.content.substring(0, 8);
                return d.content.substring(0, 10);
            })
            .attr('x', 0)
            .attr('y', d => -(10 + d.layer * 2 + d.importance * 10))
            .attr('text-anchor', 'middle')
            .attr('font-size', '10px')
            .attr('fill', d => layerColors[d.layer] || '#00ff41')
            .attr('font-weight', 'bold')
            .style('pointer-events', 'none')
            .style('text-shadow', '0 0 3px #000');
        
        // 悬浮提示
        nodeGroup.append('title')
            .text(d => {
                const layerName = ['热层 (Hot)', '温层 (Warm)', '冷层 (Cold)'][d.layer] || '未知层';
                return `${layerName} - ${d.type}\n` +
                       `内容: ${d.content}\n` +
                       `重要性: ${(d.importance * 100).toFixed(0)}%\n` +
                       `访问: ${d.access_count || 0}次`;
            });
        
        // 添加呼吸动画效果
        nodeGroup.selectAll('circle')
            .transition()
            .duration(2000)
            .ease(d3.easeSinInOut)
            .attr('r', function() {
                const r = d3.select(this).attr('r');
                return r * 1.1;
            })
            .transition()
            .duration(2000)
            .ease(d3.easeSinInOut)
            .attr('r', function() {
                const r = d3.select(this).attr('r') / 1.1;
                return r;
            })
            .on('end', function repeat() {
                d3.select(this)
                    .transition()
                    .duration(2000)
                    .ease(d3.easeSinInOut)
                    .attr('r', function() {
                        const r = d3.select(this).attr('r');
                        return r * 1.1;
                    })
                    .transition()
                    .duration(2000)
                    .ease(d3.easeSinInOut)
                    .attr('r', function() {
                        const r = d3.select(this).attr('r') / 1.1;
                        return r;
                    })
                    .on('end', repeat);
            });
        
        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            
            nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`);
        });
        
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
    }
}

// 设置管理
class SettingsManager {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('settingsModal');
        this.closeBtn = this.modal.querySelector('.close-modal');
        this.form = document.getElementById('settingsForm');
        this.loadingEl = document.querySelector('.settings-loading');
        this.resetBtn = document.getElementById('resetBtn');
        this.originalConfig = null;
        
        this.closeBtn.onclick = () => this.hide();
        window.onclick = (event) => {
            if (event.target === this.modal) this.hide();
        };
        
        this.form.onsubmit = (e) => this.handleSubmit(e);
        this.resetBtn.onclick = () => this.loadConfig();
        
        // 绑定按钮事件
        document.getElementById('bindBtn').addEventListener('click', () => this.handleBindChannel());
    }
    
    async show() {
            this.modal.style.display = 'flex';
        await this.loadConfig();
        await this.loadBoundChannels();
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    async loadConfig() {
        try {
            this.loadingEl.style.display = 'block';
            this.form.style.display = 'none';
            
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            
            // 加载系统配置
            const response = await fetch(`${this.apiBaseUrl}/api/config`, { headers });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.originalConfig = data.config;
                this.populateForm(data.config);
            }
            
            // 加载用户配置
            const userResp = await fetch(`${this.apiBaseUrl}/api/user/profile`, { headers });
            if (userResp.ok) {
                const userData = await userResp.json();
                this.setFieldValue('userAgentName', userData.agent_name);
                this.setFieldValue('userSystemPrompt', userData.system_prompt);
                
                // 填充用户 API 配置
                if (userData.api) {
                    this.setFieldValue('userApiKey', userData.api.api_key);
                    this.setFieldValue('userBaseUrl', userData.api.base_url);
                    this.setFieldValue('userModel', userData.api.model);
                    this.setFieldValue('userTemperature', userData.api.temperature);
                    this.setFieldValue('userMaxTokens', userData.api.max_tokens);
                }
            }
            
                this.loadingEl.style.display = 'none';
                this.form.style.display = 'block';
            
        } catch (error) {
            this.loadingEl.innerHTML = `<p style="color: #ff4141;">加载失败: ${error.message}</p>`;
        }
    }
    
    async loadBoundChannels() {
        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(`${this.apiBaseUrl}/api/user/channels`, { headers });
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
                        <span class="status-badge">已绑定</span>
                    `;
                    listEl.appendChild(item);
                }
            }
        } catch (error) {
            console.error('加载绑定渠道失败:', error);
        }
    }
    
    getChannelIcon(channel) {
        const icons = {
            'telegram': '✈️',
            'wechat': '💬',
            'dingtalk': '钉',
            'feishu': '🐦'
        };
        return icons[channel] || '🔗';
    }
    
    async handleBindChannel() {
        const channel = document.getElementById('bindChannelType').value;
        const accountId = document.getElementById('bindAccountId').value.trim();
        
        if (!accountId) {
            alert('请输入账号ID');
            return;
        }
        
        try {
            const token = localStorage.getItem('auth_token');
            const headers = {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            };
            
            const response = await fetch(`${this.apiBaseUrl}/api/user/channels/bind`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ channel, account_id: accountId })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                alert('✅ 绑定成功！');
                document.getElementById('bindAccountId').value = '';
                this.loadBoundChannels();
            } else {
                throw new Error(data.detail || '绑定失败');
            }
        } catch (error) {
            alert(`❌ 绑定失败: ${error.message}`);
        }
    }
    
    populateForm(config) {
        // API配置
        this.setFieldValue('apiKey', config.api.api_key);
        this.setFieldValue('baseUrl', config.api.base_url);
        this.setFieldValue('model', config.api.model);
        this.setFieldValue('temperature', config.api.temperature);
        this.setFieldValue('maxTokens', config.api.max_tokens);
        this.setFieldValue('maxHistoryRounds', config.api.max_history_rounds);
        
        // 系统配置
        this.setFieldValue('streamMode', config.system.stream_mode, 'checkbox');
        this.setFieldValue('debugMode', config.system.debug, 'checkbox');
        this.setFieldValue('logLevel', config.system.log_level);
        
        // 记忆系统配置
        this.setFieldValue('memoryEnabled', config.memory.enabled, 'checkbox');
        this.setFieldValue('neo4jEnabled', config.memory.neo4j.enabled, 'checkbox');
        this.setFieldValue('neo4jUri', config.memory.neo4j.uri);
        this.setFieldValue('neo4jUsername', config.memory.neo4j.username);
        this.setFieldValue('neo4jDatabase', config.memory.neo4j.database);
        this.setFieldValue('warmLayerEnabled', config.memory.warm_layer.enabled, 'checkbox');
        this.setFieldValue('clusteringThreshold', config.memory.warm_layer.clustering_threshold);
        this.setFieldValue('minClusterSize', config.memory.warm_layer.min_cluster_size);
        this.setFieldValue('maxSummaryLength', config.memory.cold_layer.max_summary_length);
        this.setFieldValue('compressionThreshold', config.memory.cold_layer.compression_threshold);
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
        
        const formData = new FormData(this.form);
        const config = this.buildConfigObject(formData);
        const token = localStorage.getItem('auth_token');
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        };
        
        try {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = true;
            submitBtn.textContent = '正在保存...';
            
            // 1. 保存用户配置
            const userConfig = {
                agent_name: formData.get('user.agent_name'),
                system_prompt: formData.get('user.system_prompt'),
                api: {
                    api_key: formData.get('user.api.api_key') || null,
                    base_url: formData.get('user.api.base_url') || null,
                    model: formData.get('user.api.model') || null,
                    temperature: formData.get('user.api.temperature') ? parseFloat(formData.get('user.api.temperature')) : null,
                    max_tokens: formData.get('user.api.max_tokens') ? parseInt(formData.get('user.api.max_tokens')) : null
                }
            };
            
            await fetch(`${this.apiBaseUrl}/api/user/config`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(userConfig)
            });
            
            // 更新本地缓存
            if (userConfig.agent_name) {
                localStorage.setItem('agent_name', userConfig.agent_name);
            }
            
            // 2. 保存系统配置
            const response = await fetch(`${this.apiBaseUrl}/api/config`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ config })
            });
            
            const data = await response.json();
            
            if (data.status === 'success') {
                alert('✅ 配置已保存并生效！');
                this.hide();
            } else {
                throw new Error(data.message || '保存失败');
            }
        } catch (error) {
            alert(`❌ 保存失败: ${error.message}`);
        } finally {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = false;
            submitBtn.textContent = '保存并应用';
        }
    }
    
    buildConfigObject(formData) {
        const config = {
            api: {},
            system: {},
            memory: {
                neo4j: {},
                warm_layer: {},
                cold_layer: {}
            }
        };
        
        for (let [name, value] of formData.entries()) {
            const parts = name.split('.');
            let current = config;
            
            for (let i = 0; i < parts.length - 1; i++) {
                if (!current[parts[i]]) {
                    current[parts[i]] = {};
                }
                current = current[parts[i]];
            }
            
            const lastPart = parts[parts.length - 1];
            const field = this.form.querySelector(`[name="${name}"]`);
            
            if (field.type === 'checkbox') {
                current[lastPart] = field.checked;
            } else if (field.type === 'number') {
                current[lastPart] = parseFloat(value);
            } else {
                current[lastPart] = value;
            }
        }
        
        return config;
    }
}

// 性能统计管理器
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
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(`${this.apiBaseUrl}/api/metrics`, { headers });
            const data = await response.json();
            
            if (data.status === 'success') {
                this.updateDisplay(data.metrics);
            }
        } catch (error) {
            console.error('获取统计数据失败:', error);
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
        
        const uptime = metrics.uptime_seconds;
        const hours = Math.floor(uptime / 3600);
        const minutes = Math.floor((uptime % 3600) / 60);
        const secs = uptime % 60;
        document.getElementById('uptime').textContent = hours > 0 ? `${hours}h ${minutes}m` : minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
    }
}

// 系统自检（Doctor）管理器
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
        this.outputEl.textContent = '正在运行系统自检，请稍候...\n';

        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(`${this.apiBaseUrl}/api/doctor`, { headers });
            const data = await response.json();

            const lines = [];
            lines.push(`状态: ${data.status || 'unknown'}`);
            lines.push(`时间: ${data.timestamp || ''}`);
            lines.push('');

            const checks = data.checks || {};
            for (const [key, value] of Object.entries(checks)) {
                const ok = value.ok !== false;
                lines.push(`■ ${key} => ${ok ? 'OK' : 'ERROR'}`);
                if (value.issues && Array.isArray(value.issues) && value.issues.length > 0) {
                    for (const issue of value.issues) {
                        lines.push(`   - ${issue}`);
                    }
                }
                // 对于 config/memory/plugins/mcp 等，附加一些关键字段做简要展示
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
            this.outputEl.textContent = `自检失败: ${error.message}`;
        }
    }

    async migrateConfig() {
        if (!this.outputEl) return;
        this.outputEl.textContent = '正在修复 / 迁移配置，请稍候...\n';

        try {
            const token = localStorage.getItem('auth_token');
            const headers = {
                'Content-Type': 'application/json',
            };
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }

            const response = await fetch(`${this.apiBaseUrl}/api/doctor/migrate-config`, {
                method: 'POST',
                headers,
                body: JSON.stringify({}),
            });
            const data = await response.json();

            const lines = [];
            if (response.ok && data.status === 'success') {
                lines.push(`状态: success`);
                if (data.message) lines.push(data.message);
                if (data.config_path) lines.push(`配置文件: ${data.config_path}`);
                if (data.backup) lines.push(`已创建备份: ${data.backup}`);
            } else {
                lines.push(`状态: ${data.status || 'error'}`);
                lines.push(`错误: ${data.message || '修复失败'}`);
                if (data.config_path) lines.push(`配置文件: ${data.config_path}`);
                if (data.backup) lines.push(`备份: ${data.backup}`);
            }

            this.outputEl.textContent = lines.join('\n');
        } catch (error) {
            this.outputEl.textContent = `自检修复失败: ${error.message}`;
        }
    }
}

// 虚拟形象管理
class AvatarManager {
    constructor() {
        this.placeholder = document.getElementById('avatarPlaceholder');
        this.uploadInput = document.getElementById('avatarUpload');
        this.avatarImage = document.getElementById('avatarImage');
        this.avatarIcon = document.getElementById('avatarIcon');
        this.avatarHint = document.getElementById('avatarHint');
        this.removeBtn = document.getElementById('removeAvatarBtn');
        
        this.bindEvents();
        this.loadAvatar();
    }
    
    bindEvents() {
        // 点击占位区域触发上传
        this.placeholder.addEventListener('click', (e) => {
            if (e.target !== this.removeBtn) {
                this.uploadInput.click();
            }
        });
        
        // 文件选择
        this.uploadInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file && file.type.startsWith('image/')) {
                this.setAvatar(file);
            }
        });
        
        // 移除按钮
        this.removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.removeAvatar();
        });
    }
    
    setAvatar(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const imageData = e.target.result;
            
            // 显示图片
            this.avatarImage.src = imageData;
            this.avatarImage.style.display = 'block';
            this.avatarIcon.style.display = 'none';
            this.avatarHint.style.display = 'none';
            this.removeBtn.style.display = 'flex';
            
            // 保存到localStorage
            localStorage.setItem('avatar_image', imageData);
            
            console.log('✅ 虚拟形象已设置');
        };
        reader.readAsDataURL(file);
    }
    
    removeAvatar() {
        // 隐藏图片
        this.avatarImage.style.display = 'none';
        this.avatarImage.src = '';
        this.avatarIcon.style.display = 'block';
        this.avatarHint.style.display = 'block';
        this.removeBtn.style.display = 'none';
        
        // 从localStorage移除
        localStorage.removeItem('avatar_image');
        
        console.log('✅ 虚拟形象已移除');
    }
    
    loadAvatar() {
        // 从localStorage加载
        const savedImage = localStorage.getItem('avatar_image');
        if (savedImage) {
            this.avatarImage.src = savedImage;
            this.avatarImage.style.display = 'block';
            this.avatarIcon.style.display = 'none';
            this.avatarHint.style.display = 'none';
            this.removeBtn.style.display = 'flex';
        }
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', () => {
    const app = new TerminalChatApp();
    const memoryViz = new MemoryGraphVisualization(app.apiBaseUrl);
    const settingsManager = new SettingsManager(app.apiBaseUrl);
    const metricsManager = new MetricsManager(app.apiBaseUrl);
    const doctorManager = new DoctorManager(app.apiBaseUrl);
    const avatarManager = new AvatarManager();
    
    document.getElementById('memoryGraphBtn').addEventListener('click', () => {
        memoryViz.show(app.currentSessionId);
    });
    
    document.getElementById('settingsBtn').addEventListener('click', () => {
        settingsManager.show();
    });
});
