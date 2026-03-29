# Promethea 报告对照与改造落地矩阵（2026-03-24）

基准文档：`docs/full-static-readiness-assessment-2026-03-23.md`（2026-03-24 重写版）  
目标：在不削弱差异化能力前提下，优先满足 MVP 可交付。

---

## 总体判断

报告结论成立，可作为后续修改基础。  
工程重点应从“补功能”转为“统一行为 + 可解释性 + 冒烟验收”。

---

## 模块对照矩阵

### 1. 启动与注入链路
- 结论：可用，存在降级路径可见性不足。
- 当前处理：部分已覆盖（状态接口可观察基础服务）。
- MVP动作：保留现有能力；补统一健康分级和降级原因字段。
- 优先级：P1

### 2. 接口与协议边界（HTTP/WS）
- 结论：边界成熟，错误风格分散。
- 当前处理：已有路由和 dispatcher 收敛。
- MVP动作：统一依赖缺失错误模型（code/message/dependency/advice）。
- 优先级：P0

### 3. 对话主链路（Pipeline）
- 结论：主链路强，fallback 不够透明。
- 本次改动：新增 `pipeline.stage_status` 与 `capability_state`，可见 degraded reason。
- 结果：MVP 场景下可判断“成功但降级”。
- 优先级：已落地（继续补全）

### 4. 工具系统
- 结论：能力完整，产品感知不足（看得到但不一定能调用）。
- 本次改动：`get_tool_catalog` 增加 `callable_now/callable_reason/policy_allowed/dependency_ready`。
- 结果：调用方可在执行前判断可调用性。
- 优先级：已落地

### 5. 工作流系统
- 结论：已进入可交付阶段，语义仍需收敛。
- 本次改动：
  - `workflow_type` 归一化；
  - 增加 `scheduler_mode`；
  - `graph/dag/parallel` 增加循环依赖校验；
  - 保持 async 主链路。
- 结果：类型语义比之前一致，错误更可预测。
- 优先级：P0（基本落地）

### 6. 记忆系统
- 结论：能力强，部署敏感。
- 当前处理：已有多后端与健康接口。
- MVP动作：继续补统一 reason_code，尤其后端不可用时的用户可见解释。
- 优先级：P1

### 7. 推理系统
- 结论：差异化强，skip/fallback 可解释性不足。
- 当前处理：已有 workflow trace 与多策略。
- MVP动作：统一 skip reason_code 与策略选择说明。
- 优先级：P1

### 8. 安全与可观测
- 结论：基础好，策略等级与修复建议闭环不足。
- 当前处理：已有 audit/trace/status/ops。
- MVP动作：健康分级 + 自动建议（doctor/ops）。
- 优先级：P1

### 9. 渠道/插件
- 结论：扩展性好，E2E 证据弱。
- MVP动作：增加契约级 smoke，不追求全量仿真。
- 优先级：P2

### 10. 本机控制
- 结论：能力强，权限边界需更清晰。
- MVP动作：明确默认可用边界与高风险动作确认规则。
- 优先级：P2

### 11. 配置体系
- 结论：方向正确。
- MVP动作：维持“默认全开”，但对依赖不满足场景给出显式提示。
- 优先级：P1

### 12. 测试体系
- 结论：原有测试偏单元，业务闭环不足。
- 本次改动：
  - 增加工具可调用性测试；
  - 增加 workflow graph cycle/scheduler_mode 测试；
  - 增加 pipeline 降级可见性测试；
  - 新增业务冒烟测试集 `tests/test_mvp_business_smoke.py`。
- 优先级：已落地（继续补 smoke 脚本）

---

## 本次落地文件

- `gateway/tool_service.py`
- `gateway/workflow_engine.py`
- `gateway/conversation_pipeline.py`
- `tests/test_tool_service.py`
- `tests/test_workflow_engine_mvp.py`
- `tests/test_conversation_pipeline_staging.py`
- `tests/test_mvp_business_smoke.py`

---

## MVP 判定（当前）

- 能力差异化：保留（Memory/Reasoning/Tool/Workflow 组合未削弱）
- 可交付性：提升（可调用性与降级可见性增强）
- 大规模放量：仍建议在统一错误模型与 readiness 报表后进行


## 追加修正（同日）

- WS 请求入口对齐 HTTP：增加参数校验、service_guard、统一 `error_detail` 回传。
- 启动快照落地：`gateway/http/state.py` 增加 `startup_report`，`/api/status` 与 `/api/status/services` 透出。
- 新增 `/api/ops/readiness`：输出 go/no-go、关键服务失败列表、启动退化影响与修复建议。
- 协议发现补齐：`/api/ops/readiness` 纳入 surface/CLI reference。
- 测试新增：
  - `tests/test_gateway_ws_error_model.py`
  - `tests/test_ops_readiness.py`
  - `tests/test_status_startup_report.py`
