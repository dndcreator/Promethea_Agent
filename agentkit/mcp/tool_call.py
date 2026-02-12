import json
import re
from typing import List, Dict, Any, Tuple, Optional, Set
from loguru import logger
import asyncio
import uuid
from agentkit.security.policy import global_policy

class ToolConfirmationRequired(Exception):
    def __init__(self, tool_call_id: str, tool_name: str, args: dict, all_tool_calls: list):
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.args = args
        self.all_tool_calls = all_tool_calls

def parse_tool_calls(content: str) -> list:
    tool_calls = []
    decoder = json.JSONDecoder()
    pos = 0
    
    while True:
        # Find the next potential JSON object start '{'
        # Also tolerate full-width Chinese brace '｛'
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
            # If it's a full-width brace, skip/normalise so we can parse
            if content[start_idx] == '｛':
                pos = start_idx + 1
                continue

            # Try to decode a JSON object starting at this position
            tool_args, end_idx = decoder.raw_decode(content, start_idx)
            pos = start_idx + end_idx # 移动指针
            
            # Validate whether the parsed object looks like a tool call
            if isinstance(tool_args, dict):
                _process_single_tool_call(tool_args, tool_calls)
            else:
                pos = start_idx + 1
                
        except json.JSONDecodeError:
            pos = start_idx + 1
            
    return tool_calls

def _process_single_tool_call(tool_args: dict, tool_calls: list):
    """Process a single tool-call dictionary and append to the list if valid."""
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

async def execute_tool_calls(tool_calls: list, mcp_manager, session_id: str = None, approved_call_ids: Set[str] = None) -> List[Dict[str, Any]]:
    """
    Execute all tool calls concurrently.

    Returns a flat list of content blocks; each block may be text or image data.
    """
    if approved_call_ids is None:
        approved_call_ids = set()

    # 0. Pre-process: ensure every tool call has a unique ID
    for tool_call in tool_calls:
        if 'id' not in tool_call:
            tool_call['id'] = str(uuid.uuid4())

    # 1. Security check: scan all tool calls
    for tool_call in tool_calls:
        # Skip checks for calls that were already approved
        if tool_call['id'] in approved_call_ids:
            continue

        tool_name = tool_call['name']
        args = tool_call['args']
        
        # Check whether user confirmation is required
        if global_policy.requires_confirmation(tool_name, args):
            logger.warning(f"工具 {tool_name} (ID: {tool_call['id']}) 需要用户确认")
            # Raise an exception to interrupt execution and carry all pending tool calls
            raise ToolConfirmationRequired(tool_call['id'], tool_name, args, all_tool_calls=tool_calls)

    tasks = []

    # 2. Create all async tasks
    for i, tool_call in enumerate(tool_calls):
        tasks.append(_execute_single_tool(i, tool_call, mcp_manager))
    
    if not tasks:
        return []

    # 3. Wait for all tasks in parallel
    results = await asyncio.gather(*tasks)
    
    # 4. Flatten results (each tool may return multiple blocks such as text + image)
    flat_results = []
    for res_blocks in results:
        flat_results.extend(res_blocks)
        
    return flat_results

async def _execute_single_tool(index: int, tool_call: dict, mcp_manager) -> List[Dict[str, Any]]:
    """
    Execute a single tool call.

    Returns:
        List[Dict]: OpenAI-style content blocks.
    """
    content_blocks = []
    
    try:
        logger.debug(f"开始执行工具调用{index+1}: {tool_call['name']}")
        tool_name = tool_call['name']
        args = tool_call['args']
        agent_type = args.get('agentType', 'mcp').lower()
        
        result_data = None
        error_msg = None

        if agent_type == 'agent':
            try:
                from agentkit.mcp.agent_manager import get_agent_manager
                agent_manager = get_agent_manager()
                agent_name = args.get('agent_name')
                prompt = args.get('prompt')

                if not agent_name or not prompt:
                    error_msg = "Agent调用失败: 缺少agent_name或prompt参数"
                else:
                    call_result = await agent_manager.call_agent(agent_name, prompt)
                    if call_result.get("status") == "success":
                        result_data = call_result.get("result", "")
                    else:
                        error_msg = f"Agent调用失败: {call_result.get('error', '未知错误')}"
            except Exception as e:
                error_msg = f"Agent调用失败: {str(e)}"
        else:
            service_name = args.get('service_name')
            actual_tool_name = args.get('tool_name', tool_name)
            tool_args = {k: v for k, v in args.items() 
                        if k not in ['service_name', 'agentType']}

            if not service_name:
                error_msg = "MCP调用失败: 缺少service_name参数"
            else:
                result_data = await mcp_manager.unified_call(
                    service_name=service_name,
                    tool_name=actual_tool_name,
                    args=tool_args
                )
        
        # 处理结果
        header_text = f"来自工具 \"{tool_name}\" 的结果:"
        
        if error_msg:
            content_blocks.append({"type": "text", "text": f"{header_text}\n[Error] {error_msg}"})
        else:
            # 检查是否有 Vision 数据 (Base64 图片)
            # 假设 result_data 是 dict 且包含 screenshot/base64 字段
            # 或者 result_data 已经是 dict
            
            # 如果是字符串，尝试解析为 JSON (有些工具可能返回 JSON 字符串)
            if isinstance(result_data, str):
                try:
                    # 只有当它看起来像 JSON 时才解析
                    if result_data.strip().startswith('{'):
                        result_data = json.loads(result_data)
                except:
                    pass

            text_output = ""
            images = []
            
            if isinstance(result_data, dict):
                # 提取图片
                if 'screenshot' in result_data and result_data['screenshot']:
                    images.append(result_data['screenshot'])
                    # 从文本输出中移除巨大的 base64 字符串，避免污染上下文
                    result_data['screenshot'] = "<image_base64_hidden>"
                
                if 'base64' in result_data and result_data['base64']:
                    images.append(result_data['base64'])
                    result_data['base64'] = "<image_base64_hidden>"
                
                # 剩余部分转为文本
                text_output = json.dumps(result_data, ensure_ascii=False, indent=2)
            else:
                text_output = str(result_data)
            
            # 构建块
            content_blocks.append({"type": "text", "text": f"{header_text}\n{text_output}"})
            
            for img_b64 in images:
                # 确保 base64 前缀正确
                # 这里假设是 png，通常工具会返回格式，或者默认为 png
                # OpenAI 格式: data:image/png;base64,...
                # 但 openai api 的 image_url 字段只需要 url 属性
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }
                })

        logger.debug(f"工具调用{index+1}完成")
        return content_blocks
        
    except Exception as e:
        error_result = f"执行工具 {tool_call['name']} 时发生错误：{str(e)}"
        logger.error(error_result)
        return [{"type": "text", "text": error_result}]

async def tool_call_loop(messages: List[Dict], mcp_manager, llm_caller, is_streaming: bool = False, max_recursion: int = None, session_id: str = None) -> Dict:
    if max_recursion is None:
        max_recursion = 5 if is_streaming else 5
    
    recursion_depth = 0
    current_messages = messages.copy()
    current_ai_content = ''
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

            logger.debug(f"第{recursion_depth + 1}轮LLM回复: {current_ai_content[:100]}...")

            tool_calls = parse_tool_calls(current_ai_content)
            
            if not tool_calls:
                logger.debug(f"无工具调用，退出循环")
                break
            
            logger.debug(f"解析到 {len(tool_calls)} 个工具调用")

            try:
                # Execute tools and get multimodal result blocks.
                # Pass session_id so state can be recorded when needed (even though we mostly rely on exceptions).
                tool_result_blocks = await execute_tool_calls(tool_calls, mcp_manager, session_id)
            except ToolConfirmationRequired as e:
                # Capture confirmation requests and return a special status
                logger.info(f"中断执行，等待用户确认工具: {e.tool_name} (ID: {e.tool_call_id})")
                
                return {
                    'status': 'needs_confirmation',
                    'tool_call_id': e.tool_call_id,
                    'tool_name': e.tool_name,
                    'args': e.args,
                    'current_messages': current_messages, # Save current conversation state
                    'pending_tool_calls': e.all_tool_calls, # Save the full batch of pending tool calls
                    'content': current_ai_content          # Save the AI reply content
                }

            current_messages.append({'role': 'assistant', 'content': current_ai_content})
            
            # Build a new user message (Observation) that includes
            # both textual results and any images.
            observation_message = {
                'role': 'user',
                'content': tool_result_blocks
            }
            
            # Append a prompt to guide the model to continue
            tool_result_blocks.append({
                "type": "text", 
                "text": "\n请根据以上工具执行结果（可能包含截图），回答用户的问题或进行下一步操作。"
            })

            current_messages.append(observation_message)
            recursion_depth += 1
            
        except Exception as e:
            logger.error(f"工具调用循环错误: {e}")
            import traceback
            traceback.print_exc()
            break
            
    # If we exit because we reached the max recursion depth, try to produce a final answer
    if recursion_depth >= max_recursion:
        try:
            logger.warning(f"达到最大递归深度 {max_recursion}，强制生成最终回答")
            current_messages.append({'role': 'system', 'content': "系统提示：任务执行步骤已达上限。请忽略未完成的步骤，根据目前已获得的信息，立即给用户一个最终回答。"})
            
            resp = await llm_caller(current_messages)
            final_answer = resp.get('content', '')
            
            if final_answer:
                current_ai_content = final_answer
                current_messages.append({'role': 'assistant', 'content': final_answer})
            
            usage = resp.get('usage', {})
            if usage:
                final_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                final_usage['completion_tokens'] += usage.get('completion_tokens', 0)
                
        except Exception as e:
            logger.error(f"强制终止生成失败: {e}")
        
    return {
        'status': 'success',
        'content': current_ai_content,
        'recursion_depth': recursion_depth,
        'messages': current_messages,
        'usage': final_usage if final_usage['prompt_tokens'] > 0 else None
    }
