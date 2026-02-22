# Config Module

---

## 中文文档

### 1. 配置模型

配置优先级（低 -> 高）：
1. `config/default.json`
2. `config/users/<user_id>/config.json`
3. 环境变量（`.env`）

### 2. 关键目标

- 让默认配置稳定可复用
- 允许用户覆盖非敏感项
- 敏感项（如 API key）由环境变量统一管理

### 3. 关键文件

- `config/default.json`：系统默认配置
- `config/users/<user_id>/config.json`：用户覆盖配置
- `config.py`：配置模型与加载逻辑

### 4. 示例

用户修改 agent 名称：
- 前端调用配置更新接口
- 后端写入 `config/users/<user_id>/config.json`
- 下次加载时自动合并并生效

### 5. 修改注意事项

- 新字段要同步更新：默认值 + schema + 前端表单
- 避免新增“并行写入入口”
- 变更前后都要验证合并优先级是否符合预期

---

## English Documentation

### 1. Config Model

Config precedence (low -> high):
1. `config/default.json`
2. `config/users/<user_id>/config.json`
3. environment variables (`.env`)

### 2. Key Objectives

- stable reusable defaults
- user-level non-secret overrides
- centralized secret management via environment variables

### 3. Key Files

- `config/default.json`: default system config
- `config/users/<user_id>/config.json`: user overrides
- `config.py`: schema + loading logic

### 4. Example

User updates agent name:
- frontend calls config update endpoint
- backend persists to per-user config file
- next load merges and applies automatically

### 5. Change Notes

- keep defaults, schema, and UI fields in sync
- avoid introducing parallel write paths
- verify precedence behavior after each config change
