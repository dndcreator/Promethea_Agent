# Core 模块

Core 模块提供核心插件系统和统一服务接口。

## 架构设计

```
┌─────────────────────────────────────┐
│   Plugin Registry (插件注册表)        │
│  - 插件发现和加载                     │
│  - 服务注册和查找                     │
└─────────────────────────────────────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
Plugin   Service   Runtime
Loader   Registry  Registry
```

## 核心组件

### 1. Plugin System (`plugins/`)

#### Plugin Discovery (`plugins/discovery.py`)
- **职责**: 发现插件
- **功能**:
  - 扫描 `extensions/` 目录
  - 读取插件清单文件

#### Plugin Loader (`plugins/loader.py`)
- **职责**: 加载插件
- **功能**:
  - 加载插件代码
  - 执行插件注册函数

#### Plugin Registry (`plugins/registry.py`)
- **职责**: 插件注册表
- **功能**:
  - 注册和查找插件
  - 服务注册和查找

#### Plugin Runtime (`plugins/runtime.py`)
- **职责**: 运行时注册表
- **功能**:
  - 管理活跃插件
  - 提供运行时服务

### 2. Services (`services.py`)

- **职责**: 统一服务获取接口
- **功能**:
  - 通过插件注册表获取服务
  - 避免直接 import，实现解耦
  - 支持降级处理

## 插件系统

### 插件结构

```
extensions/
└── my-plugin/
    ├── promethea.plugin.json  # 插件清单
    └── plugin.py              # 插件入口
```

### 插件清单格式

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "Plugin description",
  "entry": "plugin.py",
  "services": ["memory", "tool"]
}
```

### 插件入口

```python
def register(api):
    """插件注册函数"""
    # 注册服务
    api.register_service("memory", MyMemoryService())
    
    # 注册工具
    api.register_tool("my_tool", my_tool_function)
    
    # 订阅事件
    api.event_emitter.on(EventType.CHANNEL_MESSAGE, handler)
```

## 使用示例

### 获取服务

```python
from core.services import get_memory_service

memory_service = get_memory_service()
if memory_service:
    # 使用记忆服务
    memory_service.add_message(...)
```

### 注册服务

```python
from core.plugins.registry import register_service

register_service("my_service", MyService())
```

### 查找服务

```python
from core.plugins.registry import find_service

service = find_service("memory")
```

## 插件开发

### 1. 创建插件目录

```bash
mkdir extensions/my-plugin
```

### 2. 创建插件清单

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "entry": "plugin.py"
}
```

### 3. 实现插件入口

```python
# plugin.py
def register(api):
    # 注册服务
    api.register_service("my_service", MyService())
    
    # 注册工具
    api.register_tool("my_tool", my_tool)
```

## 相关文档

- [主 README](../README.md)
- [Gateway 模块](../gateway/README.md)
- [Extensions 目录](../extensions/)
