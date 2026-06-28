# AgentKit Module

AgentKit is the agent execution layer for MCP service management, tool-call orchestration, streaming tool calls, and security policy enforcement.

## Responsibilities

- MCP management
- tool-call orchestration
- streaming tool call support
- security policy enforcement

## Key Files

- `agentkit/mcp/mcp_manager.py`: MCP manager
- `agentkit/mcp/mcpregistry.py`: service registry
- `agentkit/mcp/agent_manager.py`: agent coordination
- `agentkit/mcp/tool_call.py`: tool-call pipeline
- `agentkit/mcp/streaming_tool_call.py`: streaming tool execution
- `agentkit/security/policy.py`: security policy
- `agentkit/tools/computer/*`: computer tool definitions
- `agentkit/tools/web/*`: web tool definitions
- `agentkit/tools/FEWSHOT_TOOL_SCRIPT_EXAMPLE.md`: LLM-ready few-shot template for generating new tools

## Workflow

1. The conversation layer decides whether a tool is needed.
2. AgentKit builds the invocation request.
3. The MCP registry resolves the target service.
4. Execution returns structured output.
5. The conversation layer integrates the result into the final answer.

## Notes

- Security policy should always gate execution.
- Failures should be observable and diagnosable.
- Streaming tool calls should support interruption safely.
