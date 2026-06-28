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

# 分层套件（推荐先跑 business）
python tests/run_all_tests.py --suite smoke
python tests/run_all_tests.py --suite core
python tests/run_all_tests.py --suite contracts
python tests/run_all_tests.py --suite business
python tests/run_all_tests.py --suite business_plus
python tests/run_all_tests.py --suite full

# 全量 + 覆盖率
python tests/run_all_tests.py --coverage

# 单文件
python tests/run_all_tests.py --file test_moirai_service.py

# 按关键字过滤
python tests/run_all_tests.py --pattern "memory and not live"

# 开启 live 测试
python tests/run_all_tests.py --live

# 开启压力测试（默认关闭）
$env:RUN_STRESS_TESTS="1"
pytest -q -m stress tests/test_memory_stress.py

# 发布前业务回归（自动找解释器并写日志）
powershell -ExecutionPolicy Bypass -File scripts/run_business_audit.ps1 -Suite business
```

### 最小回归集合（推荐）
```powershell
pytest -q tests/test_reasoning_service.py tests/test_moirai_service.py tests/test_memory_regressions.py tests/test_tool_service.py
```

### 临时文件策略
- 测试临时文件统一写入 `.tmp/pytest-runtime/`。
- `tests/conftest.py` 会把 `TEMP`、`TMP`、`TMPDIR`、`PYTEST_DEBUG_TEMPROOT` 和 `PROMETHEA_TEST_TMP_ROOT` 指向该目录。
- 测试正常结束时会清理 `.tmp/pytest-runtime/`。
- 如果测试被中断，最多残留 `.tmp/pytest-runtime/` 一个目录；不应再在仓库根目录生成新的 `.pytest-*`、`tmp_*`、`_pytest_case_tmp` 或 `_pytest_session_tmp` 目录。
- 清理逻辑只允许删除当前仓库内计算出的 `.tmp/pytest-runtime/`，不清理用户数据、上传文件、`config/users/`、`memory/` 或 `logs/`。

### 场景增强测试组织
- `tests/business_plus/`: 贴近业务链路的轻量真实场景测试（chat/tool/workflow 组合流程）。
- `tests/business_plus/README.md`: `business_plus` 用例边界、命名约定与新增标准。

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
$env:RUN_STRESS_TESTS="1"; pytest -q -m stress tests/test_memory_stress.py
```

### Temporary Files
- Test artifacts should live under `.tmp/pytest-runtime/`.
- Normal pytest completion removes `.tmp/pytest-runtime/`.
- Interrupted runs may leave that single directory behind.
- Test cleanup is intentionally narrow and must not delete runtime user data such as `config/users/`, `memory/`, or `logs/`.
