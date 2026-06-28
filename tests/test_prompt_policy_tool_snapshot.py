from __future__ import annotations

from gateway.conversation_service import ConversationService


class _ToolService:
    async def get_tool_catalog(self, *, run_context=None, user_config=None):
        _ = (run_context, user_config)
        return [
            {
                "tool_type": "mcp",
                "service_name": "computer_control",
                "tool_name": "write_file",
                "description": "Write text file quickly.",
                "callable_now": True,
                "requires_confirmation": True,
            },
            {
                "tool_type": "mcp",
                "service_name": "hidden",
                "tool_name": "offline",
                "description": "Unavailable tool.",
                "callable_now": False,
            },
        ]


async def test_prompt_policy_snapshot_preserves_structured_registered_tools():
    service = ConversationService(tool_service=_ToolService())

    tools = await service._build_prompt_policy_tool_snapshot(
        run_context=None,
        user_config={},
    )

    assert tools == [
        {
            "name": "computer_control.write_file",
            "service_name": "computer_control",
            "tool_name": "write_file",
            "tool_type": "mcp",
            "description": "Write text file quickly.",
            "requires_confirmation": True,
            "callable_now": True,
            "callable_reason": "",
            "policy_allowed": True,
            "dependency_ready": True,
        },
        {
            "name": "hidden.offline",
            "service_name": "hidden",
            "tool_name": "offline",
            "tool_type": "mcp",
            "description": "Unavailable tool.",
            "requires_confirmation": False,
            "callable_now": False,
            "callable_reason": "",
            "policy_allowed": True,
            "dependency_ready": True,
        }
    ]
