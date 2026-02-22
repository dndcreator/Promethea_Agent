# Tests Module

---

## 中文文档

### 1. 模块目标

`tests` 用于保护核心路径：对话、记忆、配置、网关协同。

### 2. 常见测试文件

- `test_message_manager_turns.py`：回合写入一致性
- `test_memory_regressions.py`：记忆写入与召回回归
- `test_memory_forgetting_regressions.py`：遗忘机制回归
- `test_config_service.py`：配置服务行为
- `test_conversation_queue.py`：会话队列与并发行为
- `test_gateway_integration_unit.py`：网关集成单元

### 3. 运行方式

```powershell
pip install -e .[dev]
pytest -q tests/
```

### 4. 最小回归集（推荐）

```powershell
pytest -q tests/test_message_manager_turns.py tests/test_memory_regressions.py tests/test_conversation_queue.py
```

### 5. 注意事项

- 涉及 Neo4j 的测试应使用独立测试库
- 修改 recall/forgetting 逻辑后必须跑记忆回归
- 接口返回结构改动后补充 API 兼容测试

---

## English Documentation

### 1. Purpose

`tests` protects critical paths: conversation flow, memory behavior, config logic, and gateway integration.

### 2. Common Test Files

- `test_message_manager_turns.py`: turn consistency
- `test_memory_regressions.py`: memory write/recall regressions
- `test_memory_forgetting_regressions.py`: forgetting regressions
- `test_config_service.py`: config behavior
- `test_conversation_queue.py`: queue/concurrency behavior
- `test_gateway_integration_unit.py`: gateway integration unit tests

### 3. Run

```powershell
pip install -e .[dev]
pytest -q tests/
```

### 4. Recommended Minimal Regression Set

```powershell
pytest -q tests/test_message_manager_turns.py tests/test_memory_regressions.py tests/test_conversation_queue.py
```

### 5. Notes

- use isolated Neo4j DB for graph-related tests
- always run memory regressions after recall/forgetting changes
- add compatibility tests when API response shapes change
