"""
api_server 运行态单例（集中管理跨路由共享对象）

说明：
- 这是“拆路由文件”的过渡手段：把原来 chat_router.py 里的模块级对象集中到这里；
- 行为保持不变：仍是进程级单例。
"""

from __future__ import annotations

import sys
import os

# 兼容旧启动方式：确保项目根目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_core import PrometheaConversation
from agentkit.mcp.mcp_manager import MCPManager
from .metrics import get_metrics_collector

# 全局实例（与原 chat_router.py 行为一致）
conversation = PrometheaConversation()
mcp_manager = MCPManager()
metrics = get_metrics_collector()

