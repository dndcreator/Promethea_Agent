from enum import Enum
from typing import Dict, List, Optional, Set
from loguru import logger

class RiskLevel(Enum):
    SAFE = "safe"           # 只读、无副作用 (e.g. search, read_file)
    MODERATE = "moderate"   # 轻微副作用 (e.g. browser click, write_file to temp)
    HIGH = "high"           # 重大副作用 (e.g. shell_execute, delete_file, write_file to system)

class ToolPolicy:
    def __init__(self):
        # 默认高风险工具
        self.high_risk_tools: Set[str] = {
            "execute_command", 
            "run_script", 
            "delete_file", 
            "move_file",
            "replace_in_file", # 代码修改
            "write_file",      # 文件写入
            "computer_control" # 包含 shell/screen 操作
        }
        
        # 默认中风险工具
        self.moderate_risk_tools: Set[str] = {
            "browser_action",  # 浏览器操作
            "click",
            "type",
            "scroll"
        }
        
        # 自动批准的工具 (白名单)
        self.auto_approve_tools: Set[str] = {
            "search",
            "read_file",
            "list_files",
            "get_weather",
            "time",
            "date"
        }

    def check_risk(self, tool_name: str, args: Dict) -> RiskLevel:
        """评估工具调用的风险等级"""
        
        # 1. 检查具体的子命令 (针对 computer_control 等复合工具)
        if tool_name == "computer_control" or tool_name == "browser_action":
            action = args.get("action")
            if action in ["screenshot", "get_content", "get_url", "get_title", "get_mouse_position", "get_screen_size"]:
                return RiskLevel.SAFE
            return RiskLevel.MODERATE

        if tool_name in self.high_risk_tools:
            return RiskLevel.HIGH
        
        if tool_name in self.moderate_risk_tools:
            return RiskLevel.MODERATE
            
        return RiskLevel.SAFE

    def requires_confirmation(self, tool_name: str, args: Dict) -> bool:
        """判断是否需要用户确认"""
        risk = self.check_risk(tool_name, args)
        # 默认策略：高风险必须确认，中风险视情况（暂定自动），低风险自动
        return risk == RiskLevel.HIGH

# 全局策略实例
global_policy = ToolPolicy()
