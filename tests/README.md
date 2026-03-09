# Tests

## 中文

### 目标
`tests/` 用于保护核心能力：对话编排、工具调用、Moirai 工作流、记忆系统、配置与策略。

### 分层约定
- 单元测试：纯逻辑与边界行为，无外部依赖。
- 集成测试：跨模块协作（网关、工具服务、策略引擎）。
- Live 测试：依赖运行中的服务或外部组件（通过 `PROMETHEA_LIVE_TEST=1` 启用）。

### 常用命令
```powershell
# 全量（默认不跑 live）
python tests/run_all_tests.py

# 全量 + 覆盖率
python tests/run_all_tests.py --coverage

# 单文件
python tests/run_all_tests.py --file test_moirai_service.py

# 按关键字过滤
python tests/run_all_tests.py --pattern "memory and not live"

# 开启 live 测试
python tests/run_all_tests.py --live
```

### 最小回归集合（推荐）
```powershell
pytest -q tests/test_reasoning_service.py tests/test_moirai_service.py tests/test_memory_regressions.py tests/test_tool_service.py
```

## English

### Purpose
`tests/` protects critical paths: orchestration, tool execution, Moirai workflows, memory behavior, and policy/config logic.

### Test Layers
- Unit: pure logic and boundary behavior.
- Integration: cross-module behavior.
- Live: requires running services or external dependencies (enabled by `PROMETHEA_LIVE_TEST=1`).

### Common Commands
```powershell
python tests/run_all_tests.py
python tests/run_all_tests.py --coverage
python tests/run_all_tests.py --file test_moirai_service.py
python tests/run_all_tests.py --pattern "memory and not live"
python tests/run_all_tests.py --live
```
