from __future__ import annotations

from gateway.conversation_service import ConversationService


class _CapabilityService:
    async def build_capability_snapshot(self, *, run_context=None, user_config=None, preferred_tools=None):
        _ = (run_context, user_config, preferred_tools)
        rows = [
            {
                "name": "computer_control.write_file",
                "description": "Write text file quickly.",
                "callable_now": True,
                "callable_reason": "callable",
                "requires_confirmation": True,
                "schema_status": "declared",
                "capability_type": "mcp",
            },
            {
                "name": "hidden.offline",
                "description": "Unavailable tool.",
                "callable_now": False,
                "callable_reason": "service_unavailable",
                "requires_confirmation": False,
                "schema_status": "missing",
                "capability_type": "mcp",
            },
        ]
        return {
            "snapshot_id": "caps-1",
            "compact_index": rows,
            "selected_specs": [
                {
                    "name": "computer_control.write_file",
                    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    "output_schema": {},
                }
            ],
        }


async def test_runtime_snapshot_preserves_structured_registered_tools():
    service = ConversationService(capability_service=_CapabilityService())

    tools = await service._build_runtime_tool_snapshot(
        run_context=None,
        user_config={},
    )

    assert tools == [
        {
            "name": "computer_control.write_file",
            "description": "Write text file quickly.",
            "requires_confirmation": True,
            "callable_now": True,
            "callable_reason": "callable",
            "schema_status": "declared",
            "capability_type": "mcp",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
        {
            "name": "hidden.offline",
            "description": "Unavailable tool.",
            "requires_confirmation": False,
            "callable_now": False,
            "callable_reason": "service_unavailable",
            "schema_status": "missing",
            "capability_type": "mcp",
        }
    ]
