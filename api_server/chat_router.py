from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sys
import os
import asyncio
import queue
import json
import time
import logging
from typing import Optional, List, Dict

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_core import PrometheaConversation
from config import config, AI_NAME
from .message_manager import message_manager
from .metrics import get_metrics_collector
from agentkit.mcp.tool_call import tool_call_loop, execute_tool_calls
from agentkit.mcp.mcp_manager import MCPManager
from agentkit.mcp.streaming_tool_call import StreamingToolCallProcessor

router = APIRouter()
metrics = get_metrics_collector()
logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
    status: str = "success"

class FollowUpRequest(BaseModel):
    # 用户手动选中的文本
    selected_text: str
    query_type: str  # why/risk/alternative/custom
    custom_query: Optional[str] = None  # 自定义追问
    session_id: str
    context: Optional[List[Dict]] = None  # 最近几轮对话上下文



# 全局对话实例
conversation = PrometheaConversation()
mcp_manager = MCPManager()

async def stream_chat_response(messages: List[Dict], session_id: str, user_message: str):
    """流式聊天响应生成器，支持工具调用"""
    # 使用 asyncio.Queue 替代同步 Queue，避免阻塞 event loop
    tool_calls_queue = asyncio.Queue()
    text_output_queue = asyncio.Queue()
    
    # 创建流式处理器
    processor = StreamingToolCallProcessor(mcp_manager)
    
    # 定义回调函数
    async def on_text_chunk(text: str, chunk_type: str):
        """文本块回调 - 发送给前端"""
        await text_output_queue.put(json.dumps({
            "type": "text",
            "content": text,
            "session_id": session_id
        }) + "\n")
        return None
    
    async def on_sentence(sentence: str, sentence_type: str):
        """完整句子回调（可用于语音等）"""
        pass
    
    async def on_tool_result(result: str):
        """工具调用结果回调"""
        pass
    
    def tool_call_detected_signal(msg: str):
        """工具调用检测信号"""
        pass
    
    # 启动后台工具调用消费任务
    tool_consumer_task = asyncio.create_task(
        consume_tool_calls(tool_calls_queue, session_id)
    )
    
    # 用于收集完整响应文本
    full_response_text = []
    
    # 修改文本块回调以收集完整文本
    original_on_text_chunk = on_text_chunk
    async def on_text_chunk_with_collection(text: str, chunk_type: str):
        full_response_text.append(text)
        return await original_on_text_chunk(text, chunk_type)
    
    # 启动流式处理任务
    async def process_stream():
        try:
            await processor.process_ai_response(
                conversation.call_llm_stream(messages),
                callbacks={
                    "on_text_chunk": on_text_chunk_with_collection,
                    "on_sentence": on_sentence,
                    "on_tool_result": on_tool_result,
                    "tool_calls_queue": tool_calls_queue,
                    "tool_call_detected_signal": tool_call_detected_signal
                }
            )
            # 等待工具调用队列消费完成
            await tool_calls_queue.put(None)  # 结束信号
            await tool_consumer_task
            
            # 发送完成信号
            await text_output_queue.put(json.dumps({
                "type": "done",
                "session_id": session_id,
                "status": "success"
            }) + "\n")
        except Exception as e:
            await text_output_queue.put(json.dumps({
                "type": "error",
                "content": f"流式处理错误: {str(e)}",
                "session_id": session_id
            }) + "\n")
        finally:
            # 结束信号
            await text_output_queue.put(None)
    
    # 启动处理任务
    process_task = asyncio.create_task(process_stream())
    
    try:
        # 持续从输出队列获取并yield数据
        while True:
            chunk = await text_output_queue.get()
            if chunk is None:
                break
            yield chunk
        
        # 保存历史
        final_response = processor.get_response_buffer()
        message_manager.add_message(session_id, "user", user_message)
        message_manager.add_message(session_id, "assistant", final_response)
        try:
            conversation.save_log(user_message, final_response)
        except Exception as e:
            logger.warning(f"写入对话日志失败: {e}")
        
        # 自动触发记忆层处理（后台任务，不阻塞）
        asyncio.create_task(auto_trigger_memory_layers(session_id))
        
    finally:
        # 确保后台任务清理
        if not process_task.done():
            process_task.cancel()
        if not tool_consumer_task.done():
            tool_consumer_task.cancel()

async def consume_tool_calls(tool_calls_queue: asyncio.Queue, session_id: str):
    """后台消费工具调用队列"""
    while True:
        try:
            # 异步等待，无需轮询
            tool_call = await tool_calls_queue.get()
            
            # None 是结束信号
            if tool_call is None:
                break
            
            # 执行工具调用
            result = await execute_tool_calls([tool_call], mcp_manager)
            print(f"[STREAM] 工具调用结果: {result}")
            
        except Exception as e:
            print(f"[STREAM] 工具调用消费错误: {e}")
            break


async def auto_trigger_memory_layers(session_id: str):
    """自动触发温层、冷层和遗忘处理（后台任务）"""
    try:
        from memory import create_warm_layer_manager, create_cold_layer_manager, create_forgetting_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter or not memory_adapter.is_enabled():
            return
        
        connector = memory_adapter.hot_layer.connector
        
        # 获取会话消息数量
        count_query = """
        MATCH (s:Session {id: $session_id})<-[:PART_OF_SESSION]-(m:Message)
        WHERE m.layer = 0
        RETURN count(m) as count
        """
        result = connector.query(count_query, {"session_id": f"session_{session_id}"})
        message_count = result[0]['count'] if result else 0
        
        logger.info(f"会话 {session_id} 当前消息数: {message_count}")
        
        # 自动触发温层（每 10 条消息）
        if message_count > 0 and message_count % 10 == 0:
            try:
                from config import load_config
                config = load_config()
                
                if config.memory.warm_layer.enabled:
                    warm_layer = create_warm_layer_manager(connector)
                    if warm_layer:
                        # WarmLayerManager.cluster_entities 是同步方法，这里不要 await
                        concepts_created = warm_layer.cluster_entities(session_id)
                        logger.info(f"✅ 温层自动聚类完成，创建了 {concepts_created} 个概念")
            except Exception as e:
                logger.exception(f"温层自动触发失败: {e}")
        
        # 自动触发冷层（达到阈值时）
        try:
            from config import load_config
            config = load_config()
            
            cold_layer = create_cold_layer_manager(connector)
            if cold_layer and cold_layer.should_create_summary(session_id):
                summary_id = cold_layer.create_incremental_summary(session_id)
                if summary_id:
                    logger.info(f"✅ 冷层自动摘要完成: {summary_id}")
        except Exception as e:
            logger.exception(f"冷层自动触发失败: {e}")
        
        # 自动应用时间衰减（每50条消息）
        if message_count > 0 and message_count % 50 == 0:
            try:
                forgetting_manager = create_forgetting_manager(connector)
                result = forgetting_manager.apply_time_decay(session_id)
                logger.info(f"✅ 时间衰减完成: {result.get('updated_count', 0)} 个节点")
            except Exception as e:
                logger.warning(f"时间衰减失败: {e}")
        
        # 自动清理遗忘节点（每100条消息）
        if message_count > 0 and message_count % 100 == 0:
            try:
                forgetting_manager = create_forgetting_manager(connector)
                result = forgetting_manager.cleanup_forgotten(session_id)
                logger.info(f"✅ 清理遗忘节点: {result.get('deleted_count', 0)} 个节点")
            except Exception as e:
                logger.warning(f"清理遗忘节点失败: {e}")
            
    except Exception as e:
        logger.exception(f"自动触发记忆层失败: {e}")

@router.post("/chat")
async def chat(request: ChatRequest):
    """聊天接口（支持流式和非流式）"""
    try:
        # 1) 复用或创建会话ID
        if request.session_id and message_manager.get_session(request.session_id):
            session_id = request.session_id
        else:
            session_id = message_manager.create_session()
            metrics.record_session()

        # 2) 自动召回长期记忆
        memory_context = ""
        try:
            from memory.adapter import get_memory_adapter
            memory_adapter = get_memory_adapter()
            if memory_adapter.is_enabled():
                recall_start = time.time()
                memory_context = memory_adapter.get_context(request.message, session_id)
                metrics.record_memory_recall(time.time() - recall_start)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"记忆召回失败: {e}")
        
        # 3) 构建上下文（系统提示词 + 记忆上下文 + 历史 + 当前用户消息）
        system_prompt = getattr(config.prompts, "Promethea_system_prompt", "")
        if memory_context:
            system_prompt += f"\n\n{memory_context}"
        
        messages: List[Dict] = message_manager.build_conversation(
            session_id=session_id,
            system_prompt=system_prompt,
            current_message=request.message,
            include_history=True,
        )

        # 3) 根据stream参数选择处理方式
        if request.stream:
            # 流式响应
            return StreamingResponse(
                stream_chat_response(messages, session_id, request.message),
                media_type="text/event-stream"
            )
        else:
            # 非流式响应
            async def llm_caller(messages):
                return await conversation.call_llm(messages)
            
            llm_start = time.time()
            tool_call_outcome = await tool_call_loop(
                messages=messages,
                mcp_manager=mcp_manager,
                llm_caller=llm_caller,
                is_streaming=False
            )
            
            # 记录token使用情况
            usage = tool_call_outcome.get("usage", {})
            metrics.record_llm_call(
                time.time() - llm_start,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0)
            )
            
            final_content = tool_call_outcome.get("content", "")

            # 写回历史
            message_manager.add_message(session_id, "user", request.message)
            message_manager.add_message(session_id, "assistant", final_content)
            metrics.record_message()
            try:
                conversation.save_log(request.message, final_content)
            except Exception as e:
                logger.warning(f"写入对话日志失败: {e}")
            
            # 自动触发记忆层处理（后台任务，不阻塞）
            asyncio.create_task(auto_trigger_memory_layers(session_id))

            return ChatResponse(
                response=final_content, 
                session_id=session_id, 
                status="success"
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"聊天处理失败: {str(e)}")

@router.get("/status")
async def get_status():
    """获取服务状态"""
    # 检查记忆系统状态
    memory_status = False
    try:
        from memory.adapter import get_memory_adapter
        adapter = get_memory_adapter()
        memory_status = adapter.is_enabled()
    except:
        pass

    return {
        "status": "running",
        "conversation_ready": conversation is not None,
        "memory_active": memory_status
    }

@router.get("/sessions")
async def list_sessions():

    try:
        message_manager.cleanup_old_sessions()

        sessions_info = message_manager.get_all_sessions_info()

        sessions = []
        for sid, info in sessions_info.items():
            if info:
                sessions.append(info)
        sessions.sort(key=lambda x: x.get("last_activity", 0), reverse=True)

        return {
            "status": "success",
            "sessions": sessions,
            "total": len(sessions_info)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")

@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    try:
        session_info = message_manager.get_session(session_id)
        if not session_info:
            raise HTTPException(status_code=404, detail="会话不存在")
        
        messages = message_manager.get_messages(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "session_info": session_info,
            "messages": messages
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(e)}")


@router.post("/memory/cluster/{session_id}")
async def cluster_session_memory(session_id: str):
    """对会话的记忆进行聚类（温层处理）"""
    try:
        from memory import create_warm_layer_manager
        from memory.adapter import get_memory_adapter
        
        # 检查记忆系统是否启用
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        # 创建温层管理器
        warm_layer = create_warm_layer_manager(memory_adapter.hot_layer.connector)
        if not warm_layer:
            raise HTTPException(status_code=503, detail="温层管理器初始化失败")
        
        # 执行聚类
        concepts_created = warm_layer.cluster_entities(session_id)
        
        # 获取概念列表
        concepts = warm_layer.get_concepts(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "concepts_created": concepts_created,
            "total_concepts": len(concepts),
            "concepts": concepts
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"记忆聚类失败: {str(e)}")


@router.get("/memory/concepts/{session_id}")
async def get_session_concepts(session_id: str):
    """获取会话的概念列表"""
    try:
        from memory import create_warm_layer_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        warm_layer = create_warm_layer_manager(memory_adapter.hot_layer.connector)
        if not warm_layer:
            raise HTTPException(status_code=503, detail="温层管理器初始化失败")
        
        concepts = warm_layer.get_concepts(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "concepts": concepts
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取概念列表失败: {str(e)}")


# ============ 冷层 API ============

@router.post("/memory/summarize/{session_id}")
async def summarize_session(session_id: str, incremental: bool = False):
    """
    生成会话摘要（冷层处理）
    
    Args:
        session_id: 会话ID
        incremental: 是否生成增量摘要（默认 False）
    """
    try:
        from memory import create_cold_layer_manager
        from memory.adapter import get_memory_adapter
        
        # 检查记忆系统是否启用
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        # 创建冷层管理器
        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")
        
        # 检查是否需要创建摘要
        if not cold_layer.should_create_summary(session_id):
            return {
                "status": "skipped",
                "session_id": session_id,
                "message": "消息数量不足或已有最近摘要"
            }
        
        # 生成摘要
        if incremental:
            summary_id = cold_layer.create_incremental_summary(session_id)
        else:
            summary_id = cold_layer.summarize_session(session_id)
        
        if not summary_id:
            raise HTTPException(status_code=500, detail="摘要生成失败")
        
        # 获取生成的摘要
        summary = cold_layer.get_summary_by_id(summary_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "summary_id": summary_id,
            "summary": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成摘要失败: {str(e)}")


@router.get("/memory/summaries/{session_id}")
async def get_session_summaries(session_id: str):
    """获取会话的摘要列表"""
    try:
        from memory import create_cold_layer_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")
        
        summaries = cold_layer.get_summaries(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "total_summaries": len(summaries),
            "summaries": summaries
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取摘要列表失败: {str(e)}")


@router.get("/memory/summary/{summary_id}")
async def get_summary(summary_id: str):
    """获取特定摘要"""
    try:
        from memory import create_cold_layer_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        cold_layer = create_cold_layer_manager(memory_adapter.hot_layer.connector)
        if not cold_layer:
            raise HTTPException(status_code=503, detail="冷层管理器初始化失败")
        
        summary = cold_layer.get_summary_by_id(summary_id)
        
        if not summary:
            raise HTTPException(status_code=404, detail="摘要不存在")
        
        return {
            "status": "success",
            "summary": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取摘要失败: {str(e)}")


# ============ 配置管理 API ============

@router.get("/metrics")
async def get_metrics():
    """获取性能统计数据"""
    return {
        "status": "success",
        "metrics": metrics.get_stats()
    }

@router.get("/config")
async def get_config():
    """获取当前配置（可热修改的部分）"""
    try:
        from config import load_config
        config = load_config()
        
        # 只返回可热修改的配置项
        return {
            "status": "success",
            "config": {
                "api": {
                    "api_key": config.api.api_key[:20] + "..." if len(config.api.api_key) > 20 else config.api.api_key,
                    "base_url": config.api.base_url,
                    "model": config.api.model,
                    "temperature": config.api.temperature,
                    "max_tokens": config.api.max_tokens,
                    "max_history_rounds": config.api.max_history_rounds,
                },
                "system": {
                    "stream_mode": config.system.stream_mode,
                    "debug": config.system.debug,
                    "log_level": config.system.log_level,
                },
                "memory": {
                    "enabled": config.memory.enabled,
                    "neo4j": {
                        "enabled": config.memory.neo4j.enabled,
                        "uri": config.memory.neo4j.uri,
                        "username": config.memory.neo4j.username,
                        "database": config.memory.neo4j.database,
                    },
                    "warm_layer": {
                        "enabled": config.memory.warm_layer.enabled,
                        "clustering_threshold": config.memory.warm_layer.clustering_threshold,
                        "min_cluster_size": config.memory.warm_layer.min_cluster_size,
                    },
                    "cold_layer": {
                        "max_summary_length": config.memory.cold_layer.max_summary_length,
                        "compression_threshold": config.memory.cold_layer.compression_threshold,
                    }
                }
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.post("/config")
async def update_config(request: dict):
    """更新配置（热修改）"""
    try:
        import json
        from pathlib import Path
        
        config_path = Path("config.json")
        
        # 读取当前配置
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                current_config = json.load(f)
        else:
            raise HTTPException(status_code=404, detail="配置文件不存在")
        
        # 更新配置（深度合并）
        def deep_update(base_dict, update_dict):
            for key, value in update_dict.items():
                if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                    deep_update(base_dict[key], value)
                else:
                    base_dict[key] = value
        
        deep_update(current_config, request.get('config', {}))
        
        # 写回文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, indent=4, ensure_ascii=False)
        
        # 触发热重载
        from config import load_config
        global config, conversation
        config = load_config()
        
        # 重新初始化会话核心（使用新配置）
        from conversation_core import PrometheaConversation
        conversation = PrometheaConversation()
        
        logger.info("✅ 配置已更新并热重载")
        
        return {
            "status": "success",
            "message": "配置已更新并生效"
        }
        
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.get("/memory/graph/{session_id}")
async def get_memory_graph(session_id: str):
    """获取会话的完整记忆图（三层结构）"""
    try:
        from memory import create_warm_layer_manager, create_cold_layer_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            return {
                "status": "disabled",
                "nodes": [],
                "edges": [],
                "stats": {
                    "total_nodes": 0,
                    "total_edges": 0,
                    "layers": {"hot": 0, "warm": 0, "cold": 0}
                }
            }
        
        connector = memory_adapter.hot_layer.connector
        
        # 查询所有节点和关系
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
        
        # 转换为前端格式
        nodes = []
        for node in nodes_raw:
            nodes.append({
                "id": node.get('id'),
                "type": node.get('type', '').lower(),
                "content": node.get('content', ''),
                "layer": node.get('layer', 0),
                "importance": node.get('importance', 0.5),
                "access_count": node.get('access_count', 0),
                "created_at": node.get('created_at')
            })
        
        edges = []
        for edge in edges_raw:
            edges.append({
                "source": edge.get('source'),
                "target": edge.get('target'),
                "type": edge.get('type', ''),
                "weight": edge.get('weight', 1.0)
            })
        
        # 统计信息
        layer_counts = {"hot": 0, "warm": 0, "cold": 0}
        for node in nodes:
            layer = node['layer']
            if layer == 0:
                layer_counts["hot"] += 1
            elif layer == 1:
                layer_counts["warm"] += 1
            elif layer == 2:
                layer_counts["cold"] += 1
        
        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "layers": layer_counts
        }
        
        return {
            "status": "success",
            "nodes": nodes,
            "edges": edges,
            "stats": stats
        }
        
    except Exception as e:
        # 关键：即使失败也返回结构化结果，避免前端因 stats 缺失而报 “total_nodes 不存在”
        logger.error(f"获取记忆图失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"获取记忆图失败: {str(e)}",
            "nodes": [],
            "edges": [],
            "stats": {
                "total_nodes": 0,
                "total_edges": 0,
                "layers": {"hot": 0, "warm": 0, "cold": 0}
            }
        }


@router.post("/followup")
async def handle_followup(request: FollowUpRequest):
    """处理气泡追问"""
    try:
        # 快捷追问的提示词模板
        templates = {
            "why": "为什么说「{text}」？请用100字以内简短解释推理依据和前提。",
            "risk": "「{text}」有什么潜在的坑或代价？请用100字以内诚实说明。",
            "alternative": "除了「{text}」，还有什么替代方案？请用100字以内列举2-3个方案并简要对比。"
        }
        
        # 构建追问消息
        if request.query_type == "custom" and request.custom_query:
            user_query = f"{request.custom_query}\n\n相关内容：「{request.selected_text}」"
        else:
            user_query = templates.get(request.query_type, templates["why"]).format(
                text=request.selected_text[:100]  # 限制长度
            )
        
        # 构建上下文：从message_manager获取最近几轮对话
        messages = []
        
        # 获取会话历史（最近6条消息=3轮对话）
        recent_messages = message_manager.get_recent_messages(request.session_id, count=6)
        if recent_messages:
            messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in recent_messages
            ]
        
        # 追加当前追问
        messages.append({"role": "user", "content": user_query})
        
        # 调用LLM（快速配置：低temperature，短max_tokens）
        response = await conversation.call_llm(messages)
        
        return {
            "status": "success",
            "response": response.get("content", ""),
            "query": user_query
        }
        
    except Exception as e:
        logger.error(f"追问处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"追问处理失败: {str(e)}")


@router.post("/memory/decay/{session_id}")
async def apply_memory_decay(session_id: str):
    """
    应用时间衰减到指定会话的记忆
    
    Args:
        session_id: 会话ID
    """
    try:
        from memory import create_forgetting_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        result = forgetting_manager.apply_time_decay(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            **result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用记忆衰减失败: {e}")
        raise HTTPException(status_code=500, detail=f"应用记忆衰减失败: {str(e)}")


@router.post("/memory/cleanup/{session_id}")
async def cleanup_forgotten_memory(session_id: str):
    """
    清理指定会话的遗忘节点
    
    Args:
        session_id: 会话ID
    """
    try:
        from memory import create_forgetting_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        result = forgetting_manager.cleanup_forgotten(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            **result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理遗忘节点失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理遗忘节点失败: {str(e)}")


@router.get("/memory/forgetting/stats/{session_id}")
async def get_forgetting_stats(session_id: str):
    """
    获取指定会话的遗忘统计
    
    Args:
        session_id: 会话ID
    """
    try:
        from memory import create_forgetting_manager
        from memory.adapter import get_memory_adapter
        
        memory_adapter = get_memory_adapter()
        if not memory_adapter.is_enabled():
            raise HTTPException(status_code=503, detail="记忆系统未启用")
        
        forgetting_manager = create_forgetting_manager(memory_adapter.hot_layer.connector)
        stats = forgetting_manager.get_forgetting_stats(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            **stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取遗忘统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取遗忘统计失败: {str(e)}")

