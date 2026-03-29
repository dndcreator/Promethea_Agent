# Promethea Backlog 全量对照（001-016）

日期：2026-03-24  
依据：`docs/backlogs/*.md` 全量逐条对照当前代码基线。

---

## 对照结论

1. 001-016 的主体能力在当前代码中已基本落地，不是“从零开始”。  
2. 本轮补齐了几个仍影响交付一致性的缺口：  
   - 工具可调用性显式化（`callable_now`）  
   - workflow 语义收敛（`scheduler_mode` + graph cycle check）  
   - pipeline 降级可见性（`stage_status` / `capability_state`）  
   - HTTP 统一错误模型增强（`retryable/dependency/advice/trace_id`）  
   - doctor 可执行修复建议与健康分级  
3. 差异化能力（memory/reasoning/workflow/tool/runtime）未削弱。

---

## Backlog 逐项状态

### 001 RunContext / SessionState
- 状态：已实现
- 对照：`gateway/models/session_state.py`、`gateway/models/run_context.py`、`gateway/server.py` 主链路传递

### 002 Gateway Protocol 统一化
- 状态：已实现（本轮增强）
- 对照：`gateway/protocol.py` 的 `GatewayRequest/GatewayResponse/GatewayEvent`
- 本轮补齐：`gateway/http/dispatcher.py` 统一错误 detail 字段

### 003 Conversation Pipeline Staging
- 状态：已实现（本轮增强）
- 对照：`gateway/conversation_pipeline.py` 六阶段
- 本轮补齐：`pipeline.stage_status`、`capability_state`

### 004 Prompt Block Assembler
- 状态：已实现
- 对照：`gateway/prompt_assembler.py`、pipeline 接入与测试

### 005 Tool Spec + Policy + Registry
- 状态：已实现（本轮增强）
- 对照：`gateway/tools/spec.py`、`gateway/tools/policy.py`、`gateway/tools/registry.py`
- 本轮补齐：`gateway/tool_service.py` 工具目录可调用性输出

### 006 Trace / Audit Foundation
- 状态：已实现
- 对照：`gateway/observability/*`、`gateway/events.py`、`tests/test_trace_audit_foundation.py`

### 007 Memory Write Gate
- 状态：已实现
- 对照：`gateway/memory_gate.py`、`gateway/memory_service.py`、`tests/test_memory_write_gate.py`

### 008 Reasoning Node State Machine
- 状态：已实现
- 对照：`gateway/reasoning_service.py` 的 `ReasoningNode` 与状态流转；`tests/test_reasoning_node_state_machine.py`

### 009 Workspace Sandbox MVP
- 状态：已实现
- 对照：`gateway/workspace_service.py`（WorkspaceHandle、边界检查、artifact）

### 010 MCP Health & Tool Panel
- 状态：已实现（本轮增强）
- 对照：`agentkit/mcp/mcp_manager.py`（MCPServiceHealth/MCPToolDescriptor）
- 本轮补齐：MCP 健康状态参与 `callable_now` 计算

### 011 Memory Recall Policy & Inspector
- 状态：已实现
- 对照：`gateway/memory_recall_schema.py`、`gateway/memory_service.py` inspector 路径、相关测试

### 012 Workflow Engine MVP
- 状态：已实现（本轮增强）
- 对照：`gateway/workflow_models.py`、`gateway/workflow_engine.py`
- 本轮补齐：`scheduler_mode`、graph cycle check、语义对齐测试

### 013 Channel Adapter Framework
- 状态：已实现
- 对照：`channels/adapter_framework.py`、`channels/adapters/*`、相关测试

### 014 Skill Layer & Official Packs
- 状态：已实现
- 对照：`skills/schema.py`、`skills/registry.py`、`tests/test_skill_layer_and_official_packs.py`

### 015 Config Schema & Migration
- 状态：已实现
- 对照：`gateway/config_migrations.py`、`gateway/config_service.py`、`tests/test_config_schema_migration.py`

### 016 Namespace & Security Audit
- 状态：已实现
- 对照：tool/workspace/memory/config 边界校验 + security audit 查询路径；`tests/test_namespace_security_audit.py`

---

## 本轮新增测试（业务/工程向）

1. `tests/test_mvp_business_smoke.py`  
2. `tests/test_http_dispatcher_error_model.py`  
3. `tests/test_doctor_recommendations.py`  
4. `tests/test_tool_service.py` 新增可调用性用例  
5. `tests/test_workflow_engine_mvp.py` 新增 graph cycle/scheduler 语义用例  
6. `tests/test_conversation_pipeline_staging.py` 新增降级可见性用例

