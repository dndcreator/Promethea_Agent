import json
import re
import logging
from typing import List, Dict

logger = logging.getLogger('ToolCall')

def parse_tool_calls(content: str) -> list:
    tool_calls = []
    decoder = json.JSONDecoder()
    pos = 0
    
    while True:
        # 查找下一个可能的 JSON 起始点 '{'
        # 兼容中文全角大括号 '｛'
        start_idx = -1
        idx1 = content.find('{', pos)
        idx2 = content.find('｛', pos)
        
        if idx1 != -1 and idx2 != -1:
            start_idx = min(idx1, idx2)
        elif idx1 != -1:
            start_idx = idx1
        elif idx2 != -1:
            start_idx = idx2
            
        if start_idx == -1:
            break
            
        try:
            # 如果是全角大括号，替换为半角以便解析
            if content[start_idx] == '｛':
                # 这里比较棘手，因为直接替换会改变字符串索引
                # 我们尝试从这里开始提取一段可能的 JSON
                # 简单起见，我们假设 LLM 输出的标准 JSON 不会用全角
                # 如果遇到全角，可能需要更复杂的预处理
                # 这里暂时跳过全角起始，除非手动替换
                pos = start_idx + 1
                continue

            # 尝试解析 JSON 对象（支持嵌套大括号）
            tool_args, end_idx = decoder.raw_decode(content, start_idx)
            pos = start_idx + end_idx # 移动指针
            
            # 验证解析出的对象是否是工具调用
            if isinstance(tool_args, dict):
                _process_single_tool_call(tool_args, tool_calls)
            else:
                # 解析成功但不是字典，继续向后查找
                pos = start_idx + 1
                
        except json.JSONDecodeError:
            # 如果解析失败，说明这个 '{' 不是有效的 JSON 起始，移动 1 位继续尝试
            pos = start_idx + 1
            
    return tool_calls

def _process_single_tool_call(tool_args: dict, tool_calls: list):
    """处理单个工具调用字典"""
    try:
        agent_type = tool_args.get('agentType', 'mcp').lower()
        if agent_type == 'agent':
            agent_name = tool_args.get('agent_name')
            prompt = tool_args.get('prompt')
            if agent_name and prompt:
                tool_call = {
                    'name': 'agent_call',
                    'args': {
                        'agentType': 'agent',
                        'agent_name': agent_name,
                        'prompt': prompt
                    }
                }
                tool_calls.append(tool_call)
        else:
            tool_name = tool_args.get('tool_name')
            if tool_name:
                if 'service_name' in tool_args:
                    tool_call = {
                        'name': tool_name,
                        'args': tool_args
                    }
                    tool_calls.append(tool_call)
                else:
                    service_name = tool_name
                    tool_args['service_name'] = service_name
                    tool_args['agentType'] = 'mcp'
                    tool_call = {
                        'name': tool_name,
                        'args': tool_args
                    }
                    tool_calls.append(tool_call)
    except Exception as e:
        logger.warning(f"处理工具调用参数失败: {e}")

async def execute_tool_calls(tool_calls: list, mcp_manager) -> str:

    results = []
    for i, tool_call in enumerate(tool_calls):
        try:
            logger.debug(f"开始执行工具调用{i+1}: {tool_call['name']}")
            tool_name = tool_call['name']
            args = tool_call['args']
            agent_type = args.get('agentType', 'mcp').lower()
            logger.debug(f"工具类型: {agent_type}, 参数: {args}")

            if agent_type == 'agent':
                try:
                    from agentkit.mcp.agent_manager import get_agent_manager
                    agent_manager = get_agent_manager()
                    agent_name = args.get('agent_name')
                    prompt = args.get('prompt')
                    logger.debug(f"Agent调用: {agent_name}, prompt: {prompt}")

                    if not agent_name or not prompt:
                        result = "Agent调用失败: 缺少agent_name或prompt参数"
                    else:
                        result = await agent_manager.call_agent(agent_name, prompt)
                        if result.get("status") == "success":
                            result = result.get("result", "")
                        else:
                            result = f"Agent调用失败: {result.get('error', '未知错误')}"
                except Exception as e:
                    result = f"Agent调用失败: {str(e)}"
            else:
                service_name = args.get('service_name')
                actual_tool_name = args.get('tool_name', tool_name)
                tool_args = {k: v for k, v in args.items() 
                            if k not in ['service_name', 'agentType']}

                logger.debug(f"MCP调用: service={service_name}, tool={actual_tool_name}, args={tool_args}")

                if not service_name:
                    result = "MCP调用失败: 缺少service_name参数"
                else:
                    result = await mcp_manager.unified_call(
                        service_name=service_name,
                        tool_name=actual_tool_name,
                        args=tool_args
                    )
            logger.debug(f"工具调用{i+1}执行结果: {result}")
            results.append(f"来自工具 \"{tool_name}\" 的结果:\n{result}")
        except Exception as e:
            error_result = f"执行工具 {tool_call['name']} 时发生错误：{str(e)}"
            logger.debug(f"工具调用{i+1}执行异常: {error_result}")
            results.append(error_result)
    return "\n\n---\n\n".join(results)

async def tool_call_loop(messages: List[Dict], mcp_manager, llm_caller, is_streaming: bool = False, max_recursion: int = None) -> Dict:
    if max_recursion is None:
        max_recursion = 5 if is_streaming else 5
    
    recursion_depth = 0
    current_messages = messages.copy()
    current_ai_content = ''
    final_logprobs = None
    final_usage = {'prompt_tokens': 0, 'completion_tokens': 0}

    while recursion_depth < max_recursion:
        try:
            resp = await llm_caller(current_messages)
            current_ai_content = resp.get('content', '')
            
            # 累积usage
            usage = resp.get('usage', {})
            if usage:
                final_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                final_usage['completion_tokens'] += usage.get('completion_tokens', 0)
            
            # 保留第一次的logprobs（最重要）
            if final_logprobs is None and resp.get('logprobs'):
                final_logprobs = resp.get('logprobs')

            logger.debug(f"第{recursion_depth + 1}轮LLM回复:")
            logger.debug(f"回复内容: {current_ai_content}")

            tool_calls = parse_tool_calls(current_ai_content)
            logger.debug(f"解析到工具调用数量: {len(tool_calls)}")

            if not tool_calls:
                logger.debug(f"无工具调用，退出循环")
                break
            
            for i, tool_call in enumerate(tool_calls):
                logger.debug(f"工具调用{i+1}: {tool_call}")

            tool_results = await execute_tool_calls(tool_calls, mcp_manager)

            # 将工具结果作为新的用户消息（Observation）添加到历史中，让 LLM 继续处理
            current_messages.append({'role': 'assistant', 'content': current_ai_content})
            current_messages.append({'role': 'user', 'content': f"工具调用结果:\n{tool_results}\n请根据以上结果回答用户的问题。"})
            recursion_depth += 1
            
        except Exception as e:
            logger.error(f"工具调用循环错误: {e}")
            break
            
    # 如果因为达到最大递归深度而退出，尝试生成一个最终总结
    if recursion_depth >= max_recursion:
        try:
            logger.warning(f"达到最大递归深度 {max_recursion}，强制生成最终回答")
            # 只有当最后一条消息不是 AI 的总结时才追加提示（避免重复）
            current_messages.append({'role': 'system', 'content': "系统提示：任务执行步骤已达上限。请忽略未完成的步骤，根据目前已获得的信息，立即给用户一个最终回答。"})
            
            resp = await llm_caller(current_messages)
            final_answer = resp.get('content', '')
            
            # 如果成功生成了非空的最终回答，覆盖当前的中间状态
            if final_answer:
                current_ai_content = final_answer
                current_messages.append({'role': 'assistant', 'content': final_answer})
            
            # 累积最后一次 usage
            usage = resp.get('usage', {})
            if usage:
                final_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                final_usage['completion_tokens'] += usage.get('completion_tokens', 0)
                
        except Exception as e:
            logger.error(f"强制终止生成失败: {e}")
        
    return {
        'content': current_ai_content,
        'recursion_depth': recursion_depth,
        'messages': current_messages,
        'logprobs': final_logprobs,
        'usage': final_usage if final_usage['prompt_tokens'] > 0 else None
    }