from enum import Enum
from typing import Dict, Set, Any


class RiskLevel(Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"


class ToolRiskLevel(Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"


class ToolPolicy:
    def __init__(self):
        self.high_risk_tools: Set[str] = {
            "execute_command",
            "run_script",
            "delete_file",
            "move_file",
            "replace_in_file",
            "write_file",
            "computer_control",
        }

        self.moderate_risk_tools: Set[str] = {
            "browser_action",
            "click",
            "type",
            "scroll",
        }

        self.auto_approve_tools: Set[str] = {
            "search",
            "read_file",
            "list_files",
            "get_weather",
            "time",
            "date",
        }

        # Backward-compatible map used by existing tests and older callers
        self.tool_risk_map: Dict[str, ToolRiskLevel] = {
            tool: ToolRiskLevel.HIGH for tool in self.high_risk_tools
        }
        self.tool_risk_map.update({
            tool: ToolRiskLevel.MODERATE for tool in self.moderate_risk_tools
        })

    def check_risk(self, tool_name: str, args: Dict[str, Any]) -> RiskLevel:
        direct_level = self.tool_risk_map.get(tool_name)
        if direct_level:
            return RiskLevel(direct_level.value)

        nested_tool_name = args.get("tool_name") if isinstance(args, dict) else None
        nested_level = self.tool_risk_map.get(nested_tool_name)
        if nested_level:
            return RiskLevel(nested_level.value)

        if tool_name in {"computer_control", "browser_action"}:
            action = args.get("action") if isinstance(args, dict) else None
            if action in {
                "screenshot",
                "get_content",
                "get_url",
                "get_title",
                "get_mouse_position",
                "get_screen_size",
            }:
                return RiskLevel.SAFE
            return RiskLevel.MODERATE

        if tool_name in self.high_risk_tools:
            return RiskLevel.HIGH
        if tool_name in self.moderate_risk_tools:
            return RiskLevel.MODERATE
        return RiskLevel.SAFE

    def requires_confirmation(self, tool_name: str, args: Dict[str, Any]) -> bool:
        return self.check_risk(tool_name, args) == RiskLevel.HIGH


global_policy = ToolPolicy()
