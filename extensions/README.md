# Extensions Module

---

## 中文文档

### 1. 模块职责

`extensions` 存放可插拔插件实现。每个插件通常包含：
- 一个 manifest（声明插件元数据）
- 一个入口脚本（注册能力）

### 2. 目录结构约定

```text
extensions/<plugin_name>/
├─ promethea.plugin.json
└─ plugin.py
```

内置示例：`web`、`memory`、`wecom`、`feishu`、`dingtalk`。

### 3. 工作流

1. 系统启动时扫描 `extensions/*`
2. 读取插件 manifest
3. 导入并执行 `plugin.py` 的注册逻辑
4. 注册到 core registry，供 gateway 使用

### 4. 示例：新增插件

1. 新建 `extensions/my_plugin/`
2. 写 `promethea.plugin.json`
3. 在 `plugin.py` 暴露注册入口
4. 启动后检查日志里是否出现注册成功信息

### 5. 注意事项

- manifest 的 id/version/entry 信息要准确
- 插件初始化异常要自恢复，不影响主服务
- 插件能力应通过接口暴露，避免直接耦合内部细节

---

## English Documentation

### 1. Purpose

`extensions` contains pluggable implementation modules. Each plugin typically includes:
- a manifest for metadata
- an entry script for capability registration

### 2. Expected Layout

```text
extensions/<plugin_name>/
├─ promethea.plugin.json
└─ plugin.py
```

Built-in examples: `web`, `memory`, `wecom`, `feishu`, `dingtalk`.

### 3. Workflow

1. startup scans `extensions/*`
2. manifest is parsed
3. plugin entry is imported and executed
4. capabilities are registered into core registry

### 4. Example: Add a Plugin

1. create `extensions/my_plugin/`
2. add `promethea.plugin.json`
3. expose registration entry in `plugin.py`
4. verify registration logs after startup

### 5. Notes

- keep manifest metadata accurate
- plugin init errors must not crash core service
- expose plugin capability via interfaces, not internal hard coupling
