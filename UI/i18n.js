const I18N = {
    zh: {},
    en: {
        lang_name: "English",
        auth_login: "Sign In",
        auth_register: "Sign Up",
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
        app_welcome: "Welcome to Promethea AI Assistant!\n\nI can help you with:\n- Q&A\n- Document analysis\n- Coding\n- Creative writing\n\nLet's start.",
        ui_memory_workbench: "Memory Workbench",
        ui_lang_title: "Choose Language",
        ui_lang_desc: "Choose UI language (backend logs stay unchanged).",
        ui_metrics: "Metrics",
        ui_doctor: "System Doctor",
        ui_settings: "Settings",
        ui_memory: "Memory Workbench",
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
        ui_confirm_title: "Sensitive Action Confirmation",
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
        ui_quickask_btn: "Follow-up",
        ui_thinking: "Thinking...",
        ui_thinking_deep: "Deep thinking...",
        ui_thinking_process: "Thinking Process",
        ui_tool_detected: "Tool call detected...",
        ui_followup_title: "Ask about this selection",
        ui_followup_why: "Why",
        ui_followup_risk: "Risks",
        ui_followup_alt: "Alternatives",
        ui_followup_custom: "Or enter a custom follow-up...",
        ui_followup_send: "Send",
        ui_followup_fail: "Follow-up failed, please retry.",
        ui_bind_need_id: "Please enter account ID.",
        ui_bind_success: "Bound successfully!",
        ui_bind_fail: "Bind failed: {msg}",
        ui_save_progress: "Saving...",
        ui_save_success: "Configuration saved and applied!",
        ui_save_fail: "Save failed: {msg}",
        ui_save_btn: "Save & Apply",
        ui_settings_loading: "Loading configuration...",
        ui_settings_load_fail: "Load failed: {msg}",
        ui_settings_reset: "Reset",
        ui_rejected: "Action rejected.",
        ui_tool_running: "Tool call: {name} (running)",
        ui_tool_done: "Tool call: {name} (done)",
        ui_tool_failed: "Tool call failed",
        ui_error_unknown: "Unknown error",
        ui_switch_session_fail: "Switch session failed: {msg}",
        ui_settings_personal: "Personalization",
        ui_settings_personal_api: "Personal API Config (Optional)",
        ui_settings_personal_api_hint: "Values here override system defaults. Leave empty to use defaults.",
        ui_settings_bind: "Social Account Binding",
        ui_settings_sys_api: "API Config",
        ui_settings_sys: "System Config",
        ui_settings_memory: "Memory System",
        ui_settings_soul: "Soul Prompt (Read-only)",
        ui_settings_soul_hint: "Auto-evolved by the agent. This field is view-only.",
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
    lang_name: "简体中文",
    auth_login: "登录",
    auth_register: "注册",
    auth_submit_login: "登录",
    auth_submit_register: "注册并创建 Agent",
    auth_switch_to_register: "去注册",
    auth_switch_to_login: "去登录",
    auth_no_account: "还没有账号？",
    auth_has_account: "已有账号？",
    auth_register_success: "注册成功，请登录",
    auth_welcome_back: "欢迎回来，{agent} 已就绪",
    auth_failed: "操作失败",
    auth_invalid: "认证失效，请重新登录",
    logout_confirm: "确定要退出登录吗？",
    chat_placeholder: "输入你的问题...",
    memory_loading: "正在加载记忆图...",
    memory_disabled: "记忆系统未启用或不可用",
    memory_fail: "加载失败: {msg}",
    memory_no_data: "当前筛选条件无数据",
    memory_no_nodes: "暂无可显示的记忆节点",
    memory_select_detail: "选择左侧节点查看详情",
    memory_action_fail: "{label}失败: {msg}",
    app_welcome: "欢迎使用 Promethea AI Assistant。\n\n我可以帮助你：\n- 问答\n- 文档分析\n- 编写代码\n- 创意写作\n\n开始对话吧。",
    ui_lang_title: "选择语言 / Choose Language",
    ui_lang_desc: "选择界面语言（不影响后端日志）。",
    ui_metrics: "统计",
    ui_doctor: "系统自检",
    ui_settings: "设置",
    ui_memory: "记忆工作台",
    ui_memory_cluster: "聚类",
    ui_memory_summary: "摘要",
    ui_memory_decay: "衰减",
    ui_memory_cleanup: "清理",
    ui_memory_refresh: "刷新",
    ui_memory_node_list: "节点列表",
    ui_memory_node_detail: "节点详情",
    ui_memory_filter_all_layers: "全部层级",
    ui_memory_filter_all_types: "全部类型",
    ui_memory_search_placeholder: "搜索内容 / 节点ID / 类型...",
    ui_memory_total_nodes: "节点总数",
    ui_memory_total_edges: "关系总数",
    ui_memory_hot: "热层",
    ui_memory_warm: "温层",
    ui_memory_cold: "冷层",
    ui_memory_detail_id: "ID",
    ui_memory_detail_type: "类型",
    ui_memory_detail_layer: "层级",
    ui_memory_detail_importance: "重要度",
    ui_memory_detail_access: "访问次数",
    ui_memory_detail_edges: "关联边",
    ui_sessions: "会话",
    ui_chat_tab: "对话",
    ui_current_session: "当前会话",
    ui_not_started: "未开始",
    ui_auth_username: "用户名",
    ui_auth_password: "密码",
    ui_auth_agent_name: "Agent 名称",
    ui_auth_username_placeholder: "请输入用户名",
    ui_auth_password_placeholder: "请输入密码",
    ui_auth_agent_placeholder: "给你的助手起个名字（默认：Promethea）",
    ui_app_title: "Promethea AI Assistant - Terminal",
    ui_logo_text: "Promethea",
    ui_new_chat_title: "新建会话",
    ui_avatar_hint: "点击上传头像",
    ui_avatar_remove_title: "移除头像",
    ui_api_status_title: "API 连接状态",
    ui_memory_status_title: "记忆系统状态",
    ui_logout_title: "退出登录",
    ui_doctor_title: "系统自检",
    ui_metrics_title: "统计",
    ui_settings_title: "设置",
    ui_memory_graph_title: "查看记忆图",
    ui_confirm_title: "敏感操作确认",
    ui_confirm_desc: "Agent 请求执行以下高风险操作：",
    ui_confirm_tool: "工具：",
    ui_confirm_args: "参数：",
    ui_confirm_reject: "拒绝",
    ui_confirm_approve: "批准",
    ui_metrics_token: "Token 使用量",
    ui_metrics_cost: "预估成本",
    ui_metrics_llm: "LLM 调用",
    ui_metrics_avg: "平均",
    ui_metrics_memory: "记忆召回",
    ui_metrics_session_message: "会话/消息",
    ui_metrics_uptime: "运行时长",
    ui_doctor_run: "重新运行",
    ui_doctor_fix: "修复/迁移配置",
    ui_quickask_btn: "追问",
    ui_thinking: "思考中...",
    ui_thinking_process: "思考过程",
    ui_tool_detected: "检测到工具调用...",
    ui_followup_title: "针对选中文本追问",
    ui_followup_why: "为什么",
    ui_followup_risk: "风险",
    ui_followup_alt: "替代方案",
    ui_followup_custom: "或输入自定义追问...",
    ui_followup_send: "发送",
    ui_followup_fail: "追问失败，请重试",
    ui_bind_need_id: "请输入账号 ID",
    ui_bind_success: "绑定成功",
    ui_bind_fail: "绑定失败: {msg}",
    ui_save_progress: "保存中...",
    ui_save_success: "配置已保存并生效",
    ui_save_fail: "保存失败: {msg}",
    ui_save_btn: "保存并应用",
    ui_settings_loading: "正在加载配置...",
    ui_settings_load_fail: "加载失败: {msg}",
    ui_settings_reset: "重置",
    ui_rejected: "操作已拒绝",
    ui_tool_running: "工具调用：{name}（执行中）",
    ui_tool_done: "工具调用：{name}（已完成）",
    ui_tool_failed: "工具调用失败",
    ui_error_unknown: "未知错误",
    ui_switch_session_fail: "切换会话失败: {msg}",
    ui_settings_personal: "个性化",
    ui_settings_personal_api: "个人 API 配置（可选）",
    ui_settings_personal_api_hint: "这里的配置会覆盖系统默认值；留空则使用默认。",
    ui_settings_bind: "社交账号绑定",
    ui_settings_sys_api: "系统 API 配置",
    ui_settings_sys: "系统配置",
    ui_settings_memory: "记忆系统",
    ui_settings_soul: "灵魂 Prompt（只读）",
    ui_settings_soul_hint: "该内容由 Agent 自动演化，前端仅展示。",
    ui_label_user_agent: "Agent 名称",
    ui_label_user_prompt: "自定义 System Prompt",
    ui_placeholder_user_prompt: "自定义你的助手人设...",
    ui_label_user_model: "模型",
    ui_label_bind_account: "输入账号 ID（如 Telegram User ID）",
    ui_bind_btn: "绑定",
    ui_label_model: "模型",
    ui_label_history_rounds: "历史轮数",
    ui_label_stream_mode: "流式输出",
    ui_label_debug_mode: "调试模式",
    ui_label_log_level: "日志级别",
    ui_label_memory_enabled: "启用记忆系统",
    ui_label_neo4j_enabled: "启用 Neo4j",
    ui_label_neo4j_user: "用户名",
    ui_label_neo4j_db: "数据库",
    ui_label_warm_enabled: "启用温层",
    ui_label_cluster_threshold: "聚类阈值",
    ui_label_min_cluster: "最小簇大小",
    ui_label_summary_len: "摘要长度",
    ui_label_compress_threshold: "压缩阈值",
    ui_status_running_doctor: "正在运行系统自检，请稍候...",
    ui_status_running_migrate: "正在修复/迁移配置，请稍候...",
    ui_memory_btn_short: "记忆",
    ui_api_short: "API",
    ui_memory_short: "记忆",
    ui_delete_user: "注销",
    memory_sync_idle: "记忆同步空闲",
    memory_sync_running: "记忆同步中：{pending}",
    memory_sync_error: "记忆同步异常",
    memory_sync_wait_close: "记忆同步尚未完成，请稍后再关闭页面。",
    ui_tools_live: "工具",
    ui_tools_loading: "正在加载工具...",
    ui_tools_empty: "暂无可用工具",
    ui_tools_error: "工具列表加载失败",
    ui_tools_more: "还有 {count} 个工具",
    ui_session_search_placeholder: "搜索会话...",
    ui_tool_filter_placeholder: "筛选工具...",
    ui_tool_types_summary: "类型：{summary}",
    ui_pin: "置顶",
    ui_unpin: "取消置顶",
    ui_metrics_pinned_files: "置顶: <span id=\"pinnedSessions\">0</span> · 文件: <span id=\"filesCount\">0</span>",
    ui_settings_basic: "快速设置",
    ui_settings_basic_hint: "这里只显示最关键配置；展开高级设置可查看全部选项。",
    ui_settings_advanced: "高级设置",
    ui_settings_hot_apply: "立即生效（热重载）",
    ui_label_api_key: "API 密钥",
    ui_label_base_url: "Base URL",
    ui_label_memory_backend: "记忆后端",
    ui_memory_backend_neo4j: "Neo4j（图数据库）",
    ui_memory_backend_sqlite_graph: "SQLite Graph（轻量）",
    ui_memory_backend_flat: "Flat Memory（兜底）",
    ui_showcase: "展示",
    ui_showcase_title: "开源展示",
    ui_showcase_intro: "用于路演、上手与发布公告的产品演示场景。",
    ui_showcase_card1_title: "运行健康演示",
    ui_showcase_card1_desc: "一次性展示网关、记忆、工具与策略状态。",
    ui_showcase_card2_title: "推理可视化闭环",
    ui_showcase_card2_desc: "展示 ToT/ReAct 过程可见，以及纠偏与中止控制。",
    ui_showcase_card3_title: "记忆与工作流可信性",
    ui_showcase_card3_desc: "展示召回轨迹、写入决策与可恢复工作流。",
    ui_showcase_copy: "复制演示命令",
    ui_showcase_launch_doc: "发布文档",
    ui_reasoning_title: "推理可视化",
    ui_reasoning_steer_placeholder: "输入纠偏提示...",
    ui_reasoning_steer: "纠偏",
    ui_reasoning_stop: "中止",
    ui_memory_view_network: "图谱",
    ui_memory_view_mindmap: "导图",
    ui_memory_importance_filter: "最小重要度",
    ui_memory_hide_weak: "隐藏弱信号",
    ui_settings_personal_ops: "个人工作台运维",
    ui_settings_personal_ops_hint: "在这里管理模板生态、统一导入导出与工作流恢复。",
    ui_personal_template_label: "模板",
    ui_personal_template_empty: "（先加载模板）",
    ui_personal_template_start: "适用时自动启动工作流",
    ui_personal_templates_load: "加载模板",
    ui_personal_template_apply: "应用模板",
    ui_personal_import_file: "导入 Bundle 文件",
    ui_personal_import_merge: "合并模式（跳过已存在）",
    ui_personal_export: "导出 Bundle",
    ui_personal_import: "导入 Bundle",
    ui_personal_recovery: "工作流恢复",
    ui_personal_choose_template: "请先选择模板。",
    ui_personal_choose_bundle: "请先选择 Bundle 文件。",
    ui_personal_action_resume: "继续运行",
    ui_personal_action_retry: "重试当前步骤",
    ui_personal_recovery_actions: "可恢复运行：",
    ui_personal_recovery_empty: "当前没有可恢复的工作流运行。",
    ui_personal_recovery_resume_done: "已触发继续运行：{run_id}",
    ui_personal_recovery_retry_done: "已触发重试：{run_id} / {step_id}",
});

Object.assign(I18N.en, {
    auth_login: "Sign In",
    auth_register: "Sign Up",
    app_welcome: "Welcome to Promethea AI Assistant!\n\nI can help you with:\n- Q&A\n- Document analysis\n- Coding\n- Creative writing\n\nLet's start.",
    ui_memory_workbench: "Memory Workbench",
    ui_lang_title: "Choose Language / 选择语言",
    ui_metrics: "Metrics",
    ui_doctor: "System Doctor",
    ui_settings: "Settings",
    ui_memory: "Memory Workbench",
    ui_confirm_title: "Sensitive Action Confirmation",
    ui_quickask_btn: "Follow-up",
    ui_thinking_deep: "Deep thinking...",
    ui_thinking_process: "Thinking Process",
    ui_followup_title: "Ask about this selection",
    ui_followup_why: "Why",
    ui_followup_risk: "Risks",
    ui_followup_alt: "Alternatives",
    ui_bind_success: "Bound successfully!",
    ui_bind_fail: "Bind failed: {msg}",
    ui_save_success: "Configuration saved and applied!",
    ui_save_fail: "Save failed: {msg}",
    ui_rejected: "Action rejected.",
    ui_tool_running: "Tool call: {name} (running)",
    ui_tool_done: "Tool call: {name} (done)",
    ui_settings_personal: "Personalization",
    ui_settings_personal_api: "Personal API Config (Optional)",
    ui_settings_bind: "Social Account Binding",
    ui_settings_sys_api: "API Config",
    ui_settings_sys: "System Config",
    ui_settings_memory: "Memory System",
    ui_tools_live: "Tools",
    ui_tools_loading: "Loading tools...",
    ui_tools_empty: "No tools available",
    ui_tools_error: "Failed to load tools",
    ui_tools_more: "{count} more tools",
    ui_session_search_placeholder: "Search sessions...",
    ui_tool_filter_placeholder: "Filter tools...",
    ui_tool_types_summary: "Types: {summary}",
    ui_pin: "Pin",
    ui_unpin: "Unpin",
    ui_metrics_pinned_files: "Pinned: <span id=\"pinnedSessions\">0</span> · Files: <span id=\"filesCount\">0</span>",
    ui_settings_basic: "Quick Setup",
    ui_settings_basic_hint: "Only the most important fields are shown here. Open advanced settings for full control.",
    ui_settings_advanced: "Advanced Settings",
    ui_settings_hot_apply: "Apply immediately (hot reload)",
    ui_label_api_key: "API Key",
    ui_label_base_url: "Base URL",
    ui_label_memory_backend: "Memory Backend",
    ui_memory_backend_neo4j: "Neo4j (Graph)",
    ui_memory_backend_sqlite_graph: "SQLite Graph (Lightweight)",
    ui_memory_backend_flat: "Flat Memory (Fallback)",
    ui_showcase: "Showcase",
    ui_showcase_title: "Open Source Showcase",
    ui_showcase_intro: "Product release scenarios for demos, onboarding, and launch announcements.",
    ui_showcase_card1_title: "Runtime Health Demo",
    ui_showcase_card1_desc: "Show gateway, memory, tools, and policy status in one pass.",
    ui_showcase_card2_title: "Reasoning Visual Loop",
    ui_showcase_card2_desc: "Demonstrate ToT/ReAct visibility, steer, and stop controls.",
    ui_showcase_card3_title: "Memory + Workflow Trust",
    ui_showcase_card3_desc: "Show recall traces, write decisions, and resumable workflow.",
    ui_showcase_copy: "Copy Demo Commands",
    ui_showcase_launch_doc: "Launch Doc",
    ui_reasoning_title: "Reasoning",
    ui_reasoning_steer_placeholder: "Enter steering note...",
    ui_reasoning_steer: "Steer",
    ui_reasoning_stop: "Stop",
    ui_memory_view_network: "Graph",
    ui_memory_view_mindmap: "Mind Map",
    ui_memory_importance_filter: "Min Importance",
    ui_memory_hide_weak: "Hide weak signals",
    ui_settings_personal_ops: "Personal Workspace Ops",
    ui_settings_personal_ops_hint: "Manage template ecosystem, unified import/export, and workflow recovery here.",
    ui_personal_template_label: "Template",
    ui_personal_template_empty: "(load templates first)",
    ui_personal_template_start: "Start workflow when applicable",
    ui_personal_templates_load: "Load Templates",
    ui_personal_template_apply: "Apply Template",
    ui_personal_import_file: "Import Bundle File",
    ui_personal_import_merge: "Merge mode (skip existing)",
    ui_personal_export: "Export Bundle",
    ui_personal_import: "Import Bundle",
    ui_personal_recovery: "Workflow Recovery",
    ui_personal_choose_template: "Please choose a template first.",
    ui_personal_choose_bundle: "Please choose a bundle file first.",
    ui_personal_action_resume: "Resume",
    ui_personal_action_retry: "Retry Step",
    ui_personal_recovery_actions: "Recoverable runs:",
    ui_personal_recovery_empty: "No recoverable workflow runs.",
    ui_personal_recovery_resume_done: "Resume requested: {run_id}",
    ui_personal_recovery_retry_done: "Retry requested: {run_id} / {step_id}",
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
        const showcaseBtn = document.getElementById("showcaseBtn");
        if (showcaseBtn) showcaseBtn.title = t("ui_showcase");
        const metricsBtn = document.getElementById("metricsBtn");
        if (metricsBtn) metricsBtn.title = t("ui_metrics_title");
        const settingsBtn = document.getElementById("settingsBtn");
        if (settingsBtn) settingsBtn.title = t("ui_settings_title");
        const memoryGraphBtn = document.getElementById("memoryGraphBtn");
        if (memoryGraphBtn) memoryGraphBtn.title = t("ui_memory_graph_title");
        if (doctorBtn) doctorBtn.textContent = t("ui_doctor");
        if (showcaseBtn) showcaseBtn.textContent = t("ui_showcase");
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
        const reasoningTitle = document.getElementById("reasoningPanelTitle");
        if (reasoningTitle) reasoningTitle.textContent = t("ui_reasoning_title");
        const reasoningSteerInput = document.getElementById("reasoningSteerInput");
        if (reasoningSteerInput) reasoningSteerInput.placeholder = t("ui_reasoning_steer_placeholder");
        const reasoningSteerBtn = document.getElementById("reasoningSteerBtn");
        if (reasoningSteerBtn) reasoningSteerBtn.textContent = t("ui_reasoning_steer");
        const reasoningStopBtn = document.getElementById("reasoningStopBtn");
        if (reasoningStopBtn) reasoningStopBtn.textContent = t("ui_reasoning_stop");

        const metricsTitle = document.querySelector("#metricsModal .modal-header h2");
        if (metricsTitle) metricsTitle.textContent = t("ui_metrics");
        const doctorTitle = document.querySelector("#doctorModal .modal-header h2");
        if (doctorTitle) doctorTitle.textContent = t("ui_doctor");
        const settingsTitle = document.querySelector("#settingsModal .modal-header h2");
        if (settingsTitle) settingsTitle.textContent = t("ui_settings");
        const memoryTitle = document.querySelector("#memoryGraphModal .modal-header h2");
        if (memoryTitle) memoryTitle.textContent = t("ui_memory");
        const showcaseTitle = document.getElementById("showcaseTitle");
        if (showcaseTitle) showcaseTitle.textContent = t("ui_showcase_title");
        const showcaseIntro = document.getElementById("showcaseIntro");
        if (showcaseIntro) showcaseIntro.textContent = t("ui_showcase_intro");
        const showcaseCard1Title = document.getElementById("showcaseCard1Title");
        if (showcaseCard1Title) showcaseCard1Title.textContent = t("ui_showcase_card1_title");
        const showcaseCard1Desc = document.getElementById("showcaseCard1Desc");
        if (showcaseCard1Desc) showcaseCard1Desc.textContent = t("ui_showcase_card1_desc");
        const showcaseCard2Title = document.getElementById("showcaseCard2Title");
        if (showcaseCard2Title) showcaseCard2Title.textContent = t("ui_showcase_card2_title");
        const showcaseCard2Desc = document.getElementById("showcaseCard2Desc");
        if (showcaseCard2Desc) showcaseCard2Desc.textContent = t("ui_showcase_card2_desc");
        const showcaseCard3Title = document.getElementById("showcaseCard3Title");
        if (showcaseCard3Title) showcaseCard3Title.textContent = t("ui_showcase_card3_title");
        const showcaseCard3Desc = document.getElementById("showcaseCard3Desc");
        if (showcaseCard3Desc) showcaseCard3Desc.textContent = t("ui_showcase_card3_desc");
        const showcaseCopyBtn = document.getElementById("showcaseCopyBtn");
        if (showcaseCopyBtn) showcaseCopyBtn.textContent = t("ui_showcase_copy");
        const showcaseLaunchDocLink = document.getElementById("showcaseLaunchDocLink");
        if (showcaseLaunchDocLink) showcaseLaunchDocLink.textContent = t("ui_showcase_launch_doc");

        const memorySearchInput = document.getElementById("memorySearchInput");
        if (memorySearchInput) memorySearchInput.placeholder = t("ui_memory_search_placeholder");
        const sessionSearchInput = document.getElementById("sessionSearchInput");
        if (sessionSearchInput) sessionSearchInput.placeholder = t("ui_session_search_placeholder");
        const toolsFilterInput = document.getElementById("toolsFilterInput");
        if (toolsFilterInput) toolsFilterInput.placeholder = t("ui_tool_filter_placeholder");
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
        if (
            currentSessionValue
            && (
                (currentSessionValue.textContent || '').trim() === ''
                || currentSessionValue.textContent === "Not Started"
                || currentSessionValue.textContent === "未开始"
            )
        ) {
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
        if (metricSubs[4]) metricSubs[4].innerHTML = t("ui_metrics_pinned_files");

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

        const setTextById = (id, key) => {
            const el = document.getElementById(id);
            if (el) el.textContent = t(key);
        };
        setTextById("settingsSectionBasicTitle", "ui_settings_basic");
        setTextById("settingsBasicHint", "ui_settings_basic_hint");
        setTextById("settingsAdvancedSummary", "ui_settings_advanced");
        setTextById("settingsSectionPersonalTitle", "ui_settings_personal");
        setTextById("settingsSectionPersonalApiTitle", "ui_settings_personal_api");
        setTextById("settingsSectionPersonalOpsTitle", "ui_settings_personal_ops");
        setTextById("settingsPersonalOpsHint", "ui_settings_personal_ops_hint");
        setTextById("settingsSectionBindTitle", "ui_settings_bind");
        setTextById("settingsSectionSysApiTitle", "ui_settings_sys_api");
        setTextById("settingsSectionSystemTitle", "ui_settings_sys");
        setTextById("settingsSectionMemoryTitle", "ui_settings_memory");
        setTextById("settingsPersonalApiHint", "ui_settings_personal_api_hint");
        setTextById("labelHotApply", "ui_settings_hot_apply");
        setTextById("labelSoulPrompt", "ui_settings_soul");
        setTextById("soulPromptHint", "ui_settings_soul_hint");
        setTextById("labelBaseUrl", "ui_label_base_url");
        setTextById("labelMemoryStoreBackend", "ui_label_memory_backend");

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
        setLabel('#labelPersonalTemplateSelect', 'ui_personal_template_label');
        setLabel('#labelPersonalImportFile', 'ui_personal_import_file');

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
        const personalTemplateStartSpan = document.getElementById('labelPersonalTemplateStartWorkflow');
        if (personalTemplateStartSpan) personalTemplateStartSpan.textContent = t("ui_personal_template_start");
        const personalImportMergeSpan = document.getElementById('labelPersonalImportMerge');
        if (personalImportMergeSpan) personalImportMergeSpan.textContent = t("ui_personal_import_merge");
        const bindBtn = document.getElementById('bindBtn');
        if (bindBtn) bindBtn.textContent = t("ui_bind_btn");
        const personalTemplateRefreshBtn = document.getElementById('personalTemplateRefreshBtn');
        if (personalTemplateRefreshBtn) personalTemplateRefreshBtn.textContent = t("ui_personal_templates_load");
        const personalTemplateApplyBtn = document.getElementById('personalTemplateApplyBtn');
        if (personalTemplateApplyBtn) personalTemplateApplyBtn.textContent = t("ui_personal_template_apply");
        const personalExportBtn = document.getElementById('personalExportBtn');
        if (personalExportBtn) personalExportBtn.textContent = t("ui_personal_export");
        const personalImportBtn = document.getElementById('personalImportBtn');
        if (personalImportBtn) personalImportBtn.textContent = t("ui_personal_import");
        const personalRecoveryBtn = document.getElementById('personalRecoveryBtn');
        if (personalRecoveryBtn) personalRecoveryBtn.textContent = t("ui_personal_recovery");
        const bindInput = document.getElementById('bindAccountId');
        if (bindInput) bindInput.placeholder = t("ui_label_bind_account");
        const userPrompt = document.getElementById('userSystemPrompt');
        if (userPrompt) userPrompt.placeholder = t("ui_placeholder_user_prompt");
        const personalTemplateSelect = document.getElementById('personalTemplateSelect');
        if (personalTemplateSelect && personalTemplateSelect.options?.length > 0 && !personalTemplateSelect.value) {
            personalTemplateSelect.options[0].text = t("ui_personal_template_empty");
        }
        const memoryBackend = document.getElementById("memoryStoreBackend");
        if (memoryBackend?.options?.length >= 3) {
            memoryBackend.options[0].text = t("ui_memory_backend_neo4j");
            memoryBackend.options[1].text = t("ui_memory_backend_sqlite_graph");
            memoryBackend.options[2].text = t("ui_memory_backend_flat");
        }
        const memoryViewMode = document.getElementById("memoryViewMode");
        if (memoryViewMode?.options?.length >= 2) {
            memoryViewMode.options[0].text = t("ui_memory_view_network");
            memoryViewMode.options[1].text = t("ui_memory_view_mindmap");
        }
        const memoryImportanceLabel = document.getElementById("memoryImportanceLabel");
        if (memoryImportanceLabel) memoryImportanceLabel.textContent = t("ui_memory_importance_filter");
        const memoryHideWeakLabel = document.getElementById("memoryHideWeakLabel");
        if (memoryHideWeakLabel) memoryHideWeakLabel.textContent = t("ui_memory_hide_weak");

        window.dispatchEvent(new CustomEvent("ui-language-changed", { detail: { lang: getCurrentLang() } }));
    }
}
