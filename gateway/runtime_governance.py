from __future__ import annotations

from typing import Any, Dict, List, Optional


STAGE_NODE_ORDER = [
    ("input_normalization", "input"),
    ("mode_detection", "mode"),
    ("memory_recall", "memory"),
    ("planning_reasoning", "reasoning"),
    ("tool_execution", "tools"),
    ("response_synthesis", "response"),
]


def build_task_graph_snapshot(
    *,
    stage_status: Dict[str, Any],
    mode: str,
    response_status: str,
    workflow_trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    for stage_name, node_id in STAGE_NODE_ORDER:
        info = stage_status.get(stage_name) if isinstance(stage_status, dict) else None
        status = "pending"
        if isinstance(info, dict):
            status = str(info.get("status") or "pending")
        node: Dict[str, Any] = {
            "id": node_id,
            "stage": stage_name,
            "status": status,
            "type": "pipeline_stage",
        }
        nodes.append(node)

    edges: List[Dict[str, str]] = []
    for idx in range(len(STAGE_NODE_ORDER) - 1):
        edges.append(
            {
                "from": STAGE_NODE_ORDER[idx][1],
                "to": STAGE_NODE_ORDER[idx + 1][1],
                "relation": "next",
            }
        )

    current_node_id = "response"
    for node in nodes:
        if node["status"] in {"pending", "degraded", "failed"}:
            current_node_id = str(node["id"])
            break

    metadata: Dict[str, Any] = {"mode": str(mode or "fast")}
    if isinstance(workflow_trace, dict) and workflow_trace:
        metadata["workflow_trace"] = {
            "workflow_id": workflow_trace.get("workflow_id"),
            "workflow_run_id": workflow_trace.get("workflow_run_id"),
        }

    return {
        "version": "1.0",
        "status": str(response_status or "success"),
        "current_node_id": current_node_id,
        "nodes": nodes,
        "edges": edges,
        "metadata": metadata,
    }


def build_orchestration_snapshot(
    *,
    mode: str,
    used_reasoning: bool,
    workflow_trace: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    reasoning_payload = reasoning if isinstance(reasoning, dict) else {}
    return {
        "version": "1.0",
        "execution_core": "single_loop_runtime",
        "scheduler_mode": "pipeline_compat",
        "reasoning_engine": {
            "enabled": bool(used_reasoning),
            "mode": str(mode or "fast"),
            "tree_id": str(reasoning_payload.get("tree_id") or "") or None,
            "strategy": "react_tot" if bool(used_reasoning) else "fast_path",
        },
        "workflow_bridge": {
            "enabled": bool(isinstance(workflow_trace, dict) and workflow_trace),
            "workflow_run_id": (
                str((workflow_trace or {}).get("workflow_run_id") or "")
                if isinstance(workflow_trace, dict)
                else None
            )
            or None,
        },
    }


def build_context_budget_snapshot(prompt_assembly: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(prompt_assembly or {})
    used_block_ids = payload.get("used_block_ids")
    dropped_block_ids = payload.get("dropped_block_ids")
    if not isinstance(used_block_ids, list):
        used_block_ids = []
    if not isinstance(dropped_block_ids, list):
        dropped_block_ids = []
    budget = payload.get("budget")
    policy = payload.get("budget_policy") if isinstance(payload.get("budget_policy"), dict) else {}
    return {
        "version": "1.0",
        "source": str(payload.get("source") or "prompt_assembly"),
        "compacted": bool(payload.get("compacted", False)),
        "budget": budget if isinstance(budget, int) and budget > 0 else None,
        "policy": {
            "strategy": str(policy.get("strategy") or "weighted_truncation"),
            "drop_order": str(policy.get("drop_order") or "lowest_priority_compactable_last"),
            "protect": list(policy.get("protect") or []),
        },
        "used_block_ids": [str(x) for x in used_block_ids],
        "dropped_block_ids": [str(x) for x in dropped_block_ids],
        "kept_block_count": len(used_block_ids),
        "dropped_block_count": len(dropped_block_ids),
    }


def build_runtime_governance_contract() -> Dict[str, Any]:
    return {
        "status": "success",
        "governance": {
            "version": "1.1",
            "contracts": {
                "task_graph": {
                    "version": "1.0",
                    "required_fields": ["version", "status", "current_node_id", "nodes", "edges", "metadata"],
                    "node_fields": ["id", "stage", "status", "type"],
                    "edge_fields": ["from", "to", "relation"],
                },
                "orchestration": {
                    "version": "1.0",
                    "required_fields": [
                        "version",
                        "execution_core",
                        "scheduler_mode",
                        "reasoning_engine",
                        "workflow_bridge",
                    ],
                },
                "context_budget": {
                    "version": "1.0",
                    "required_fields": [
                        "version",
                        "source",
                        "compacted",
                        "budget",
                        "policy",
                        "used_block_ids",
                        "dropped_block_ids",
                        "kept_block_count",
                        "dropped_block_count",
                    ],
                },
            },
            "principles": [
                "single_contract_multi_surface",
                "runtime_first_governance",
                "backward_compatible_additive_evolution",
            ],
        },
    }
