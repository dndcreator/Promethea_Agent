from __future__ import annotations

import ast
from typing import Any, Dict, Optional

from gateway.tool_service import ToolInvocationContext


class MathCalculateTool:
    tool_id = "math.calculate"
    name = "math.calculate"
    description = "Safely evaluate arithmetic expressions."
    official = True
    official_domain = "math"

    async def invoke(self, args: Dict[str, Any], ctx: Optional[ToolInvocationContext] = None) -> Any:
        _ = ctx
        expr = str((args or {}).get("expression") or "").strip()
        if not expr:
            raise ValueError("expression is required")
        value = _safe_eval(expr)
        return {"expression": expr, "value": value}


def _safe_eval(expression: str) -> float:
    node = ast.parse(expression, mode="eval")
    return float(_eval_node(node.body))


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        return left % right
    raise ValueError("unsupported expression")

