# Tests And Evaluations

测试保护 Runtime 的事实、权限、状态与恢复；评测单独衡量模型行为。
完整分层、模型预算、Judge 校准和人工验收见
[Testing Strategy](../docs/testing-strategy.md)，审计依据与覆盖矩阵见
[Testing Audit](../docs/testing-audit.md)。

## 常用命令

在项目虚拟环境中，从仓库根目录执行：

```powershell
# 默认只跑低成本单元层
python tests/run_all_tests.py
python tests/run_all_tests.py --suite critical --repeat 3 --timeout 300
python tests/run_all_tests.py --suite integration
python tests/run_all_tests.py --suite system
python tests/run_all_tests.py --suite full --coverage

# 显式单文件，不受默认 unit 标记过滤
python -m pytest -q tests/test_memory_regressions.py

# 只验证评测资产；不调用模型
python scripts/run_evaluations.py --mode validate

# 实际 SQLite 召回，每例三次；此组不调用模型
python scripts/run_evaluations.py --mode live --group retrieval --repeat 3
```

`unit/integration/system/browser` 是层；`critical/contracts/smoke/core/business`
是风险筛选集合，不应顺序全跑后再跑 full。混合测试文件保守归入集成层，
并未为了目录整齐移动全部旧测试。注册表在 `evaluation/suites.json`。

## 目录职责

- `test_*.py`：保留的确定性、契约和模块测试。
- `integration/`：真实服务组合，模型边界使用脚本输出。
- `system/`：真实 HTTP、认证、文件产物和隔离子进程重启。
- `live/`：显式开启的只读部署检查，不是全产品业务验收。
- `evaluation/`：版本化案例、评价标准、人工标签、基线。
- `support/`：测试所有的组合根、报告与预算工具，产品不可依赖。

pytest 临时数据写入 `.tmp/pytest-runtime/`，正常结束后清理。
需保留的 JUnit、覆盖率、重复运行结果写入 `.tmp/evaluations/`，不上传。
不要把个人日志、会话、数据库、凭据或生成应用加入固定评测集。

浏览器、实时部署与真实模型均须显式选择，详见策略文档。
测试通过不等于真实模型质量、Neo4j 或外部工具已经通过业务验收。
