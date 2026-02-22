# Core Module

---

## 中文文档

### 1. 模块职责

`core` 提供插件框架：发现、加载、注册、运行时访问。

### 2. 关键文件

- `core/services.py`：核心服务访问入口
- `core/plugins/discovery.py`：插件发现
- `core/plugins/loader.py`：插件加载
- `core/plugins/manifest.py`：插件元数据
- `core/plugins/registry.py`：能力注册中心
- `core/plugins/runtime.py`：运行态管理
- `core/plugins/types.py`：插件相关类型定义

### 3. 工作流

1. 扫描 `extensions/*`
2. 读取 `promethea.plugin.json`
3. 导入 `plugin.py`
4. 执行注册并挂到 registry

### 4. 示例

新增插件后重启服务，日志出现 `registered channel/service` 即表示接入成功。

### 5. 注意事项

- 插件失败应可隔离，不拖垮主系统
- 注册名必须唯一
- 插件尽量通过接口依赖，避免硬耦合

---

## English Documentation

### 1. Purpose

`core` implements the plugin framework: discovery, loading, registration, and runtime access.

### 2. Key Files

- `core/services.py`: service access entrypoint
- `core/plugins/discovery.py`: plugin discovery
- `core/plugins/loader.py`: plugin loading
- `core/plugins/manifest.py`: plugin metadata model
- `core/plugins/registry.py`: capability registry
- `core/plugins/runtime.py`: runtime management
- `core/plugins/types.py`: plugin-related types

### 3. Workflow

1. Scan `extensions/*`
2. Parse `promethea.plugin.json`
3. Import `plugin.py`
4. Register capabilities into registry

### 4. Example

After adding a plugin, restart the service and verify `registered channel/service` logs.

### 5. Notes

- plugin failures should be isolated
- registration keys must be unique
- prefer interface-based dependency over hard coupling
