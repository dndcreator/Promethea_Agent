# Core 模块使用说明

`core` 提供插件注册与运行时服务发现能力。

## 主要职责

- 插件发现与加载
- 运行时服务注册表
- 统一服务获取接口

## 目录

```text
core/
├─ plugins/
│  ├─ discovery.py
│  ├─ loader.py
│  ├─ registry.py
│  └─ runtime.py
└─ services.py
```

## 插件基本结构

```text
extensions/<plugin-id>/
├─ promethea.plugin.json
└─ plugin.py
```

## 插件入口约定

`plugin.py` 需要提供 `register(api)`：

- 注册服务
- 注册工具
- 可订阅事件

## 典型用法

### 获取核心服务

```python
from core.services import get_memory_service

memory_service = get_memory_service()
```

### 新增插件能力

1. 在 `extensions/` 下建插件目录
2. 写 `promethea.plugin.json`
3. 实现 `register(api)`
4. 重启服务

## 设计建议

- 插件尽量无状态或状态可恢复
- 服务注册要有唯一名称
- 避免在插件里直接硬编码全局配置路径
