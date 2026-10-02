# AgentKit Module

AgentKit supplies tool implementations, external MCP transport, tool-call orchestration, structured results, approval, and sandbox enforcement.

## Responsibilities

- MCP management
- tool-call orchestration
- structured tool result normalization
- approval and sandbox enforcement

## Key Files

- `agentkit/mcp/mcp_manager.py`: MCP manager
- `agentkit/mcp/mcpregistry.py`: MCP-backed service registry
- `agentkit/mcp/agent_manager.py`: agent coordination
- `agentkit/mcp/tool_call.py`: tool-call pipeline
- `agentkit/mcp/tool_result.py`: canonical tool result and error mapping
- `agentkit/security/approval.py`: exact-call approval scope
- `agentkit/security/sandbox.py`: workspace and host capability policy
- `agentkit/security/process_sandbox.py`: platform process sandbox selection
- `agentkit/tools/computer/*`: computer tool definitions
- `gateway/official_tools/*`: built-in local tools, including the canonical `web.search` capability
- `agentkit/tools/FEWSHOT_TOOL_SCRIPT_EXAMPLE.md`: LLM-ready few-shot template for generating new tools

## Workflow

1. The conversation layer decides whether a tool is needed.
2. AgentKit builds the invocation request.
3. Startup discovery or hot reload registers manifest tools into `ToolRegistry`.
4. `CapabilityService` owns every invocation; only true external MCP tools delegate transport to `MCPManager`.
5. Execution returns structured output.
6. The conversation layer integrates the result into the final answer.

## Notes

- Security policy should always gate execution.
- Failures should be observable and diagnosable.
- Long-running tool calls should propagate cancellation safely.
