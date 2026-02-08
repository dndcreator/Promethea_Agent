# 测试系统

简洁易用的测试框架，支持单元测试和集成测试。

## 快速开始

### 运行所有测试

```bash
# 运行所有单元测试（默认）
python tests/run_all_tests.py

# 或使用 pytest（如果已安装）
pytest tests/
```

### 运行特定测试

```bash
# 运行单个测试文件
python -m pytest tests/test_gateway_basic.py

# 运行特定测试类
python -m pytest tests/test_gateway_basic.py::TestGatewayBasic

# 运行特定测试方法
python -m pytest tests/test_gateway_basic.py::TestGatewayBasic::test_connect
```

### 运行集成测试

```bash
# 需要设置环境变量（需要运行服务器和 Neo4j）
set PROMETHEA_LIVE_TEST=1
python tests/run_all_tests.py
```

## 测试结构

```
tests/
├── __init__.py              # 测试包初始化
├── conftest.py              # pytest 配置和共享 fixtures
├── test_utils.py            # 测试工具函数
├── run_all_tests.py         # 测试运行器
├── README.md                # 测试文档
├── test_config_service.py   # ConfigService 测试
├── test_tool_service.py     # ToolService 测试
├── test_computer.py         # 电脑控制测试（合并版）
├── test_gateway_basic.py    # Gateway 基础测试（集成测试）
├── test_gateway_integration_unit.py  # Gateway 集成单元测试
├── test_memory_system.py    # 记忆系统测试（集成测试）
├── test_plugins_loader.py   # 插件加载测试
├── test_tool_execution.py   # 工具执行测试
├── test_agent_integration.py  # Agent 集成测试（集成测试）
└── test_api_compatibility.py  # API 兼容性测试（集成测试）
```

## 测试工具

### Fixtures (conftest.py)

- `project_root_path` - 项目根目录路径
- `test_config` - 测试配置
- `mock_event_emitter` - 模拟事件发射器
- `mock_connection_manager` - 模拟连接管理器
- `mock_memory_adapter` - 模拟记忆适配器
- `mock_message_manager` - 模拟消息管理器

### 工具函数 (test_utils.py)

- `create_test_request()` - 创建测试请求
- `create_test_response()` - 创建测试响应
- `create_test_event()` - 创建测试事件
- `mock_websocket_connection()` - 创建模拟 WebSocket
- `assert_response_ok()` - 断言响应成功
- `assert_response_error()` - 断言响应失败

## 编写测试

### 单元测试示例

```python
import pytest
from tests.test_utils import create_test_request, assert_response_ok
from gateway.server import GatewayServer

class TestGatewayServer:
    def test_handle_request(self, mock_event_emitter):
        server = GatewayServer(event_emitter=mock_event_emitter)
        request = create_test_request("health")
        # ... 测试逻辑
```

### 集成测试示例

```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_gateway_connection():
    # 需要运行服务器
    # 测试逻辑
    pass
```

## 测试标记

- `@pytest.mark.asyncio` - 异步测试
- `@pytest.mark.live` - 集成测试（需要运行服务器）
- `@pytest.mark.skip` - 跳过测试

## 最佳实践

1. **单元测试优先**: 大部分测试应该是单元测试，不需要外部依赖
2. **使用 Mock**: 使用 fixtures 和工具函数创建模拟对象
3. **测试隔离**: 每个测试应该独立，不依赖其他测试
4. **清晰命名**: 测试方法名应该描述测试内容
5. **简洁断言**: 使用工具函数简化断言

## 相关文档

- [主 README](../README.md)
- [Gateway 模块](../gateway/README.md)
- [Memory 模块](../memory/README.md)
