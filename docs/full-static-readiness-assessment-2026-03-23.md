# Promethea 工程实现评测报告（MVP/交付导向，2026-03-24）

## 0. 文档定位

这是一份面向工程落地的静态评测报告，目标不是“论文式架构描述”，而是回答 4 个实际问题：

1. 你的项目到底要做什么（产品与技术边界）  
2. 现在代码已经做到什么程度（功能 + 架构）  
3. 哪些问题会影响 MVP 交付  
4. 下一步按什么顺序做，风险最小、收益最大

> 说明：本报告基于源码、配置、文档、测试静态分析，不包含真实环境压测/联调结果。

---

## 1. 对项目目标的理解（先对齐）

从代码与文档（`README.md`、`PROJECT_OVERVIEW.md`、`docs/runtime-overview.md`、`gateway/*`）看，Promethea 的目标不是“聊天壳子”，而是一个可持续演进的 Agent Runtime：

- **控制平面**：Gateway 统一调度
- **能力平面**：Memory / Reasoning / Tool / Workflow / Workspace
- **治理平面**：Policy / Namespace / Audit / Trace
- **接入平面**：HTTP、WebSocket、UI、渠道插件

这意味着你的成功标准不是“能答一句话”，而是：

- 多用户隔离可控
- 工具调用可治理
- 长链路可恢复
- 问题可追踪可运维

这个方向本身是对的，而且你已经走到了“可交付雏形”阶段。

---

## 2. 评测范围与方法

## 2.1 覆盖范围

- 入口与生命周期：`start_gateway_service.py`、`gateway/app.py`
- 控制平面：`gateway/server.py`、`gateway/protocol.py`
- 对话执行：`gateway/conversation_service.py`、`gateway/conversation_pipeline.py`、`conversation_core.py`
- 工具执行：`gateway/tool_service.py`、`gateway/tools/*`、`agentkit/mcp/*`、`gateway/official_tools/*`
- 工作流：`gateway/workflow_engine.py`、`gateway/workflow_models.py`
- 记忆：`gateway/memory_service.py`、`memory/*`
- 安全与观测：`gateway/security/*`、`gateway/observability/*`
- 集成与注入：`gateway_integration.py`
- 接口层：`gateway/http/routes/*`、`gateway/http/dispatcher.py`
- 配置与默认值：`config.py`、`config/default.json`
- 计划文档：`docs/production-readiness-action-plan.md`

## 2.2 评测方法

- 功能可达性：是否有完整执行链路
- 架构一致性：设计宣称与代码语义是否一致
- 运行一致性：降级/异常是否可预测
- MVP 交付性：是否能在受控范围稳定对外

---

## 3. 当前状态总评（像 GitHub 成熟项目的 Readiness Summary）

## 3.1 总评分（静态）

- 架构完整度：**8.9 / 10**
- 功能落地度：**8.5 / 10**
- 工程可运维度：**7.5 / 10**
- MVP 可交付度：**7.8 / 10**

## 3.2 一句话结论

项目已经具备“可灰度上线的工程基础”，主要差距不在“缺功能”，而在“语义收敛、故障一致性、可观测闭环”。

---

## 4. 分层评测（功能实现 + 架构质量）

## 4.1 启动与注入链路

优点：

- 生命周期清晰（FastAPI lifespan）
- 关键子系统（conversation/mcp/gateway integration）均有初始化路径
- 集成层已补上官方工具二次注册，降低初始化时序风险

问题：

- 仍存在“失败告警后继续”的路径，容易出现部分能力失活但服务存活
- 多处异常吞掉（`except Exception: pass`）削弱诊断能力

判断：**可用，但运维可见性不足**

---

## 4.2 接口与协议边界（HTTP + WS）

优点：

- 路由覆盖完整，边界分层清楚
- dispatcher 把 HTTP 与 Gateway method 对齐，协议一致性好
- 错误码映射机制已存在

问题：

- 依赖缺失时错误语义在不同路由分散，不够统一
- “降级可继续”和“硬失败”缺统一呈现规范

判断：**接口设计成熟，错误治理需统一**

---

## 4.3 对话主链路（Pipeline）

优点：

- 六阶段 pipeline 已稳定成型
- `tool_executor` 在会话链路中真实可用
- 结构化 IO 与阶段事件做得好（便于演进和回放）

问题：

- 部分 fallback 为静默，不利于上层判断质量退化

判断：**主链路工程质量高，适合 MVP**

---

## 4.4 工具系统（Local/MCP/Agent）

优点：

- ToolService 统一入口清晰
- ToolSpec/Registry/Policy 设计完整
- 高风险工具可做策略与确认控制

问题：

- “工具可见”不代表“当前可调用”（策略 + 依赖 + 权限共同决定）
- 该状态未统一透出给调用方

判断：**能力强，产品可解释性需补强**

---

## 4.5 工作流系统（本次重点）

最新代码确认：

- `tool_step` 已真实执行，不再是占位
- 存在 async 主链路（`advance_to_next_step_async`）
- `parallel` 路径支持批执行
- 依赖失败有结构化错误（`dependency_unavailable`）

仍需收敛：

- `workflow_type` 包含 `graph`，但语义边界仍需要文档和契约层明确
- 兼容桥接函数 `_run_async_blocking` 仍在，非主链路但有阻塞风险入口

判断：**从 MVP 向可交付迈进明显，剩余是语义和一致性问题**

---

## 4.6 记忆系统

优点：

- 三后端能力与治理模型（write gate / recall policy）较完整
- 有 inspector 思路和相关测试

问题：

- 真实可用性依赖部署条件（尤其图后端）
- 降级路径较多，用户可见性不足

判断：**工程深度够，默认体验仍受环境影响**

---

## 4.7 推理系统

优点：

- ReAct/ToT/状态机路径完整
- 与 memory/tool/workflow 结合深度高

问题：

- 多处 skip/fallback 需要统一 reason code 透出
- 成功判定机制仍有模型判断不稳定性

判断：**差异化能力强，但需要更强运行可解释性**

---

## 4.8 安全与可观测

优点：

- namespace 边界（config/session/memory/workspace）设计正确
- trace/audit/ops/status 已成体系

问题：

- 阻断 vs 审计 vs 告警策略分级还不够统一
- 诊断建议自动化不足

判断：**基础强，离“生产运维友好”只差最后一层**

---

## 5. 风险清单（MVP 视角）

## P0（上线前必须解决）

1. 关键依赖缺失场景的统一行为（不要每个接口各自报错风格）
2. workflow 类型对外语义与执行行为的统一说明（特别是 `graph`）

## P1（灰度前强烈建议解决）

1. `_run_async_blocking` 兼容桥接路径的风险收敛（明确禁用场景或替换）
2. 工具 `callable_now` 透出，避免“看得到用不了”
3. pipeline/记忆/推理降级信息对调用方可见

## P2（可持续迭代）

1. 异常吞掉点收敛，减少假健康
2. 渠道/插件 E2E 证据加强
3. readiness 报表自动化

---

## 6. 与工程师计划的融合结论

参考：`docs/production-readiness-action-plan.md`

该计划总体质量较高，建议继续沿用。  
我建议把它作为“执行层文档”，本报告作为“评审与决策层文档”。

保留的核心执行策略：

1. 先 P0，再关键 P1
2. 统一错误模型与健康分级
3. workflow 语义一致化
4. 全链路 smoke + CI readiness

新增建议（补齐 CTO 视角）：

1. 增加发布闸门（go/no-go）
2. 增加放量闸门（scale/no-scale）
3. 增加负责人矩阵（Runtime/Capability/SRE/QA）

---

## 7. MVP 推进建议（务实版）

只做最关键的 6 件事：

1. 统一依赖缺失错误模型（HTTP/WS/Gateway）
2. 明确 workflow 类型当前支持边界（尤其 graph）
3. 所有降级路径输出 `degraded + reason_code`
4. 工具目录增加 `callable_now`
5. 打通最小 smoke：`chat -> memory -> tool -> workflow -> audit`
6. 出一份自动 readiness 报表（每次发布必看）

如果你团队资源有限，先做 1/2/5，MVP 质量会明显上一个台阶。

---

## 8. 最终判定（当前版本）

## 8.1 是否“能做 MVP”

**能。**  
而且不是勉强能，是有明确工程骨架支撑的 MVP。

## 8.2 是否“适合直接大规模放量”

**暂不建议。**  
等 P0 + 关键 P1 收敛后再放量更稳。

## 8.3 你当前最该自信的点

你的项目已经从“功能集合”进化到“运行时系统”。  
现在要做的是工程收敛，不是推倒重来。

---

## 9. 版本记录

- 2026-03-23：初版静态评测
- 2026-03-24：重写为工程/MVP导向版本
- 2026-03-24（本次）：融合最新代码与整改计划，升级为专业交付评测版

