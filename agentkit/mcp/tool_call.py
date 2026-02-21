import json
import re
from typing import List, Dict, Any, Tuple, Optional, Set, Callable, Awaitable
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
        # Also tolerate full-width brace variants.
        start_idx = -1
        idx1 = content.find('{', pos)
        idx2 = content.find("\uFF5B", pos)
        
        if idx1 != -1 and idx2 != -1:
            start_idx = min(idx1, idx2)
        elif idx1 != -1:
            start_idx = idx1
        elif idx2 != -1:
            start_idx = idx2
            
        if start_idx == -1:
            break
            
        try:
            # If it's a full-width brace, skip/normalize so we can parse
            if content[start_idx] == "\uFF5B":
                pos = start_idx + 1
                continue

            # Try to decode a JSON object starting at this position
            tool_args, end_idx = decoder.raw_decode(content, start_idx)
            pos = start_idx + end_idx  # Advance parser position.
            
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
        logger.warning(f"Failed to process tool call arguments: {e}")

async def execute_tool_calls(
    tool_calls: list,
    mcp_manager,
    session_id: str = None,
    approved_call_ids: Set[str] = None,
    tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None,
) -> List[Dict[str, Any]]:
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
            logger.warning(f"Tool {tool_name} (ID: {tool_call['id']}) requires user confirmation")
            # Raise an exception to interrupt execution and carry all pending tool calls
            raise ToolConfirmationRequired(tool_call['id'], tool_name, args, all_tool_calls=tool_calls)

    tasks = []

    # 2. Create all async tasks
    for i, tool_call in enumerate(tool_calls):
        tasks.append(
            _execute_single_tool(i, tool_call, mcp_manager, tool_executor=tool_executor)
        )
    
    if not tasks:
        return []

    # 3. Wait for all tasks in parallel
    results = await asyncio.gather(*tasks)
    
    # 4. Flatten results (each tool may return multiple blocks such as text + image)
    flat_results = []
    for res_blocks in results:
        flat_results.extend(res_blocks)
        
    return flat_results

async def _execute_single_tool(
    index: int,
    tool_call: dict,
    mcp_manager,
    tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Execute a single tool call.

    Returns:
        List[Dict]: OpenAI-style content blocks.
    """
    content_blocks = []
    
    try:
        logger.debug(f"Starting tool call {index+1}: {tool_call['name']}")
        tool_name = tool_call['name']
        args = tool_call['args']
        agent_type = args.get('agentType', 'mcp').lower()
        
        result_data = None
        error_msg = None

        if tool_executor is not None:
            result_data = await tool_executor(tool_name, args)
        elif agent_type == 'agent':
            try:
                from agentkit.mcp.agent_manager import get_agent_manager
                agent_manager = get_agent_manager()
                agent_name = args.get('agent_name')
                prompt = args.get('prompt')

                if not agent_name or not prompt:
                    error_msg = "Agent call failed: missing agent_name or prompt parameter"
                else:
                    call_result = await agent_manager.call_agent(agent_name, prompt)
                    if call_result.get("status") == "success":
                        result_data = call_result.get("result", "")
                    else:
                        error_msg = f"Agent call failed: {call_result.get('error', 'unknown error')}"
            except Exception as e:
                error_msg = f"Agent call failed: {str(e)}"
        else:
            service_name = args.get('service_name')
            actual_tool_name = args.get('tool_name', tool_name)
            tool_args = {k: v for k, v in args.items() 
                        if k not in ['service_name', 'agentType']}

            if not service_name:
                error_msg = "MCP call failed: missing service_name parameter"
            else:
                result_data = await mcp_manager.unified_call(
                    service_name=service_name,
                    tool_name=actual_tool_name,
                    args=tool_args
                )
        
        # Format result header text
        header_text = f"Result from tool \"{tool_name}\""
        
        if error_msg:
            content_blocks.append({"type": "text", "text": f"{header_text}\n[Error] {error_msg}"})
        else:
            # If result_data is a string, heuristically try to parse JSON (some tools return JSON strings).
            if isinstance(result_data, str):
                try:
                    # Some tools return JSON as a string; parse when possible.
                    if result_data.strip().startswith('{'):
                        result_data = json.loads(result_data)
                except:
                    pass

            text_output = ""
            images = []
            
            if isinstance(result_data, dict):
                # Extract screenshots/images
                if 'screenshot' in result_data and result_data['screenshot']:
                    images.append(result_data['screenshot'])
                    # Remove large base64 blobs from text output to keep it readable.
                    result_data['screenshot'] = "<image_base64_hidden>"
                
                if 'base64' in result_data and result_data['base64']:
                    images.append(result_data['base64'])
                    result_data['base64'] = "<image_base64_hidden>"
                
                # Convert remaining structure to pretty-printed JSON text.
                text_output = json.dumps(result_data, ensure_ascii=False, indent=2)
            else:
                text_output = str(result_data)
            
            # Build text block
            content_blocks.append({"type": "text", "text": f"{header_text}\n{text_output}"})
            
            for img_b64 in images:
                # Ensure base64 prefix is correct; assume PNG by default.
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }
                })

        logger.debug(f"Tool call {index+1} completed")
        return content_blocks
        
    except Exception as e:
        error_result = f"Error executing tool {tool_call['name']}: {str(e)}"
        logger.error(error_result)
        return [{"type": "text", "text": error_result}]

async def tool_call_loop(
    messages: List[Dict],
    mcp_manager,
    llm_caller,
    is_streaming: bool = False,
    max_recursion: int = None,
    session_id: str = None,
    tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None,
) -> Dict:
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

            # Aggregate usage across recursive LLM turns.
            usage = resp.get('usage', {})
            if usage:
                final_usage['prompt_tokens'] += usage.get('prompt_tokens', 0)
                final_usage['completion_tokens'] += usage.get('completion_tokens', 0)

            logger.debug(f"LLM turn {recursion_depth + 1}: {current_ai_content[:100]}...")

            tool_calls = parse_tool_calls(current_ai_content)
            
            if not tool_calls:
                logger.debug("No tool call detected, exiting loop")
                break
            
            logger.debug(f"Parsed {len(tool_calls)} tool calls")

            try:
                # Execute tools and get multimodal result blocks.
                # Pass session_id so state can be recorded when needed (even though we mostly rely on exceptions).
                tool_result_blocks = await execute_tool_calls(
                    tool_calls,
                    mcp_manager,
                    session_id,
                    tool_executor=tool_executor,
                )
            except ToolConfirmationRequired as e:
                # Capture confirmation requests and return a special status
                logger.info(f"Tool requires user confirmation: {e.tool_name} (ID: {e.tool_call_id})")
                
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
                "text": "\nPlease continue based on the tool results above (may include screenshot data).",
            })

            current_messages.append(observation_message)
            recursion_depth += 1
            
        except Exception as e:
            logger.error(f"Tool-call loop error: {e}")
            import traceback
            traceback.print_exc()
            break
            
    # If we exit because we reached the max recursion depth, try to produce a final answer
    if recursion_depth >= max_recursion:
        try:
            logger.warning(f"Reached max recursion depth {max_recursion}, forcing final answer")
            current_messages.append({"role": "system", "content": "System: step limit reached. Ignore unfinished internal steps and provide a final answer now."})
            
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
            logger.error(f"Failed to force final generation: {e}")
        
    return {
        'status': 'success',
        'content': current_ai_content,
        'recursion_depth': recursion_depth,
        'messages': current_messages,
        'usage': final_usage if final_usage['prompt_tokens'] > 0 else None
    }
