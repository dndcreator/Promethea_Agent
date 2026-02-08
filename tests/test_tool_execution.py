import unittest
import asyncio
import time

from agentkit.security.policy import global_policy

from agentkit.mcp.tool_call import parse_tool_calls, execute_tool_calls
from conversation_core import PrometheaConversation

class MockMCPManager:
    """Mock MCP Manager for testing"""
    def __init__(self):
        self.call_log = []

    async def unified_call(self, service_name, tool_name, args):
        self.call_log.append({
            "service": service_name,
            "tool": tool_name,
            "args": args
        })
        # Simulate delay to verify parallelism
        await asyncio.sleep(0.1)
        return {"success": True, "result": f"Result from {service_name}.{tool_name}"}
        
    def format_available_services(self):
        return "- mock_service: Mock Description"

class TestToolExecution(unittest.TestCase):

    def test_parse_tool_calls(self):
        """Test parsing of tool calls from LLM output"""
        content = """
        Thinking about weather...
        { "tool_name": "search", "args": { "query": "weather" } }
        Also checking calendar...
        { "tool_name": "calendar", "args": { "action": "list" } }
        """
        calls = parse_tool_calls(content)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['name'], 'search')
        self.assertEqual(calls[1]['name'], 'calendar')

    def test_parallel_execution(self):
        """Test parallel execution of tool calls"""
        async def run_test():
            manager = MockMCPManager()
            tool_calls = [
                {'name': 't1', 'args': {'service_name': 's1', 'tool_name': 'func1', 'a': 1}},
                {'name': 't2', 'args': {'service_name': 's2', 'tool_name': 'func2', 'b': 2}}
            ]
            
            start = time.time()
            result = await execute_tool_calls(tool_calls, manager)
            end = time.time()
            
            # Since each call sleeps 0.1s, parallel execution should take roughly 0.1s, not 0.2s
            # We allow some overhead, but it should be fast
            self.assertLess(end - start, 0.18, "Execution should be parallel")
            
            self.assertEqual(len(manager.call_log), 2)
            # execute_tool_calls now returns a list of content blocks
            flat_text = "\n".join([b.get("text", "") for b in result if b.get("type") == "text"])
            self.assertIn("Result from s1.func1", flat_text)
            self.assertIn("Result from s2.func2", flat_text)
            
        asyncio.run(run_test())

    def test_hitl_batch_preserved_and_chainable(self):
        """If any tool in a batch is high-risk, it should request confirmation and preserve the full batch."""
        async def run_test():
            manager = MockMCPManager()

            # Force 'press_keys' to be HIGH risk for this test
            original = dict(global_policy.tool_risk_map)
            try:
                # ensure at least one tool is considered HIGH
                from agentkit.security.policy import ToolRiskLevel
                global_policy.tool_risk_map["press_keys"] = ToolRiskLevel.HIGH

                tool_calls = [
                    {"name": "safe1", "args": {"service_name": "s1", "tool_name": "search", "q": "x"}},
                    {"name": "danger", "args": {"service_name": "s2", "tool_name": "press_keys", "keys": ["ALT", "F4"]}},
                    {"name": "safe2", "args": {"service_name": "s3", "tool_name": "search", "q": "y"}},
                ]

                from agentkit.mcp.tool_call import ToolConfirmationRequired
                with self.assertRaises(ToolConfirmationRequired):
                    await execute_tool_calls(tool_calls, manager, session_id="t", approved_call_ids=set())

                # No calls should have executed because we pre-scan and abort the whole batch
                self.assertEqual(manager.call_log, [])
            finally:
                global_policy.tool_risk_map = original

        asyncio.run(run_test())

    def test_system_prompt_injection(self):
        """Test system prompt injection in ConversationCore"""
        # Mock dependencies
        conv = PrometheaConversation()
        conv.mcp_manager = MockMCPManager()
        
        messages = [{'role': 'user', 'content': 'hello'}]
        new_messages = conv.prepare_messages(messages)
        
        self.assertEqual(len(new_messages), 2)
        self.assertEqual(new_messages[0]['role'], 'system')
        self.assertIn("可用工具", new_messages[0]['content'])
        self.assertIn("mock_service", new_messages[0]['content'])

if __name__ == '__main__':
    unittest.main()
