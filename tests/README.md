# 测试说明

本目录包含单元测试和回归测试。

## 推荐执行方式

推荐先安装开发依赖：

```powershell
pip install -e .[dev]
```

然后运行：

```powershell
pytest -q tests/
```

## 常用测试分组

- 会话与回合写入：`test_message_manager_turns.py`
- 记忆回归：`test_memory_regressions.py`
- 遗忘回归：`test_memory_forgetting_regressions.py`
- 对话队列：`test_conversation_queue.py`

## Demo 前最小回归集

```powershell
pytest -q tests/test_message_manager_turns.py tests/test_memory_regressions.py tests/test_conversation_queue.py
```

## 测试建议

1. 先跑纯单元测试，再跑集成测试。
2. 涉及 Neo4j 的测试请在独立测试库执行。
3. 每次修改隔离逻辑后，务必做多用户交叉回归。
