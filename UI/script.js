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
        
        this.apiBaseUrl = 'http://127.0.0.1:8000';
        this.currentSessionId = null;
        this.isTyping = false;
        
        this.bindEvents();
        this.initializeApp();
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
                this.showFollowUpBubble(mark, rect);
                
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
    }
    
    async checkApiStatus() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/status`);
            if (response.ok) {
                const data = await response.json();
                this.updateStatus(this.apiStatusEl, true);
                
                // 检查记忆系统状态（通过config接口）
                this.checkMemoryStatus();
            } else {
                this.updateStatus(this.apiStatusEl, false);
            }
        } catch (error) {
            this.updateStatus(this.apiStatusEl, false);
            console.log('❌ 无法连接到API服务');
        }
    }
    
    async checkMemoryStatus() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/config`);
            if (response.ok) {
                const data = await response.json();
                const memoryEnabled = data.config.memory.enabled && data.config.memory.neo4j.enabled;
                this.updateStatus(this.memoryStatusEl, memoryEnabled);
            }
        } catch (e) {
            this.updateStatus(this.memoryStatusEl, false);
        }
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
    
    addMessage(role, content, uncertainMarks = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        // 处理换行符
        let formattedContent = content.replace(/\n/g, '<br>');
        
        // 如果有不确定标记，添加标记
        if (uncertainMarks && uncertainMarks.length > 0) {
            formattedContent = this.markUncertainText(formattedContent, uncertainMarks);
        }
        
        contentDiv.innerHTML = formattedContent;
        
        messageDiv.appendChild(contentDiv);
        this.chatMessages.appendChild(messageDiv);
        
        // 如果有不确定标记，绑定点击事件
        if (uncertainMarks && uncertainMarks.length > 0) {
            this.bindUncertainClickHandlers(contentDiv, uncertainMarks);
        }
        
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
            const response = await fetch(`${this.apiBaseUrl}/api/sessions`);
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
            const response = await fetch(`${this.apiBaseUrl}/api/sessions/${sessionId}`);
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
        contentDiv.innerHTML = '正在思考...';
        messageDiv.appendChild(contentDiv);
        this.chatMessages.appendChild(messageDiv);
        
        try {
            // 调用后端API（流式）
            const response = await fetch(`${this.apiBaseUrl}/api/chat`, {
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
            
            contentDiv.innerHTML = '';  // 清空"正在思考"
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();  // 保留不完整的行
                
                for (const line of lines) {
                    if (!line.trim()) continue;
                    
                    try {
                        const data = JSON.parse(line);
                        
                        if (data.type === 'text') {
                            // 流式文本
                            fullText += data.content;
                            
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
                            
                            contentDiv.innerHTML = displayHtml;
                            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                            
                            // 设置说话状态
                            this.setAvatarStatus('speaking');
                            
                        } else if (data.type === 'done') {
                            // 完成
                            this.setAvatarStatus('idle');
                            
                            if (data.session_id) {
                                this.currentSessionId = data.session_id;
                                this.currentSessionEl.textContent = data.session_id.slice(0, 8) + '...';
                            }
                
                        } else if (data.type === 'error') {
                            throw new Error(data.content);
                        }
                    } catch (e) {
                        console.warn('解析SSE数据失败:', line, e);
                    }
                }
            }
            
            // 刷新会话列表
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
                <p class="uncertain-text">"${mark.text.substring(0, 50)}${mark.text.length > 50 ? '...' : ''}"</p>
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
            if (!bubble.contains(e.target) && !anchorElement.contains(e.target)) {
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
            const response = await fetch(`${this.apiBaseUrl}/api/followup`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    uncertain_text: mark.text,
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
        
        this.modal.style.display = 'block';
        this.graphStats.innerHTML = '<p>正在加载记忆图...</p>';
        this.graphCanvas.innerHTML = '';
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/memory/graph/${sessionId}`);
            const data = await response.json();
            
            this.renderStats(data.stats);
            this.renderGraph(data.nodes, data.edges);
        } catch (error) {
            this.graphStats.innerHTML = `<p style="color: #ff4141;">加载失败: ${error.message}</p>`;
        }
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    renderStats(stats) {
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
    }
    
    async show() {
        this.modal.style.display = 'block';
        await this.loadConfig();
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    async loadConfig() {
        try {
            this.loadingEl.style.display = 'block';
            this.form.style.display = 'none';
            
            const response = await fetch(`${this.apiBaseUrl}/api/config`);
            const data = await response.json();
            
            if (data.status === 'success') {
                this.originalConfig = data.config;
                this.populateForm(data.config);
                this.loadingEl.style.display = 'none';
                this.form.style.display = 'block';
            } else {
                throw new Error('加载配置失败');
            }
        } catch (error) {
            this.loadingEl.innerHTML = `<p style="color: #ff4141;">加载失败: ${error.message}</p>`;
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
        
        // 置信度检测配置
        if (config.ui && config.ui.uncertainty_detection) {
            this.setFieldValue('uncertaintyEnabled', config.ui.uncertainty_detection.enabled, 'checkbox');
            this.setFieldValue('showCritical', config.ui.uncertainty_detection.show_critical, 'checkbox');
            this.setFieldValue('showHigh', config.ui.uncertainty_detection.show_high, 'checkbox');
            this.setFieldValue('showMedium', config.ui.uncertainty_detection.show_medium, 'checkbox');
            this.setFieldValue('minMarkDistance', config.ui.uncertainty_detection.min_mark_distance || 80);
            this.setFieldValue('signalThreshold', config.ui.uncertainty_detection.signal_threshold || 0.6);
        }
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
        
        try {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = true;
            submitBtn.textContent = '正在保存...';
            
            const response = await fetch(`${this.apiBaseUrl}/api/config`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
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
            },
            ui: {
                uncertainty_detection: {}
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
    constructor() {
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
        this.modal.style.display = 'block';
        await this.loadMetrics();
    }
    
    hide() {
        this.modal.style.display = 'none';
    }
    
    async loadMetrics() {
        try {
            const response = await fetch('http://127.0.0.1:8000/api/metrics');
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
    const metricsManager = new MetricsManager();
    const avatarManager = new AvatarManager();
    
    document.getElementById('memoryGraphBtn').addEventListener('click', () => {
        memoryViz.show(app.currentSessionId);
    });
    
    document.getElementById('settingsBtn').addEventListener('click', () => {
        settingsManager.show();
    });
});
