const I18N = {
    zh: {
        lang_name: "简体中文",
        auth_login: "🔐 登录",
        auth_register: "📝 注册",
        auth_submit_login: "登录",
        auth_submit_register: "注册并创建 Agent",
        auth_switch_to_register: "去注册",
        auth_switch_to_login: "去登录",
        auth_no_account: "还没有账号？",
        auth_has_account: "已有账号？",
        auth_register_success: "注册成功，请登录",
        auth_welcome_back: "欢迎回来！{agent} 已准备就绪。",
        auth_failed: "操作失败",
        auth_invalid: "认证失效，请重新登录",
        logout_confirm: "确定要退出登录吗？",
        chat_placeholder: "输入你的问题...",
        chat_need_session: "请先开始一个会话",
        memory_loading: "正在加载记忆图...",
        memory_disabled: "记忆系统未启用或未就绪",
        memory_fail: "加载失败: {msg}",
        memory_no_data: "当前筛选条件无数据",
        memory_no_nodes: "暂无可展示的记忆节点",
        memory_select_detail: "选择左侧节点查看详情",
        memory_action_fail: "{label}失败: {msg}",
        app_welcome: "欢迎使用普罗米娅AI助手！\n\n我是你的智能对话伙伴，可以帮你：\n• 回答问题\n• 分析文档\n• 编写代码\n• 创意写作\n\n开始对话吧！",
        ui_memory_workbench: "🧠 记忆工作台",
        ui_lang_title: "选择语言 / Choose Language",
        ui_lang_desc: "请选择界面语言（后端日志不受影响）",
        ui_metrics: "📊 性能统计",
        ui_doctor: "🩺 系统自检 Doctor",
        ui_settings: "⚙️ 系统设置",
        ui_memory: "🧠 记忆工作台",
        ui_memory_cluster: "聚类",
        ui_memory_summary: "摘要",
        ui_memory_decay: "衰减",
        ui_memory_cleanup: "清理",
        ui_memory_refresh: "刷新",
        ui_memory_node_list: "节点列表",
        ui_memory_node_detail: "节点详情",
        ui_memory_filter_all_layers: "全部层级",
        ui_memory_filter_all_types: "全部类型",
        ui_memory_search_placeholder: "搜索记忆内容 / 节点ID / 类型...",
        ui_memory_total_nodes: "总节点",
        ui_memory_total_edges: "总关系",
        ui_memory_hot: "热层 Hot",
        ui_memory_warm: "温层 Warm",
        ui_memory_cold: "冷层 Cold",
        ui_memory_detail_id: "ID",
        ui_memory_detail_type: "类型",
        ui_memory_detail_layer: "层级",
        ui_memory_detail_importance: "重要性",
        ui_memory_detail_access: "访问次数",
        ui_memory_detail_edges: "关联边",
        ui_sessions: "会话历史",
        ui_chat_tab: "对话",
        ui_current_session: "当前会话",
        ui_not_started: "未开始",
        ui_auth_username: "用户名",
        ui_auth_password: "密码",
        ui_auth_agent_name: "Agent 名字",
        ui_auth_username_placeholder: "请输入用户名",
        ui_auth_password_placeholder: "请输入密码",
        ui_auth_agent_placeholder: "给你的助手起个名字 (默认: Promethea)",
        ui_app_title: "普罗米娅AI助手 - 终端版",
        ui_logo_text: "普罗米娅",
        ui_new_chat_title: "新建会话",
        ui_avatar_hint: "点击上传形象",
        ui_avatar_remove_title: "移除形象",
        ui_api_status_title: "API连接状态",
        ui_memory_status_title: "记忆系统状态",
        ui_logout_title: "退出登录",
        ui_doctor_title: "系统自检 Doctor",
        ui_metrics_title: "性能统计",
        ui_settings_title: "系统设置",
        ui_memory_graph_title: "查看记忆图",
        ui_confirm_title: "⚠️ 敏感操作确认",
        ui_confirm_desc: "Agent 尝试执行以下高风险操作，需要您的批准：",
        ui_confirm_tool: "工具:",
        ui_confirm_args: "参数:",
        ui_confirm_reject: "拒绝",
        ui_confirm_approve: "批准执行",
        ui_metrics_token: "Token消耗",
        ui_metrics_cost: "估算成本",
        ui_metrics_llm: "LLM调用",
        ui_metrics_avg: "平均",
        ui_metrics_memory: "记忆召回",
        ui_metrics_session_message: "会话/消息",
        ui_metrics_uptime: "运行时长",
        ui_doctor_run: "重新体检",
        ui_doctor_fix: "修复 / 迁移配置",
        ui_quickask_btn: "🤔 追问",
        ui_thinking: "正在思考...",
        ui_thinking_deep: "🧠 正在深度思考...",
        ui_thinking_process: "💭 深度思考过程",
        ui_tool_detected: "检测到工具调用...",
        ui_followup_title: "💬 针对此内容追问",
        ui_followup_why: "❓ 为什么",
        ui_followup_risk: "⚠️ 有啥坑",
        ui_followup_alt: "🔄 替代方案",
        ui_followup_custom: "或者自定义追问...",
        ui_followup_send: "发送",
        ui_followup_fail: "追问失败，请重试",
        ui_bind_need_id: "请输入账号ID",
        ui_bind_success: "✅ 绑定成功！",
        ui_bind_fail: "❌ 绑定失败: {msg}",
        ui_save_progress: "正在保存...",
        ui_save_success: "✅ 配置已保存并生效！",
        ui_save_fail: "❌ 保存失败: {msg}",
        ui_save_btn: "保存并应用",
        ui_settings_loading: "正在加载配置...",
        ui_settings_load_fail: "加载失败: {msg}",
        ui_settings_reset: "重置",
        ui_rejected: "❌ 已拒绝执行该操作。",
        ui_tool_running: "🔧 调用工具：{name}（运行中）",
        ui_tool_done: "🔧 调用工具：{name}（已完成）",
        ui_tool_failed: "工具调用失败",
        ui_error_unknown: "未知错误",
        ui_switch_session_fail: "切换会话失败: {msg}",
        ui_settings_personal: "👤 个性化设置",
        ui_settings_personal_api: "🔑 个人 API 配置 (可选)",
        ui_settings_personal_api_hint: "在此填写的配置将覆盖系统默认值。留空则使用默认配置。",
        ui_settings_bind: "🔗 社交账号绑定",
        ui_settings_sys_api: "🔑 API 配置",
        ui_settings_sys: "⚡ 系统配置",
        ui_settings_memory: "🧠 记忆系统",
        ui_label_user_agent: "Agent 名字",
        ui_label_user_prompt: "自定义 System Prompt",
        ui_placeholder_user_prompt: "自定义你的 Agent 人设...",
        ui_label_user_model: "模型名称",
        ui_label_bind_account: "输入账号ID (如 Telegram User ID)",
        ui_bind_btn: "绑定",
        ui_label_model: "模型",
        ui_label_history_rounds: "历史轮数",
        ui_label_stream_mode: "流式输出",
        ui_label_debug_mode: "调试模式",
        ui_label_log_level: "日志级别",
        ui_label_memory_enabled: "启用记忆系统",
        ui_label_neo4j_enabled: "启用Neo4j",
        ui_label_neo4j_user: "用户名",
        ui_label_neo4j_db: "数据库",
        ui_label_warm_enabled: "启用温层",
        ui_label_cluster_threshold: "聚类阈值",
        ui_label_min_cluster: "最小簇大小",
        ui_label_summary_len: "摘要长度",
        ui_label_compress_threshold: "压缩阈值",
        ui_status_running_doctor: "正在运行系统自检，请稍候...",
        ui_status_running_migrate: "正在修复 / 迁移配置，请稍候...",
        ui_memory_btn_short: "记忆",
        ui_api_short: "API",
        ui_memory_short: "记忆",
        ui_delete_user: "注销",
        memory_sync_idle: "记忆同步空闲",
        memory_sync_running: "记忆同步中: {pending}",
        memory_sync_error: "记忆同步异常",
        memory_sync_wait_close: "记忆同步尚未完成，请稍候再关闭页面。",
    },
    en: {
        lang_name: "English",
        auth_login: "🔐 Sign In",
        auth_register: "📝 Sign Up",
        auth_submit_login: "Sign In",
        auth_submit_register: "Sign Up & Create Agent",
        auth_switch_to_register: "Sign Up",
        auth_switch_to_login: "Sign In",
        auth_no_account: "Don't have an account?",
        auth_has_account: "Already have an account?",
        auth_register_success: "Registration successful, please sign in.",
        auth_welcome_back: "Welcome back! {agent} is ready.",
        auth_failed: "Operation failed",
        auth_invalid: "Authentication expired, please sign in again.",
        logout_confirm: "Are you sure you want to sign out?",
        chat_placeholder: "Type your question...",
        chat_need_session: "Please start a session first.",
        memory_loading: "Loading memory graph...",
        memory_disabled: "Memory system is disabled or unavailable.",
        memory_fail: "Load failed: {msg}",
        memory_no_data: "No nodes match current filters.",
        memory_no_nodes: "No memory nodes to display.",
        memory_select_detail: "Select a node to view details",
        memory_action_fail: "{label} failed: {msg}",
        app_welcome: "Welcome to Promethea AI Assistant!\n\nI can help you with:\n• Q&A\n• Document analysis\n• Coding\n• Creative writing\n\nLet's start.",
        ui_memory_workbench: "🧠 Memory Workbench",
        ui_lang_title: "Choose Language / 选择语言",
        ui_lang_desc: "Choose UI language (backend logs stay unchanged).",
        ui_metrics: "📊 Metrics",
        ui_doctor: "🩺 System Doctor",
        ui_settings: "⚙️ Settings",
        ui_memory: "🧠 Memory Workbench",
        ui_memory_cluster: "Cluster",
        ui_memory_summary: "Summarize",
        ui_memory_decay: "Decay",
        ui_memory_cleanup: "Cleanup",
        ui_memory_refresh: "Refresh",
        ui_memory_node_list: "Node List",
        ui_memory_node_detail: "Node Details",
        ui_memory_filter_all_layers: "All Layers",
        ui_memory_filter_all_types: "All Types",
        ui_memory_search_placeholder: "Search content / node id / type...",
        ui_memory_total_nodes: "Total Nodes",
        ui_memory_total_edges: "Total Edges",
        ui_memory_hot: "Hot Layer",
        ui_memory_warm: "Warm Layer",
        ui_memory_cold: "Cold Layer",
        ui_memory_detail_id: "ID",
        ui_memory_detail_type: "Type",
        ui_memory_detail_layer: "Layer",
        ui_memory_detail_importance: "Importance",
        ui_memory_detail_access: "Access",
        ui_memory_detail_edges: "Edges",
        ui_sessions: "Sessions",
        ui_chat_tab: "Chat",
        ui_current_session: "Current Session",
        ui_not_started: "Not Started",
        ui_auth_username: "Username",
        ui_auth_password: "Password",
        ui_auth_agent_name: "Agent Name",
        ui_auth_username_placeholder: "Enter username",
        ui_auth_password_placeholder: "Enter password",
        ui_auth_agent_placeholder: "Name your assistant (default: Promethea)",
        ui_app_title: "Promethea AI Assistant - Terminal",
        ui_logo_text: "Promethea",
        ui_new_chat_title: "New chat",
        ui_avatar_hint: "Click to upload avatar",
        ui_avatar_remove_title: "Remove avatar",
        ui_api_status_title: "API connection status",
        ui_memory_status_title: "Memory system status",
        ui_logout_title: "Sign out",
        ui_doctor_title: "System Doctor",
        ui_metrics_title: "Metrics",
        ui_settings_title: "Settings",
        ui_memory_graph_title: "View memory graph",
        ui_confirm_title: "⚠️ Sensitive Action Confirmation",
        ui_confirm_desc: "Agent is requesting to execute the following high-risk action:",
        ui_confirm_tool: "Tool:",
        ui_confirm_args: "Arguments:",
        ui_confirm_reject: "Reject",
        ui_confirm_approve: "Approve",
        ui_metrics_token: "Token Usage",
        ui_metrics_cost: "Estimated Cost",
        ui_metrics_llm: "LLM Calls",
        ui_metrics_avg: "Average",
        ui_metrics_memory: "Memory Recalls",
        ui_metrics_session_message: "Sessions/Messages",
        ui_metrics_uptime: "Uptime",
        ui_doctor_run: "Run Again",
        ui_doctor_fix: "Fix / Migrate Config",
        ui_quickask_btn: "🤔 Follow-up",
        ui_thinking: "Thinking...",
        ui_thinking_deep: "🧠 Deep thinking...",
        ui_thinking_process: "💭 Thinking Process",
        ui_tool_detected: "Tool call detected...",
        ui_followup_title: "💬 Ask about this selection",
        ui_followup_why: "❓ Why",
        ui_followup_risk: "⚠️ Risks",
        ui_followup_alt: "🔄 Alternatives",
        ui_followup_custom: "Or enter a custom follow-up...",
        ui_followup_send: "Send",
        ui_followup_fail: "Follow-up failed, please retry.",
        ui_bind_need_id: "Please enter account ID.",
        ui_bind_success: "✅ Bound successfully!",
        ui_bind_fail: "❌ Bind failed: {msg}",
        ui_save_progress: "Saving...",
        ui_save_success: "✅ Configuration saved and applied!",
        ui_save_fail: "❌ Save failed: {msg}",
        ui_save_btn: "Save & Apply",
        ui_settings_loading: "Loading configuration...",
        ui_settings_load_fail: "Load failed: {msg}",
        ui_settings_reset: "Reset",
        ui_rejected: "❌ Action rejected.",
        ui_tool_running: "🔧 Tool call: {name} (running)",
        ui_tool_done: "🔧 Tool call: {name} (done)",
        ui_tool_failed: "Tool call failed",
        ui_error_unknown: "Unknown error",
        ui_switch_session_fail: "Switch session failed: {msg}",
        ui_settings_personal: "👤 Personalization",
        ui_settings_personal_api: "🔑 Personal API Config (Optional)",
        ui_settings_personal_api_hint: "Values here override system defaults. Leave empty to use defaults.",
        ui_settings_bind: "🔗 Social Account Binding",
        ui_settings_sys_api: "🔑 API Config",
        ui_settings_sys: "⚡ System Config",
        ui_settings_memory: "🧠 Memory System",
        ui_label_user_agent: "Agent Name",
        ui_label_user_prompt: "Custom System Prompt",
        ui_placeholder_user_prompt: "Customize your agent persona...",
        ui_label_user_model: "Model",
        ui_label_bind_account: "Enter account ID (e.g., Telegram User ID)",
        ui_bind_btn: "Bind",
        ui_label_model: "Model",
        ui_label_history_rounds: "History Rounds",
        ui_label_stream_mode: "Streaming",
        ui_label_debug_mode: "Debug Mode",
        ui_label_log_level: "Log Level",
        ui_label_memory_enabled: "Enable Memory",
        ui_label_neo4j_enabled: "Enable Neo4j",
        ui_label_neo4j_user: "Username",
        ui_label_neo4j_db: "Database",
        ui_label_warm_enabled: "Enable Warm Layer",
        ui_label_cluster_threshold: "Clustering Threshold",
        ui_label_min_cluster: "Min Cluster Size",
        ui_label_summary_len: "Summary Length",
        ui_label_compress_threshold: "Compression Threshold",
        ui_status_running_doctor: "Running system doctor, please wait...",
        ui_status_running_migrate: "Fixing / migrating configuration, please wait...",
        ui_memory_btn_short: "Memory",
        ui_api_short: "API",
        ui_memory_short: "Memory",
        ui_delete_user: "Delete",
        memory_sync_idle: "Memory sync idle",
        memory_sync_running: "Memory syncing: {pending}",
        memory_sync_error: "Memory sync error",
        memory_sync_wait_close: "Memory sync is still running. Please wait before leaving.",
    },
};

Object.assign(I18N.zh, {
    ui_tools_live: "工具",
    ui_tools_loading: "正在加载工具...",
    ui_tools_empty: "暂无可用工具",
    ui_tools_error: "工具列表加载失败",
    ui_tools_more: "还有 {count} 个工具",
});

Object.assign(I18N.en, {
    ui_tools_live: "Tools",
    ui_tools_loading: "Loading tools...",
    ui_tools_empty: "No tools available",
    ui_tools_error: "Failed to load tools",
    ui_tools_more: "{count} more tools",
});

function getCurrentLang() {
    return localStorage.getItem("ui_lang") || "zh";
}

function t(key, vars = {}) {
    const lang = getCurrentLang();
    const dict = I18N[lang] || I18N.zh;
    const raw = dict[key] || I18N.zh[key] || key;
    return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), raw);
}

class LanguageManager {
    constructor() {
        this.modal = document.getElementById("languageModal");
        this.zhBtn = document.getElementById("langZhBtn");
        this.enBtn = document.getElementById("langEnBtn");
        this.switchBtn = document.getElementById("langSwitchBtn");
        this.langTitle = document.getElementById("languageTitle");
        this.langDesc = document.getElementById("languageDesc");
    }

    bindEvents() {
        this.zhBtn?.addEventListener("click", () => this.setLanguage("zh"));
        this.enBtn?.addEventListener("click", () => this.setLanguage("en"));
        this.switchBtn?.addEventListener("click", () => this.openModal());
        this.modal?.addEventListener("click", (e) => {
            if (e.target === this.modal) this.closeModal();
        });
    }

    init() {
        this.bindEvents();
        this.applyLanguage();
        if (!localStorage.getItem("ui_lang")) {
            this.openModal();
        }
    }

    openModal() {
        if (this.modal) this.modal.style.display = "flex";
    }

    closeModal() {
        if (this.modal) this.modal.style.display = "none";
    }

    setLanguage(lang) {
        localStorage.setItem("ui_lang", lang);
        this.applyLanguage();
        this.closeModal();
    }

    applyLanguage() {
        document.title = t("ui_app_title");
        const logoText = document.querySelector(".logo-text");
        if (logoText) logoText.textContent = t("ui_logo_text");
        const newChatBtn = document.getElementById("newChatBtn");
        if (newChatBtn) newChatBtn.title = t("ui_new_chat_title");
        const avatarHint = document.getElementById("avatarHint");
        if (avatarHint) avatarHint.textContent = t("ui_avatar_hint");
        const removeAvatarBtn = document.getElementById("removeAvatarBtn");
        if (removeAvatarBtn) removeAvatarBtn.title = t("ui_avatar_remove_title");
        const apiStatus = document.getElementById("apiStatus");
        if (apiStatus) apiStatus.title = t("ui_api_status_title");
        const memoryStatus = document.getElementById("memoryStatus");
        if (memoryStatus) memoryStatus.title = t("ui_memory_status_title");
        if (apiStatus) apiStatus.innerHTML = `<span class="dot"></span> ${t("ui_api_short")}`;
        if (memoryStatus) memoryStatus.innerHTML = `<span class="dot"></span> ${t("ui_memory_short")}`;
        const toolsLiveTitle = document.getElementById("toolsLiveTitle");
        if (toolsLiveTitle) toolsLiveTitle.textContent = t("ui_tools_live");
        const toolsLiveEmpty = document.getElementById("toolsLiveEmpty");
        if (toolsLiveEmpty) toolsLiveEmpty.textContent = t("ui_tools_loading");
        const logoutBtn = document.getElementById("logoutBtn");
        if (logoutBtn) logoutBtn.title = t("ui_logout_title");
        const doctorBtn = document.getElementById("doctorBtn");
        if (doctorBtn) doctorBtn.title = t("ui_doctor_title");
        const metricsBtn = document.getElementById("metricsBtn");
        if (metricsBtn) metricsBtn.title = t("ui_metrics_title");
        const settingsBtn = document.getElementById("settingsBtn");
        if (settingsBtn) settingsBtn.title = t("ui_settings_title");
        const memoryGraphBtn = document.getElementById("memoryGraphBtn");
        if (memoryGraphBtn) memoryGraphBtn.title = t("ui_memory_graph_title");
        if (doctorBtn) doctorBtn.textContent = t("ui_doctor");
        if (metricsBtn) metricsBtn.textContent = t("ui_metrics");
        if (settingsBtn) settingsBtn.textContent = t("ui_settings");
        if (memoryGraphBtn) memoryGraphBtn.textContent = t("ui_memory_btn_short");
        const langSwitchBtn = document.getElementById("langSwitchBtn");
        if (langSwitchBtn) langSwitchBtn.title = getCurrentLang() === "en" ? "Language" : "语言";
        if (langSwitchBtn) langSwitchBtn.textContent = t("lang_name");
        const logoutBtnText = document.getElementById("logoutBtn");
        if (logoutBtnText) logoutBtnText.textContent = t("ui_logout_title");
        const userDeleteBtn = document.getElementById("userDeleteBtn");
        if (userDeleteBtn) userDeleteBtn.textContent = t("ui_delete_user");

        if (this.langTitle) this.langTitle.textContent = t("ui_lang_title");
        if (this.langDesc) this.langDesc.textContent = t("ui_lang_desc");

        const messageInput = document.getElementById("messageInput");
        if (messageInput) messageInput.placeholder = t("chat_placeholder");

        const metricsTitle = document.querySelector("#metricsModal .modal-header h2");
        if (metricsTitle) metricsTitle.textContent = t("ui_metrics");
        const doctorTitle = document.querySelector("#doctorModal .modal-header h2");
        if (doctorTitle) doctorTitle.textContent = t("ui_doctor");
        const settingsTitle = document.querySelector("#settingsModal .modal-header h2");
        if (settingsTitle) settingsTitle.textContent = t("ui_settings");
        const memoryTitle = document.querySelector("#memoryGraphModal .modal-header h2");
        if (memoryTitle) memoryTitle.textContent = t("ui_memory");

        const memorySearchInput = document.getElementById("memorySearchInput");
        if (memorySearchInput) memorySearchInput.placeholder = t("ui_memory_search_placeholder");
        const memoryLayerFilter = document.getElementById("memoryLayerFilter");
        if (memoryLayerFilter?.options?.[0]) memoryLayerFilter.options[0].text = t("ui_memory_filter_all_layers");
        const memoryTypeFilter = document.getElementById("memoryTypeFilter");
        if (memoryTypeFilter?.options?.[0]) memoryTypeFilter.options[0].text = t("ui_memory_filter_all_types");
        const memoryClusterBtn = document.getElementById("memoryClusterBtn");
        if (memoryClusterBtn) memoryClusterBtn.textContent = t("ui_memory_cluster");
        const memorySummarizeBtn = document.getElementById("memorySummarizeBtn");
        if (memorySummarizeBtn) memorySummarizeBtn.textContent = t("ui_memory_summary");
        const memoryDecayBtn = document.getElementById("memoryDecayBtn");
        if (memoryDecayBtn) memoryDecayBtn.textContent = t("ui_memory_decay");
        const memoryCleanupBtn = document.getElementById("memoryCleanupBtn");
        if (memoryCleanupBtn) memoryCleanupBtn.textContent = t("ui_memory_cleanup");
        const memoryRefreshBtn = document.getElementById("memoryRefreshBtn");
        if (memoryRefreshBtn) memoryRefreshBtn.textContent = t("ui_memory_refresh");
        const memoryNodeListTitle = document.getElementById("memoryNodeListTitle");
        if (memoryNodeListTitle) memoryNodeListTitle.textContent = t("ui_memory_node_list");
        const memoryNodeDetailTitle = document.getElementById("memoryNodeDetailTitle");
        if (memoryNodeDetailTitle) memoryNodeDetailTitle.textContent = t("ui_memory_node_detail");

        const confirmTitle = document.querySelector("#confirmModal .modal-header h2");
        if (confirmTitle) confirmTitle.textContent = t("ui_confirm_title");
        const confirmDesc = document.querySelector("#confirmModal .modal-body p");
        if (confirmDesc) confirmDesc.textContent = t("ui_confirm_desc");
        const confirmToolLabel = document.querySelector("#confirmModal .detail-row:first-child .label");
        if (confirmToolLabel) confirmToolLabel.textContent = t("ui_confirm_tool");
        const confirmArgsLabel = document.querySelector("#confirmModal .detail-row:nth-child(2) .label");
        if (confirmArgsLabel) confirmArgsLabel.textContent = t("ui_confirm_args");
        const rejectToolBtn = document.getElementById("rejectToolBtn");
        if (rejectToolBtn) rejectToolBtn.textContent = t("ui_confirm_reject");
        const approveToolBtn = document.getElementById("approveToolBtn");
        if (approveToolBtn) approveToolBtn.textContent = t("ui_confirm_approve");

        const sessionHeaderText = document.querySelector(".session-list-header span:first-child");
        if (sessionHeaderText) sessionHeaderText.textContent = t("ui_sessions");
        const tabTitle = document.querySelector(".tab-title");
        if (tabTitle) tabTitle.textContent = t("ui_chat_tab");
        const currentSessionLabel = document.getElementById("currentSessionLabel");
        if (currentSessionLabel) currentSessionLabel.textContent = t("ui_current_session");
        const currentSessionValue = document.getElementById("currentSession");
        if (currentSessionValue && (currentSessionValue.textContent === "未开始" || currentSessionValue.textContent === "Not Started")) {
            currentSessionValue.textContent = t("ui_not_started");
        }

        const usernameLabel = document.querySelector('label[for="username"]');
        if (usernameLabel) usernameLabel.textContent = t("ui_auth_username");
        const passwordLabel = document.querySelector('label[for="password"]');
        if (passwordLabel) passwordLabel.textContent = t("ui_auth_password");
        const agentNameLabel = document.querySelector('label[for="agentName"]');
        if (agentNameLabel) agentNameLabel.textContent = t("ui_auth_agent_name");
        const usernameInput = document.getElementById("username");
        if (usernameInput) usernameInput.placeholder = t("ui_auth_username_placeholder");
        const passwordInput = document.getElementById("password");
        if (passwordInput) passwordInput.placeholder = t("ui_auth_password_placeholder");
        const agentNameInput = document.getElementById("agentName");
        if (agentNameInput) agentNameInput.placeholder = t("ui_auth_agent_placeholder");

        const metricsCards = document.querySelectorAll("#metricsModal .metric-card .metric-label");
        if (metricsCards[0]) metricsCards[0].textContent = t("ui_metrics_token");
        if (metricsCards[1]) metricsCards[1].textContent = t("ui_metrics_llm");
        if (metricsCards[2]) metricsCards[2].textContent = t("ui_metrics_memory");
        if (metricsCards[3]) metricsCards[3].textContent = t("ui_metrics_session_message");
        const metricSubs = document.querySelectorAll("#metricsModal .metric-card .metric-sub");
        if (metricSubs[0]) metricSubs[0].innerHTML = `${t("ui_metrics_cost")}: $<span id="estimatedCost">0.00</span>`;
        if (metricSubs[1]) metricSubs[1].innerHTML = `${t("ui_metrics_avg")}: <span id="avgLlmTime">0</span>ms`;
        if (metricSubs[2]) metricSubs[2].innerHTML = `${t("ui_metrics_avg")}: <span id="avgMemoryTime">0</span>ms`;
        if (metricSubs[3]) metricSubs[3].innerHTML = `${t("ui_metrics_uptime")}: <span id="uptime">0</span>s`;

        const doctorRunBtn = document.getElementById("doctorRunBtn");
        if (doctorRunBtn) doctorRunBtn.textContent = t("ui_doctor_run");
        const doctorFixBtn = document.getElementById("doctorFixConfigBtn");
        if (doctorFixBtn) doctorFixBtn.textContent = t("ui_doctor_fix");
        const quickAskBtn = document.getElementById("quickAskBtn");
        if (quickAskBtn) quickAskBtn.textContent = t("ui_quickask_btn");
        const settingsLoading = document.querySelector(".settings-loading");
        if (settingsLoading) settingsLoading.textContent = t("ui_settings_loading");
        const resetBtn = document.getElementById("resetBtn");
        if (resetBtn) resetBtn.textContent = t("ui_settings_reset");
        const saveBtn = document.querySelector("#settingsForm .settings-actions .btn-primary");
        if (saveBtn) saveBtn.textContent = t("ui_save_btn");

        const sec = document.querySelectorAll("#settingsForm .settings-section h3");
        if (sec[0]) sec[0].textContent = t("ui_settings_personal");
        if (sec[1]) sec[1].textContent = t("ui_settings_personal_api");
        if (sec[2]) sec[2].textContent = t("ui_settings_bind");
        if (sec[3]) sec[3].textContent = t("ui_settings_sys_api");
        if (sec[4]) sec[4].textContent = t("ui_settings_sys");
        if (sec[5]) sec[5].textContent = t("ui_settings_memory");
        const personalHint = document.querySelector("#settingsForm .settings-section:nth-of-type(2) .settings-hint");
        if (personalHint) personalHint.textContent = t("ui_settings_personal_api_hint");

        const setLabel = (selector, key) => {
            const el = document.querySelector(selector);
            if (el) el.textContent = t(key);
        };
        setLabel('label[for="userAgentName"]', 'ui_label_user_agent');
        setLabel('label[for="userSystemPrompt"]', 'ui_label_user_prompt');
        setLabel('label[for="userModel"]', 'ui_label_user_model');
        setLabel('label[for="model"]', 'ui_label_model');
        setLabel('label[for="maxHistoryRounds"]', 'ui_label_history_rounds');
        setLabel('label[for="logLevel"]', 'ui_label_log_level');
        setLabel('label[for="neo4jUsername"]', 'ui_label_neo4j_user');
        setLabel('label[for="neo4jDatabase"]', 'ui_label_neo4j_db');
        setLabel('label[for="clusteringThreshold"]', 'ui_label_cluster_threshold');
        setLabel('label[for="minClusterSize"]', 'ui_label_min_cluster');
        setLabel('label[for="maxSummaryLength"]', 'ui_label_summary_len');
        setLabel('label[for="compressionThreshold"]', 'ui_label_compress_threshold');

        const streamSpan = document.querySelector('input#streamMode + span');
        if (streamSpan) streamSpan.textContent = t("ui_label_stream_mode");
        const debugSpan = document.querySelector('input#debugMode + span');
        if (debugSpan) debugSpan.textContent = t("ui_label_debug_mode");
        const memSpan = document.querySelector('input#memoryEnabled + span');
        if (memSpan) memSpan.textContent = t("ui_label_memory_enabled");
        const neo4jSpan = document.querySelector('input#neo4jEnabled + span');
        if (neo4jSpan) neo4jSpan.textContent = t("ui_label_neo4j_enabled");
        const warmSpan = document.querySelector('input#warmLayerEnabled + span');
        if (warmSpan) warmSpan.textContent = t("ui_label_warm_enabled");
        const bindBtn = document.getElementById('bindBtn');
        if (bindBtn) bindBtn.textContent = t("ui_bind_btn");
        const bindInput = document.getElementById('bindAccountId');
        if (bindInput) bindInput.placeholder = t("ui_label_bind_account");
        const userPrompt = document.getElementById('userSystemPrompt');
        if (userPrompt) userPrompt.placeholder = t("ui_placeholder_user_prompt");

        window.dispatchEvent(new CustomEvent("ui-language-changed", { detail: { lang: getCurrentLang() } }));
    }
}

// Authentication manager
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
        const token = localStorage.getItem('auth_token');
        if (token) {
            this.modal.style.display = 'none';
            if (this.onLoginSuccess) this.onLoginSuccess();
        } else {
            this.modal.style.display = 'flex'; // Use flex layout so the modal stays centered
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
            
            const response = await fetch(`${this.apiBaseUrl}${endpoint}`, {
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
                // Auto-fill username after successful registration
                document.getElementById('username').value = data.username;
                document.getElementById('password').value = '';
            } else {
                localStorage.setItem('auth_token', result.access_token);
                localStorage.setItem('user_id', result.user_id);
                localStorage.setItem('agent_name', result.agent_name);
                if (result.username) {
                    localStorage.setItem('username', result.username);
                }
                
                this.modal.style.display = 'none';
                if (this.onLoginSuccess) this.onLoginSuccess();
                
                // Welcome hint
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
    
    logout() {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user_id');
        localStorage.removeItem('agent_name');
        localStorage.removeItem('username');
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
        
        // Additional UI elements
        this.apiStatusEl = document.getElementById('apiStatus');
        this.memoryStatusEl = document.getElementById('memoryStatus');
        this.toolsLiveCountEl = document.getElementById('toolsLiveCount');
        this.toolsLiveListEl = document.getElementById('toolsLiveList');
        this.memorySyncIndicatorEl = document.getElementById('memorySyncIndicator');
        this.memorySyncTextEl = document.getElementById('memorySyncText');
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebarToggle');
        this.avatarPlaceholder = document.getElementById('avatarPlaceholder');
        this.logoutBtn = document.getElementById('logoutBtn');
        
        // Confirmation modal elements
        this.confirmModal = document.getElementById('confirmModal');
        this.confirmToolName = document.getElementById('confirmToolName');
        this.confirmToolArgs = document.getElementById('confirmToolArgs');
        this.approveToolBtn = document.getElementById('approveToolBtn');
        this.rejectToolBtn = document.getElementById('rejectToolBtn');
        this.pendingConfirmation = null;
        
        this.apiBaseUrl = 'http://127.0.0.1:8000';
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
        // Mapping: tool_call_id -> corresponding DOM elements
        this.toolCallElements = new Map();
        
        // Initialise authentication manager and start app after login
        this.authManager = new AuthManager(this.apiBaseUrl, () => this.initializeApp());
        
        this.bindEvents();
        // this.initializeApp(); // Called after login succeeds
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
        // Sidebar toggle
        this.sidebarToggle.addEventListener('click', () => {
            this.sidebar.classList.toggle('open');
        });
        
        // On mobile, clicking the main area closes the sidebar
        document.querySelector('.terminal-container').addEventListener('click', () => {
            if (window.innerWidth <= 768 && this.sidebar.classList.contains('open')) {
                this.sidebar.classList.remove('open');
            }
        });

        // Send button click handler
        this.sendButton.addEventListener('click', () => this.sendMessage());
        
        // Press Enter to send (Shift+Enter inserts a newline)
        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        // Enable or disable the send button depending on input content
        this.messageInput.addEventListener('input', () => {
            this.sendButton.disabled = !this.messageInput.value.trim();
        });

        // Follow-up-on-selection mechanism
        this.selectionMenu = document.getElementById('selectionMenu');
        this.quickAskBtn = document.getElementById('quickAskBtn');
        
        document.addEventListener('mouseup', (e) => this.handleTextSelection(e));
        
        // Follow-up button click
        this.quickAskBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent closing the menu when clicking on the button itself
            const selection = window.getSelection();
            const text = selection.toString().trim();
            if (text) {
                // Get bounding rect of the selection for bubble positioning
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                
                // Build a lightweight mark object
                const mark = { text: text };
                
                // Show follow-up bubble
                this.showFollowUpBubble(rect, mark);
                
                // Hide the floating quick-ask button
                this.selectionMenu.style.display = 'none';
                window.getSelection().removeAllRanges();
            }
        });
        
        // Hide the selection menu when clicking elsewhere
        document.addEventListener('mousedown', (e) => {
            if (!this.selectionMenu.contains(e.target) && e.target !== this.quickAskBtn) {
                this.selectionMenu.style.display = 'none';
            }
        });
        
        // New chat session button
        this.newChatBtn.addEventListener('click', () => {
            this.startNewChat();
        });
        
        // Auto focus styling for the input wrapper
        this.messageInput.addEventListener('focus', () => {
            this.messageInput.parentElement.classList.add('is-focused');
        });
        
        this.messageInput.addEventListener('blur', () => {
            this.messageInput.parentElement.classList.remove('is-focused');
        });

        // Logout button
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

        // Confirmation modal actions
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
            this.addMessage('assistant', t("ui_rejected"));
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
            } else if (response.ok && (data.status === 'success' || data.success === true)) {
                // 显示结果
                this.addMessage('assistant', data.response);
                this.sendButton.disabled = false;
                this.isTyping = false;
                this.setAvatarStatus('idle');
            } else if (data.status === 'rejected') {
                // 已拒绝
            } else {
                throw new Error(data.message || t("auth_failed"));
            }
            
        } catch (error) {
            console.error('确认操作失败:', error);
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
        
        // 使用 flex 与 .modal 的布局方式保持一致，确保模态在屏幕中居中展示
        this.confirmModal.style.display = 'flex';
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

        this.toolsLiveCountEl.textContent = String(tools.length || 0);
        this.toolsLiveListEl.innerHTML = "";

        if (errorMessage) {
            const empty = document.createElement("div");
            empty.className = "tools-live-empty";
            empty.textContent = errorMessage;
            this.toolsLiveListEl.appendChild(empty);
            return;
        }

        if (!tools.length) {
            const empty = document.createElement("div");
            empty.className = "tools-live-empty";
            empty.textContent = t("ui_tools_empty");
            this.toolsLiveListEl.appendChild(empty);
            return;
        }

        const maxVisible = 8;
        const visible = tools.slice(0, maxVisible);
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

        if (tools.length > maxVisible) {
            const more = document.createElement("div");
            more.className = "tools-live-empty";
            more.textContent = t("ui_tools_more", { count: tools.length - maxVisible });
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
        // status: 'thinking' | 'speaking' | 'idle'
        this.avatarPlaceholder.classList.remove('thinking', 'speaking');
        if (status !== 'idle') {
            this.avatarPlaceholder.classList.add(status);
        }
    }
    
    addWelcomeMessage() {
        this.addMessage('assistant', t("app_welcome"));
    }
    
    addMessage(role, content, options = {}) {
        const animate = options.animate !== false;
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
            // Keep cached/placeholder username if profile fetch fails.
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
            const response = await this.fetchWithAuth(`${this.apiBaseUrl}/api/sessions`);
            if (!response.ok) throw new Error(getCurrentLang() === 'en' ? 'Failed to fetch sessions' : '获取会话列表失败');
            
            const data = await response.json();
            const sessions = data.sessions || [];
            
            // 更新会话数量
            this.sessionCountEl.textContent = sessions.length;
            
            // 清空并重新渲染会话列表
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
                
                // 生成会话标题（使用最后一条消息的前20个字符）
                const title = session.last_message && session.last_message.trim() 
                    ? session.last_message.slice(0, 20) + (session.last_message.length > 20 ? '...' : '')
                    : (getCurrentLang() === 'en' ? 'New session' : '新的会话');
                
                li.textContent = title;
                li.title = getCurrentLang() === 'en'
                    ? `Session ID: ${session.session_id}\nCreated: ${new Date(session.created_at * 1000).toLocaleString()}\nMessages: ${session.message_count}`
                    : `会话ID: ${session.session_id}\n创建时间: ${new Date(session.created_at * 1000).toLocaleString()}\n消息数量: ${session.message_count}`;
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
            if (!response.ok) throw new Error(getCurrentLang() === 'en' ? 'Failed to fetch session detail' : '获取会话详情失败');
            
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
                    this.addMessage(msg.role, msg.content, { animate: false });
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
            this.addMessage('assistant', t("ui_switch_session_fail", { msg: error.message }));
        }
    }
    
    startNewChat() {
        this.currentSessionId = null;
        this.currentSessionEl.textContent = t("ui_not_started");
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
            <div class="text-area">${t("ui_thinking")}</div>
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
            const contentType = (response.headers.get('content-type') || '').toLowerCase();
            if (!response.body || contentType.includes('application/json')) {
                const data = await response.json().catch(() => ({}));
                const text = data?.response || data?.content || data?.message || '';
                textArea.innerHTML = String(text).replace(/\n/g, '<br>');
                this.setAvatarStatus('idle');
                if (data?.session_id) {
                    this.currentSessionId = data.session_id;
                    this.currentSessionEl.textContent = data.session_id.slice(0, 8) + '...';
                }
                await this.refreshSessions();
                return;
            }
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
                    let trimmed = line.trim();
                    if (!trimmed) continue;
                    // Support standard SSE framing: "data: {...}".
                    if (trimmed.startsWith('data:')) {
                        trimmed = trimmed.slice(5).trim();
                    }
                    if (!trimmed || trimmed === '[DONE]') continue;

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
                                        <summary>${t("ui_thinking_process")}</summary>
                                        <div class="thought-content">${content}</div>
                                    </details>`;
                                }
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
                        hint.textContent = data.content || t("ui_tool_detected");
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
                        this.toolCallElements.set(callId, { details, summary, resultPre });
                        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                    } else if (data.type === 'tool_result') {
                        const callId = data.call_id;
                        const entry = this.toolCallElements.get(callId);
                        const resultText = data.result || '';
                        if (entry) {
                            entry.resultPre.textContent = resultText;
                            entry.summary.textContent = t("ui_tool_done", { name: data.tool_name || 'tool' });
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
                        err.textContent = data.content || t("ui_tool_failed");
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
                        doneReceived = true;
                        break;
                    } else if (data.type === 'error') {
                        throw new Error(data.content || t("ui_error_unknown"));
                    }
                }

                if (doneReceived) break;
            }

            // 流式完成后刷新一次会话列表即可
            await this.refreshSessions();
            
        } catch (error) {
            console.error('发送消息失败:', error);
            contentDiv.innerHTML = `${t("auth_failed")}: ${error.message}`;
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
                <span>${t("ui_followup_title")}</span>
                <button class="bubble-close">✕</button>
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
                responseDiv.innerHTML = `<p class="ai-response">${data.response}</p>`;
            } else {
                throw new Error(getCurrentLang() === 'en' ? 'Follow-up request failed' : '追问请求失败');
            }
        } catch (error) {
            console.error('追问失败:', error);
            responseDiv.innerHTML = `<p class="error">${t("ui_followup_fail")}</p>`;
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
        this.searchInput = document.getElementById('memorySearchInput');
        this.layerFilter = document.getElementById('memoryLayerFilter');
        this.typeFilter = document.getElementById('memoryTypeFilter');
        this.nodeList = document.getElementById('memoryNodeList');
        this.nodeDetail = document.getElementById('memoryNodeDetail');
        this.nodeCount = document.getElementById('memoryNodeCount');
        this.openNeo4jBtn = document.getElementById('memoryOpenNeo4jBtn');
        this.refreshBtn = document.getElementById('memoryRefreshBtn');
        this.clusterBtn = document.getElementById('memoryClusterBtn');
        this.summarizeBtn = document.getElementById('memorySummarizeBtn');
        this.decayBtn = document.getElementById('memoryDecayBtn');
        this.cleanupBtn = document.getElementById('memoryCleanupBtn');

        this.currentSessionId = null;
        this.rawNodes = [];
        this.rawEdges = [];
        this.filteredNodes = [];
        this.filteredEdges = [];
        this.selectedNodeId = null;
        this.simulation = null;
        this.svg = null;
        this.graphLayer = null;

        this.bindEvents();
    }

    bindEvents() {
        this.closeBtn.addEventListener('click', () => this.hide());
        this.modal.addEventListener('click', (event) => {
            if (event.target === this.modal) this.hide();
        });

        this.searchInput?.addEventListener('input', () => this.applyFilters());
        this.layerFilter?.addEventListener('change', () => this.applyFilters());
        this.typeFilter?.addEventListener('change', () => this.applyFilters());
        this.openNeo4jBtn?.addEventListener('click', () => this.openNeo4jBrowser());
        this.refreshBtn?.addEventListener('click', () => this.refreshGraph());
        this.clusterBtn?.addEventListener('click', () => this.runMemoryAction('cluster', 'ui_memory_cluster'));
        this.summarizeBtn?.addEventListener('click', () => this.runMemoryAction('summarize', 'ui_memory_summary'));
        this.decayBtn?.addEventListener('click', () => this.runMemoryAction('decay', 'ui_memory_decay'));
        this.cleanupBtn?.addEventListener('click', () => this.runMemoryAction('cleanup', 'ui_memory_cleanup'));
    }
    
    async show(sessionId) {
        this.currentSessionId = sessionId || null;
        this.modal.style.display = 'flex';
        await this.refreshGraph();
    }

    hide() {
        this.modal.style.display = 'none';
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }
    }

    async refreshGraph() {
        this.graphStats.innerHTML = `<p>${t("memory_loading")}</p>`;
        this.graphCanvas.innerHTML = '';
        this.nodeList.innerHTML = '';
        this.nodeDetail.textContent = t("memory_select_detail");
        this.nodeCount.textContent = '0';

        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const graphUrl = this.currentSessionId
                ? `${this.apiBaseUrl}/api/memory/graph/${this.currentSessionId}`
                : `${this.apiBaseUrl}/api/memory/graph`;
            const response = await fetch(graphUrl, { headers });
            let data = null;
            try {
                data = await response.json();
            } catch (e) {
                data = null;
            }

            if (!response.ok) {
                const detail = data?.detail || data?.message || `HTTP ${response.status}`;
                this.graphStats.innerHTML = `<p class="error">${t("memory_fail", { msg: detail })}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            if (!data || (data.status && data.status !== 'success')) {
                const msg = data?.message || (data?.status === 'disabled' ? t("memory_disabled") : t("auth_failed"));
                this.graphStats.innerHTML = `<p class="thinking-status">${msg}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            this.rawNodes = data.nodes || [];
            this.rawEdges = data.edges || [];
            this.populateTypeFilter(this.rawNodes);
            this.renderStats(data.stats || null);
            this.applyFilters();
        } catch (error) {
            this.graphStats.innerHTML = `<p class="error">${t("memory_fail", { msg: error.message })}</p>`;
        }
    }

    populateTypeFilter(nodes) {
        if (!this.typeFilter) return;
        const keepValue = this.typeFilter.value || 'all';
        const types = [...new Set(nodes.map(n => n.type).filter(Boolean))].sort();
        this.typeFilter.innerHTML = `<option value="all">${t("ui_memory_filter_all_types")}</option>`;
        for (const type of types) {
            const opt = document.createElement('option');
            opt.value = type;
            opt.textContent = type;
            this.typeFilter.appendChild(opt);
        }
        this.typeFilter.value = types.includes(keepValue) ? keepValue : 'all';
    }

    applyFilters() {
        const query = (this.searchInput?.value || '').trim().toLowerCase();
        const layer = this.layerFilter?.value || 'all';
        const type = this.typeFilter?.value || 'all';

        this.filteredNodes = this.rawNodes.filter((node) => {
            const hitQuery = !query
                || (node.content || '').toLowerCase().includes(query)
                || (node.id || '').toLowerCase().includes(query)
                || (node.type || '').toLowerCase().includes(query);
            const hitLayer = layer === 'all' || String(node.layer) === layer;
            const hitType = type === 'all' || node.type === type;
            return hitQuery && hitLayer && hitType;
        });

        const nodeSet = new Set(this.filteredNodes.map(n => n.id));
        this.filteredEdges = this.rawEdges.filter((edge) => {
            const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
            const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
            return nodeSet.has(source) && nodeSet.has(target);
        });

        this.renderNodeList(this.filteredNodes);
        this.renderGraph(this.filteredNodes, this.filteredEdges);
        this.nodeCount.textContent = String(this.filteredNodes.length);
    }

    renderStats(stats) {
        if (!stats) {
            stats = { total_nodes: 0, total_edges: 0, layers: { hot: 0, warm: 0, cold: 0 } };
        }
        if (!stats.layers) stats.layers = { hot: 0, warm: 0, cold: 0 };
        this.graphStats.innerHTML = `
            <div class="memory-stat-grid">
                <div class="memory-stat-card">
                    <strong>${t("ui_memory_total_nodes")}</strong>
                    <span>${stats.total_nodes}</span>
                </div>
                <div class="memory-stat-card">
                    <strong>${t("ui_memory_total_edges")}</strong>
                    <span>${stats.total_edges}</span>
                </div>
                <div class="memory-stat-card hot">
                    <strong>${t("ui_memory_hot")}</strong>
                    <span>${stats.layers.hot || 0}</span>
                </div>
                <div class="memory-stat-card warm">
                    <strong>${t("ui_memory_warm")}</strong>
                    <span>${stats.layers.warm || 0}</span>
                </div>
                <div class="memory-stat-card cold">
                    <strong>${t("ui_memory_cold")}</strong>
                    <span>${stats.layers.cold || 0}</span>
                </div>
            </div>
        `;
    }

    renderNodeList(nodes) {
        this.nodeList.innerHTML = '';
        if (!nodes.length) {
            this.nodeList.innerHTML = `<div class="memory-node-item empty">${t("memory_no_data")}</div>`;
            return;
        }

        const sorted = [...nodes].sort((a, b) => (b.importance || 0) - (a.importance || 0));
        for (const node of sorted) {
            const item = document.createElement('button');
            item.className = `memory-node-item layer-${node.layer}`;
            item.dataset.nodeId = node.id;
            item.innerHTML = `
                <div class="memory-node-title">${this.escapeHtml(node.content || '(empty)')}</div>
                <div class="memory-node-meta">
                    <span>${this.escapeHtml(node.type || 'unknown')}</span>
                    <span>imp ${(node.importance || 0).toFixed(2)}</span>
                    <span>acc ${node.access_count || 0}</span>
                </div>
            `;
            item.addEventListener('click', () => this.selectNode(node.id));
            this.nodeList.appendChild(item);
        }
    }

    selectNode(nodeId) {
        this.selectedNodeId = nodeId;
        const node = this.filteredNodes.find(n => n.id === nodeId) || this.rawNodes.find(n => n.id === nodeId);
        if (!node) return;

        const layerName = [t("ui_memory_hot"), t("ui_memory_warm"), t("ui_memory_cold")][node.layer] || `Layer ${node.layer ?? '?'}`;
        const linkedCount = this.rawEdges.filter((edge) => {
            const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
            const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
            return source === nodeId || target === nodeId;
        }).length;

        this.nodeDetail.innerHTML = `
            <div class="memory-detail-row"><span>${t("ui_memory_detail_id")}</span><code>${this.escapeHtml(node.id || '')}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_type")}</span><code>${this.escapeHtml(node.type || '')}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_layer")}</span><code>${layerName}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_importance")}</span><code>${(node.importance || 0).toFixed(3)}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_access")}</span><code>${node.access_count || 0}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_edges")}</span><code>${linkedCount}</code></div>
            <div class="memory-detail-content">${this.escapeHtml(node.content || '')}</div>
        `;

        this.nodeList.querySelectorAll('.memory-node-item').forEach((el) => {
            el.classList.toggle('active', el.dataset.nodeId === nodeId);
        });

        if (this.graphLayer) {
            this.graphLayer.selectAll('.memory-node').classed('selected', d => d.id === nodeId);
            this.graphLayer.selectAll('.memory-edge').classed('related', d => {
                const source = typeof d.source === 'object' ? d.source.id : d.source;
                const target = typeof d.target === 'object' ? d.target.id : d.target;
                return source === nodeId || target === nodeId;
            });
        }
    }

    renderGraph(nodes, edges) {
        const width = this.graphCanvas.clientWidth;
        const height = this.graphCanvas.clientHeight;

        d3.select(this.graphCanvas).selectAll('*').remove();
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }

        if (!nodes.length) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_no_nodes")}</div>`;
            return;
        }

        const layerColors = { 0: '#ff5a6b', 1: '#f59e0b', 2: '#0ea5e9' };

        const svg = d3.select(this.graphCanvas)
            .append('svg')
            .attr('width', width)
            .attr('height', height);

        const zoomLayer = svg.append('g').attr('class', 'memory-zoom-layer');
        this.graphLayer = zoomLayer;

        svg.call(
            d3.zoom()
                .scaleExtent([0.2, 4])
                .on('zoom', (event) => {
                    zoomLayer.attr('transform', event.transform);
                })
        );

        this.simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(95).strength(0.18))
            .force('charge', d3.forceManyBody().strength(-280))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => 10 + (d.importance || 0) * 14))
            .force('y', d3.forceY().y(d => {
                const ratio = d.layer === 0 ? 0.75 : d.layer === 1 ? 0.5 : 0.25;
                return height * ratio;
            }).strength(0.2));

        const simulation = this.simulation;

        const link = zoomLayer.append('g')
            .attr('class', 'memory-edges')
            .selectAll('line')
            .data(edges)
            .enter()
            .append('line')
            .attr('class', 'memory-edge')
            .attr('stroke', '#64748b')
            .attr('stroke-opacity', d => Math.min(0.85, 0.18 + ((d.weight || 1) * 0.22)))
            .attr('stroke-width', d => Math.max(1, (d.weight || 1) * 1.4));

        const nodeGroup = zoomLayer.append('g')
            .attr('class', 'memory-nodes')
            .selectAll('g')
            .data(nodes)
            .enter()
            .append('g')
            .attr('class', 'memory-node')
            .on('click', (_, d) => this.selectNode(d.id))
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        nodeGroup.append('circle')
            .attr('r', d => 12 + (d.importance || 0) * 14)
            .attr('fill', d => layerColors[d.layer] || '#94a3b8')
            .attr('stroke', '#fff')
            .attr('stroke-width', 1.8);

        nodeGroup.append('circle')
            .attr('r', d => 4 + (d.importance || 0) * 4)
            .attr('fill', 'rgba(255,255,255,0.9)');

        nodeGroup.append('text')
            .text(d => (d.content || '').slice(0, 12))
            .attr('x', 0)
            .attr('y', d => -(13 + (d.importance || 0) * 12))
            .attr('text-anchor', 'middle')
            .attr('font-size', '11px')
            .attr('fill', '#1e293b')
            .attr('font-weight', 700)
            .style('paint-order', 'stroke')
            .style('stroke', '#ffffff')
            .style('stroke-width', 4)
            .style('stroke-linecap', 'round')
            .style('stroke-linejoin', 'round');

        nodeGroup.append('title')
            .text(d => `${d.type || 'node'} | ${(d.content || '').slice(0, 120)}`);

        this.simulation.on('tick', () => {
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

        if (this.selectedNodeId) {
            this.selectNode(this.selectedNodeId);
        }
    }

    async runMemoryAction(action, labelKey) {
        if (!this.currentSessionId) return;
        const label = t(labelKey);

        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(
                `${this.apiBaseUrl}/api/memory/${action}/${this.currentSessionId}`,
                { method: 'POST', headers }
            );
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || data.message || `${label} failed`);
            }
            await this.refreshGraph();
        } catch (error) {
            alert(t("memory_action_fail", { label, msg: error.message }));
        }
    }

    openNeo4jBrowser() {
        window.open('http://127.0.0.1:7474', '_blank', 'noopener,noreferrer');
    }

    escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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
        
        this.closeBtn.addEventListener('click', () => this.hide());
        this.modal.addEventListener('click', (event) => {
            if (event.target === this.modal) this.hide();
        });
        
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
        this.resetBtn.addEventListener('click', () => this.loadConfig());
        
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
            
            if (response.ok && (data.status === 'success' || data.success === true)) {
                this.originalConfig = data.config;
                this.populateForm(data.config);
            }
                this.loadingEl.style.display = 'none';
                this.form.style.display = 'block';
            
        } catch (error) {
            this.loadingEl.innerHTML = `<p style="color: #ff4141;">${t("ui_settings_load_fail", { msg: error.message })}</p>`;
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
                        <span class="status-badge">${getCurrentLang() === 'en' ? 'Bound' : '已绑定'}</span>
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
            alert(t("ui_bind_need_id"));
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
        // personal settings
        this.setFieldValue('userAgentName', config.agent_name || '');
        this.setFieldValue('userSystemPrompt', config.system_prompt || '');

        const userApi = (config.user && config.user.api) || {};
        this.setFieldValue('userApiKey', userApi.api_key || '');
        this.setFieldValue('userBaseUrl', userApi.base_url || '');
        this.setFieldValue('userModel', userApi.model || '');
        this.setFieldValue('userTemperature', userApi.temperature || '');
        this.setFieldValue('userMaxTokens', userApi.max_tokens || '');

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
        const config = this.normalizeConfigForGateway(this.buildConfigObject(formData));
        const token = localStorage.getItem('auth_token');
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        };
        
        try {
            const submitBtn = this.form.querySelector('.btn-primary');
            submitBtn.disabled = true;
            submitBtn.textContent = t("ui_save_progress");
            
            const response = await fetch(`${this.apiBaseUrl}/api/config/update`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ config })
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
        this.outputEl.textContent = `${t("ui_status_running_doctor")}\n`;

        try {
            const token = localStorage.getItem('auth_token');
            const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
            const response = await fetch(`${this.apiBaseUrl}/api/doctor`, { headers });
            const data = await response.json();

            const lines = [];
            lines.push(`${getCurrentLang() === 'en' ? 'Status' : '状态'}: ${data.status || 'unknown'}`);
            lines.push(`${getCurrentLang() === 'en' ? 'Time' : '时间'}: ${data.timestamp || ''}`);
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
            this.outputEl.textContent = `${getCurrentLang() === 'en' ? 'Doctor failed' : '自检失败'}: ${error.message}`;
        }
    }

    async migrateConfig() {
        if (!this.outputEl) return;
        this.outputEl.textContent = `${t("ui_status_running_migrate")}\n`;

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
                lines.push(`${getCurrentLang() === 'en' ? 'Status' : '状态'}: success`);
                if (data.message) lines.push(data.message);
                if (data.config_path) lines.push(`${getCurrentLang() === 'en' ? 'Config file' : '配置文件'}: ${data.config_path}`);
                if (data.backup) lines.push(`${getCurrentLang() === 'en' ? 'Backup created' : '已创建备份'}: ${data.backup}`);
            } else {
                lines.push(`${getCurrentLang() === 'en' ? 'Status' : '状态'}: ${data.status || 'error'}`);
                lines.push(`${getCurrentLang() === 'en' ? 'Error' : '错误'}: ${data.message || (getCurrentLang() === 'en' ? 'Migration failed' : '修复失败')}`);
                if (data.config_path) lines.push(`${getCurrentLang() === 'en' ? 'Config file' : '配置文件'}: ${data.config_path}`);
                if (data.backup) lines.push(`${getCurrentLang() === 'en' ? 'Backup' : '备份'}: ${data.backup}`);
            }

            this.outputEl.textContent = lines.join('\n');
        } catch (error) {
            this.outputEl.textContent = `${getCurrentLang() === 'en' ? 'Doctor fix failed' : '自检修复失败'}: ${error.message}`;
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
    const languageManager = new LanguageManager();
    languageManager.init();

    const app = new TerminalChatApp();
    const memoryViz = new MemoryGraphVisualization(app.apiBaseUrl);
    const settingsManager = new SettingsManager(app.apiBaseUrl);
    const metricsManager = new MetricsManager(app.apiBaseUrl);
    const doctorManager = new DoctorManager(app.apiBaseUrl);
    const avatarManager = new AvatarManager();
    
    document.getElementById('memoryGraphBtn').addEventListener('click', (event) => {
        // Default: global user memory. Hold Alt to inspect current session scope.
        if (event.altKey && app.currentSessionId) {
            memoryViz.show(app.currentSessionId);
            return;
        }
        memoryViz.show();
    });
    
    document.getElementById('settingsBtn').addEventListener('click', () => {
        settingsManager.show();
    });
});
