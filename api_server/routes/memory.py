from __future__ import annotations

from fastapi import APIRouter, HTTPException
import logging


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/memory/cluster/{session_id}")
async def cluster_session_memory(session_id: str):
    """对会话的记忆进行聚类（温层处理）"""
    try:
        from core.services import get_memory_service
        from memory import create_warm_layer_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        warm_layer = create_warm_layer_manager(memory_adapter.hot_layer.connector)
        if not warm_layer:
            raise HTTPException(status_code=503, detail="温层管理器初始化失败")

        concepts_created = warm_layer.cluster_entities(session_id)
        concepts = warm_layer.get_concepts(session_id)

        return {
            "status": "success",
            "session_id": session_id,
            "concepts_created": concepts_created,
            "total_concepts": len(concepts),
            "concepts": concepts,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记忆聚类失败: {str(e)}")


@router.get("/memory/concepts/{session_id}")
async def get_session_concepts(session_id: str):
    """获取会话的概念列表"""
    try:
        from core.services import get_memory_service
        from memory import create_warm_layer_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        warm_layer = create_warm_layer_manager(memory_adapter.hot_layer.connector)
        if not warm_layer:
            raise HTTPException(status_code=503, detail="温层管理器初始化失败")

        concepts = warm_layer.get_concepts(session_id)

        return {"status": "success", "session_id": session_id, "concepts": concepts}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取概念列表失败: {str(e)}")


@router.post("/memory/summarize/{session_id}")
async def summarize_session(session_id: str, incremental: bool = False):
    """
    生成会话摘要（冷层处理）

    Args:
        session_id: 会话ID
        incremental: 是否生成增量摘要（默认 False）
    """
    try:
        from core.services import get_memory_service
        from memory import create_cold_layer_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")

        if not cold_layer.should_create_summary(session_id):
            return {"status": "skipped", "session_id": session_id, "message": "消息数量不足或已有最近摘要"}

        if incremental:
            summary_id = cold_layer.create_incremental_summary(session_id)
        else:
            summary_id = cold_layer.summarize_session(session_id)

        if not summary_id:
            raise HTTPException(status_code=500, detail="摘要生成失败")

        summary = cold_layer.get_summary_by_id(summary_id)

        return {"status": "success", "session_id": session_id, "summary_id": summary_id, "summary": summary}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成摘要失败: {str(e)}")


@router.get("/memory/summaries/{session_id}")
async def get_session_summaries(session_id: str):
    """获取会话的所有摘要"""
    try:
        from core.services import get_memory_service
        from memory import create_cold_layer_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")

        summaries = cold_layer.get_summaries(session_id)

        return {"status": "success", "session_id": session_id, "total_summaries": len(summaries), "summaries": summaries}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取摘要列表失败: {str(e)}")


@router.get("/memory/summary/{summary_id}")
async def get_summary(summary_id: str):
    """获取单个摘要"""
    try:
        from core.services import get_memory_service
        from memory import create_cold_layer_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")

        summary = cold_layer.get_summary_by_id(summary_id)
        if not summary:
            raise HTTPException(status_code=404, detail="摘要不存在")

        return {"status": "success", "summary": summary}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取摘要失败: {str(e)}")


@router.get("/memory/graph/{session_id}")
async def get_memory_graph(session_id: str):
    """获取会话的完整记忆图（三层结构）"""
    try:
        from core.services import get_memory_service

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            return {
                "status": "disabled",
                "nodes": [],
                "edges": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
            }

        connector = memory_adapter.hot_layer.connector

        nodes_query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n)
        RETURN n.id as id, labels(n)[0] as type, n.content as content,
               n.layer as layer, n.importance as importance,
               n.access_count as access_count, n.created_at as created_at
        ORDER BY n.created_at ASC
        """

        edges_query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(n1)
        MATCH (n1)-[r]->(n2)
        WHERE n2.id <> $session_id
        RETURN n1.id as source, n2.id as target,
               type(r) as type, r.weight as weight
        """

        session_param = {"session_id": f"session_{session_id}"}

        nodes_raw = connector.query(nodes_query, session_param)
        edges_raw = connector.query(edges_query, session_param)

        nodes = []
        for node in nodes_raw:
            nodes.append(
                {
                    "id": node.get("id"),
                    "type": (node.get("type", "") or "").lower(),
                    "content": node.get("content", ""),
                    "layer": node.get("layer", 0),
                    "importance": node.get("importance", 0.5),
                    "access_count": node.get("access_count", 0),
                    "created_at": node.get("created_at"),
                }
            )

        edges = []
        for edge in edges_raw:
            edges.append(
                {
                    "source": edge.get("source"),
                    "target": edge.get("target"),
                    "type": edge.get("type", ""),
                    "weight": edge.get("weight", 1.0),
                }
            )

        layer_counts = {"hot": 0, "warm": 0, "cold": 0}
        for node in nodes:
            layer = node["layer"]
            if layer == 0:
                layer_counts["hot"] += 1
            elif layer == 1:
                layer_counts["warm"] += 1
            elif layer == 2:
                layer_counts["cold"] += 1

        stats = {"total_nodes": len(nodes), "total_edges": len(edges), "layers": layer_counts}

        return {"status": "success", "nodes": nodes, "edges": edges, "stats": stats}

    except Exception as e:
        logger.error(f"获取记忆图失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"获取记忆图失败: {str(e)}",
            "nodes": [],
            "edges": [],
            "stats": {"total_nodes": 0, "total_edges": 0, "layers": {"hot": 0, "warm": 0, "cold": 0}},
        }


@router.post("/memory/decay/{session_id}")
async def apply_memory_decay(session_id: str):
    """应用时间衰减到指定会话的记忆"""
    try:
        from core.services import get_memory_service
        from memory import create_forgetting_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        result = forgetting_manager.apply_time_decay(session_id)

        return {"status": "success", "session_id": session_id, **result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用记忆衰减失败: {e}")
        raise HTTPException(status_code=500, detail=f"应用记忆衰减失败: {str(e)}")


@router.post("/memory/cleanup/{session_id}")
async def cleanup_forgotten_memory(session_id: str):
    """清理指定会话的遗忘节点"""
    try:
        from core.services import get_memory_service
        from memory import create_forgetting_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        result = forgetting_manager.cleanup_forgotten(session_id)

        return {"status": "success", "session_id": session_id, **result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理遗忘节点失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理遗忘节点失败: {str(e)}")


@router.get("/memory/forgetting/stats/{session_id}")
async def get_forgetting_stats(session_id: str):
    """获取指定会话的遗忘统计"""
    try:
        from core.services import get_memory_service
        from memory import create_forgetting_manager

        memory_adapter = get_memory_service()
        if not memory_adapter or not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")

        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        stats = forgetting_manager.get_forgetting_stats(session_id)

        return {"status": "success", "session_id": session_id, **stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取遗忘统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取遗忘统计失败: {str(e)}")

