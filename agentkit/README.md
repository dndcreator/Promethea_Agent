# AgentKit Module

---

## 中文文档

### 1. 模块职责

`agentkit` 是 Agent 调用层基础设施，负责：
- MCP 管理
- 工具调用封装
- 流式工具调用
- 安全策略约束

### 2. 关键文件

- `agentkit/mcp/mcp_manager.py`：MCP 管理器
- `agentkit/mcp/mcpregistry.py`：MCP 服务注册
- `agentkit/mcp/agent_manager.py`：Agent 管理协调
- `agentkit/mcp/tool_call.py`：工具调用主流程
- `agentkit/mcp/streaming_tool_call.py`：流式工具调用
- `agentkit/security/policy.py`：安全策略
- `agentkit/tools/computer/*`：本机控制工具定义
- `agentkit/tools/web/*`：Web 搜索工具定义

### 3. 工作流

1. 对话层判定需要工具
2. AgentKit 解析并构造调用请求
3. 通过 MCP registry 找到目标服务
4. 执行并返回结构化结果
5. 对话层把结果整合成最终回复

### 4. 注意事项

- 安全策略优先于便利性
- 工具失败要可观测、可诊断
- 流式工具调用需保证可中断

---

## English Documentation

### 1. Purpose

`agentkit` is the agent-execution foundation for:
- MCP management
- tool-call orchestration
- streaming tool call support
- security policy enforcement

### 2. Key Files

- `agentkit/mcp/mcp_manager.py`: MCP manager
- `agentkit/mcp/mcpregistry.py`: service registry
- `agentkit/mcp/agent_manager.py`: agent coordination
- `agentkit/mcp/tool_call.py`: tool-call pipeline
- `agentkit/mcp/streaming_tool_call.py`: streaming tool execution
- `agentkit/security/policy.py`: security policy
- `agentkit/tools/computer/*`: computer tool definitions
- `agentkit/tools/web/*`: web tool definitions

### 3. Workflow

1. conversation layer decides tool usage
2. AgentKit builds invocation request
3. MCP registry resolves target service
4. execution returns structured output
5. conversation layer integrates result into final answer

### 4. Notes

- security policy should always gate execution
- failures should be observable and diagnosable
- streaming tool calls should support interruption safely
