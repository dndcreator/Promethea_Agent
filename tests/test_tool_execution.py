import unittest
import asyncio
import time
from datetime import datetime, timezone

from agentkit.security.policy import global_policy

from agentkit.mcp.tool_call import parse_tool_calls, execute_tool_calls, tool_call_loop
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

    def test_parse_tool_call_preserves_nested_mcp_action(self):
        calls = parse_tool_calls(
            '{"tool_name":"content_tools","agentType":"mcp","service_name":"content_tools",'
            '"args":{"tool_name":"web_fetch","url":"https://www.news.cn/","timeout":15}}'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "content_tools")
        self.assertEqual(calls[0]["args"]["service_name"], "content_tools")
        self.assertEqual(calls[0]["args"]["tool_name"], "web_fetch")
        self.assertEqual(calls[0]["args"]["url"], "https://www.news.cn/")

    def test_parse_tool_call_supports_action_envelope(self):
        calls = parse_tool_calls(
            '{"action":"tool_call","tool_name":"content_tools.web_fetch",'
            '"args":{"url":"https://example.com","timeout":15}}'
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "content_tools.web_fetch")
        self.assertEqual(calls[0]["args"]["url"], "https://example.com")
        self.assertNotIn("action", calls[0]["args"])

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

    def test_local_tool_executor_receives_strict_json_calls(self):
        async def run_test():
            manager = MockMCPManager()
            seen = []

            async def tool_executor(name, payload):
                seen.append((name, payload))
                return {"value": 20}

            calls = parse_tool_calls(
                '{"tool_name":"math.calculate","agentType":"local","service_name":"math.calculate","args":{"expression":"100 / 5"}}'
            )
            result = await execute_tool_calls(calls, manager, tool_executor=tool_executor)

            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][0], "math.calculate")
            self.assertEqual(seen[0][1]["expression"], "100 / 5")
            flat_text = "\n".join([b.get("text", "") for b in result if b.get("type") == "text"])
            self.assertIn('"value": 20', flat_text)
            self.assertEqual(manager.call_log, [])

        asyncio.run(run_test())

    def test_tool_loop_injects_lightweight_react_gate_after_observation(self):
        async def run_test():
            manager = MockMCPManager()
            responses = [
                {
                    "content": (
                        '{"tool_name":"math.calculate","agentType":"local",'
                        '"service_name":"math.calculate","args":{"expression":"2 + 2"}}'
                    )
                },
                {"content": "The observed result is 4."},
            ]
            seen = []

            async def llm_caller(messages):
                seen.append(messages)
                return responses.pop(0)

            async def tool_executor(name, payload):
                _ = (name, payload)
                return {"ok": True, "value": 4}

            out = await tool_call_loop(
                messages=[{"role": "user", "content": "calculate 2 + 2"}],
                mcp_manager=manager,
                llm_caller=llm_caller,
                tool_executor=tool_executor,
                max_recursion=2,
            )

            self.assertEqual(out["content"], "The observed result is 4.")
            second_turn_messages = seen[1]
            observation = second_turn_messages[-1]["content"]
            flat_text = "\n".join(
                block.get("text", "")
                for block in observation
                if isinstance(block, dict) and block.get("type") == "text"
            )
            self.assertIn("Lightweight ReAct gate", flat_text)
            self.assertIn("Observation", flat_text)

        asyncio.run(run_test())

    def test_tool_result_serializes_non_json_native_values(self):
        async def run_test():
            manager = MockMCPManager()

            async def tool_executor(name, payload):
                return {
                    "ok": True,
                    "entries": [
                        {
                            "content": "remembered fact",
                            "created_at": datetime(2026, 6, 12, 6, 30, tzinfo=timezone.utc),
                        }
                    ],
                }

            calls = parse_tool_calls(
                '{"tool_name":"memory.list_entries","agentType":"local",'
                '"service_name":"memory.list_entries","args":{"limit":1}}'
            )
            result = await execute_tool_calls(calls, manager, tool_executor=tool_executor)
            flat_text = "\n".join([b.get("text", "") for b in result if b.get("type") == "text"])

            self.assertIn('"ok": true', flat_text)
            self.assertIn('"created_at": "2026-06-12T06:30:00+00:00"', flat_text)
            self.assertNotIn("Error executing tool", flat_text)

        asyncio.run(run_test())

    def test_action_mode_retries_invalid_first_action_object(self):
        async def run_test():
            manager = MockMCPManager()
            responses = [
                {"content": "Calling math.calculate to compute 2 + 2."},
                {
                    "content": (
                        '{"action":"tool_call","tool_name":"math.calculate","agentType":"local",'
                        '"service_name":"math.calculate","args":{"expression":"2 + 2"}}'
                    )
                },
                {"content": '{"action":"answer","content":"The observed result is 4."}'},
            ]
            seen = []

            async def llm_caller(messages):
                seen.append([dict(message) for message in messages])
                return responses.pop(0)

            async def tool_executor(name, payload):
                _ = (name, payload)
                return {"ok": True, "value": 4}

            out = await tool_call_loop(
                messages=[
                    {"role": "system", "content": "Action mode contract:"},
                    {"role": "user", "content": "calculate 2 + 2"},
                ],
                mcp_manager=manager,
                llm_caller=llm_caller,
                tool_executor=tool_executor,
                max_recursion=2,
            )

            self.assertEqual(out["content"], "The observed result is 4.")
            flat_retry_text = "\n".join(
                str(message.get("content") or "") for message in seen[1]
            )
            self.assertIn("Protocol correction", flat_retry_text)

        asyncio.run(run_test())

    def test_action_mode_accepts_structured_answer_without_tool(self):
        async def run_test():
            manager = MockMCPManager()

            async def llm_caller(messages):
                _ = messages
                return {"content": '{"action":"answer","content":"No suitable tool is available."}'}

            out = await tool_call_loop(
                messages=[
                    {"role": "system", "content": "Action mode contract:"},
                    {"role": "user", "content": "do something unavailable"},
                ],
                mcp_manager=manager,
                llm_caller=llm_caller,
                max_recursion=2,
            )

            self.assertEqual(out["content"], "No suitable tool is available.")
            self.assertEqual(out["recursion_depth"], 0)

        asyncio.run(run_test())

    def test_tool_loop_does_not_return_unexecuted_json_after_budget_exhaustion(self):
        async def run_test():
            manager = MockMCPManager()
            responses = [
                {
                    "content": (
                        '{"tool_name":"websearch.news_search","agentType":"mcp",'
                        '"service_name":"websearch","args":{"query":"today news"}}'
                    )
                },
                {
                    "content": (
                        '{"tool_name":"content_tools.web_fetch","agentType":"mcp",'
                        '"service_name":"content_tools","args":{"url":"https://news.google.com"}}'
                    )
                },
            ]
            seen = []

            async def llm_caller(messages):
                seen.append(messages)
                return responses.pop(0)

            async def tool_executor(name, payload):
                _ = (name, payload)
                return {"error": "HTTP 403 Forbidden"}

            out = await tool_call_loop(
                messages=[{"role": "user", "content": "check today's news"}],
                mcp_manager=manager,
                llm_caller=llm_caller,
                tool_executor=tool_executor,
                max_recursion=1,
            )

            self.assertEqual(out["status"], "success")
            self.assertFalse(out["content"].lstrip().startswith("{"))
            self.assertIn("could not complete", out["content"])
            flat_text = "\n".join(
                block.get("text", "")
                for message in seen[1]
                for block in (
                    message.get("content", [])
                    if isinstance(message.get("content"), list)
                    else []
                )
                if isinstance(block, dict) and block.get("type") == "text"
            )
            self.assertIn("No tool steps remain", flat_text)
            self.assertIn('"action":"answer"', flat_text)

        asyncio.run(run_test())

    def test_action_mode_final_answer_requires_answer_envelope_after_budget_exhaustion(self):
        async def run_test():
            manager = MockMCPManager()
            responses = [
                {
                    "content": (
                        '{"action":"tool_call","tool_name":"web.fetch_text",'
                        '"args":{"url":"https://example.com/blocked"}}'
                    )
                },
                {"content": "Calling web.fetch_text to fetch https://fallback.example.com"},
                {"content": '{"action":"answer","content":"The page was blocked by the observed response."}'},
            ]
            seen = []

            async def llm_caller(messages):
                seen.append([dict(message) for message in messages])
                return responses.pop(0)

            async def tool_executor(name, payload):
                _ = (name, payload)
                return {"status": 202, "text": "captcha"}

            out = await tool_call_loop(
                messages=[
                    {"role": "system", "content": "Action mode contract:"},
                    {"role": "user", "content": "fetch the full article"},
                ],
                mcp_manager=manager,
                llm_caller=llm_caller,
                tool_executor=tool_executor,
                max_recursion=1,
            )

            self.assertEqual(out["content"], "The page was blocked by the observed response.")
            final_retry_text = "\n".join(str(message.get("content") or "") for message in seen[-1])
            self.assertIn('{"action":"answer","content":"..."}', final_retry_text)

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
        self.assertIn("", new_messages[0]['content'])
        self.assertIn("mock_service", new_messages[0]['content'])

if __name__ == '__main__':
    unittest.main()

