import json
import re
from typing import List, Dict, Any, Tuple, Optional, Set, Callable, Awaitable
from loguru import logger
import asyncio
import uuid
from agentkit.security.policy import global_policy
from agentkit.mcp.action_protocol import (
    ACTION_MODE_CONTRACT_MARKER,
    build_observation_gate,
    build_protocol_correction,
    iter_json_objects,
    parse_action_envelope,
)

class ToolConfirmationRequired(Exception):
    def __init__(self, tool_call_id: str, tool_name: str, args: dict, all_tool_calls: list):
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        # Do not assign payload to BaseException.args because CPython coerces
        # it to a tuple, which breaks downstream schema validation expecting dict.
        self.tool_args = args
        self.all_tool_calls = all_tool_calls


def _tool_blocks_failed(blocks: List[Dict[str, Any]]) -> bool:
    text = "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text.strip():
        return False
    markers = [
        "[Error]",
        "Error executing tool",
        "Call failed:",
        "HTTP Error",
        "Forbidden",
        "Tool call returned HTTP",
        "tool verification failed",
    ]
    return any(marker in text for marker in markers)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    return str(value)


def _build_lightweight_react_gate(
    *,
    tool_result_blocks: List[Dict[str, Any]],
    remaining_steps: int,
) -> str:
    failed = _tool_blocks_failed(tool_result_blocks)
    return build_observation_gate(failed=failed, remaining_steps=remaining_steps)


def _is_action_mode(messages: List[Dict]) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "system":
            continue
        if ACTION_MODE_CONTRACT_MARKER in str(message.get("content") or ""):
            return True
    return False


def _extract_action_answer(content: str) -> Optional[str]:
    envelope = parse_action_envelope(content or "")
    if envelope and envelope.action == "answer":
        return str(envelope.content or "")
    return None


def parse_tool_calls(content: str) -> list:
    tool_calls = []
    for obj in iter_json_objects(content or ""):
        # Validate whether the parsed object looks like a tool call
        if isinstance(obj, dict):
            _process_single_tool_call(obj, tool_calls)
    return tool_calls

def _process_single_tool_call(tool_args: dict, tool_calls: list):
    """Process a single tool-call dictionary and append to the list if valid."""
    try:
        action = str(tool_args.get("action") or "").lower()
        if action and action != "tool_call":
            return

        agent_type = str(tool_args.get("agentType", "mcp")).lower()
        if agent_type == "agent":
            agent_name = tool_args.get("agent_name")
            prompt = tool_args.get("prompt")
            if agent_name and prompt:
                tool_call = {
                    "name": "agent_call",
                    "args": {
                        "agentType": "agent",
                        "agent_name": agent_name,
                        "prompt": prompt,
                    },
                }
                tool_calls.append(tool_call)
            return

        tool_name = tool_args.get("tool_name")
        if not tool_name:
            return

        nested_args = tool_args.get("args")
        effective_args = {}
        if isinstance(nested_args, dict):
            effective_args.update(nested_args)
        for k, v in tool_args.items():
            if k in {"args", "action"}:
                continue
            # Preserve nested call semantics. The outer tool_name may be a
            # service id such as content_tools while args.tool_name is the
            # concrete action such as web_fetch.
            if k in {"tool_name", "service_name"} and k in effective_args:
                continue
            effective_args[k] = v

        if "service_name" not in effective_args:
            effective_args["service_name"] = str(tool_name).split(".", 1)[0]
        if "agentType" not in effective_args:
            effective_args["agentType"] = "mcp"

        tool_call = {"name": tool_name, "args": effective_args}
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
                except Exception as e:
                    logger.debug("tool_call: failed to parse string result as JSON: {}", e)

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
                text_output = json.dumps(_json_safe(result_data), ensure_ascii=False, indent=2)
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
    action_mode = _is_action_mode(current_messages)
    action_protocol_retry_used = False

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

            action_answer = _extract_action_answer(current_ai_content) if action_mode else None
            if action_answer is not None:
                current_ai_content = action_answer
                logger.debug("Action loop received structured answer action, exiting loop")
                break

            tool_calls = parse_tool_calls(current_ai_content)
            
            if not tool_calls:
                if action_mode and recursion_depth == 0 and not action_protocol_retry_used:
                    logger.warning("Action loop received invalid first action response; requesting structured action object")
                    current_messages.append({'role': 'assistant', 'content': current_ai_content})
                    current_messages.append({'role': 'user', 'content': build_protocol_correction()})
                    action_protocol_retry_used = True
                    continue
                if action_mode and recursion_depth == 0 and action_protocol_retry_used:
                    logger.warning("Action loop failed closed after invalid structured action retry")
                    current_ai_content = (
                        "I could not start a verified tool-backed action because the model did not return "
                        "a valid action object after correction. Please retry the request."
                    )
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
                    'args': e.tool_args,
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
            
            # Append a prompt to guide the model through the lightweight ReAct
            # verification step without starting the full reasoning tree.
            remaining_steps = max(0, int(max_recursion) - recursion_depth - 1)
            continuation_text = _build_lightweight_react_gate(
                tool_result_blocks=tool_result_blocks,
                remaining_steps=remaining_steps,
            )
            tool_result_blocks.append({
                "type": "text",
                "text": continuation_text,
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
            if action_mode:
                current_messages.append({"role": "system", "content": build_protocol_correction(final_answer=True)})
            else:
                current_messages.append({"role": "system", "content": "System: step limit reached. Ignore unfinished internal steps and provide a final answer now."})
            
            resp = await llm_caller(current_messages)
            final_answer = resp.get('content', '')

            if action_mode:
                action_answer = _extract_action_answer(final_answer)
                if action_answer is not None:
                    final_answer = action_answer
                elif parse_tool_calls(final_answer):
                    logger.warning("Final action answer attempted another tool call after step limit")
                    final_answer = (
                        "I could not complete this as a verified tool-backed action within the current tool budget. "
                        "The available observations did not satisfy the request, and the model attempted another tool call "
                        "after the runtime step limit was reached. Please retry or allow a larger tool budget if you want "
                        "the runtime to continue with an alternative source."
                    )
                else:
                    logger.warning("Final action answer was not a structured answer envelope")
                    current_messages.append({'role': 'assistant', 'content': final_answer})
                    current_messages.append({'role': 'user', 'content': build_protocol_correction(final_answer=True)})
                    retry_resp = await llm_caller(current_messages)
                    retry_content = retry_resp.get('content', '')
                    retry_usage = retry_resp.get('usage', {})
                    if retry_usage:
                        final_usage['prompt_tokens'] += retry_usage.get('prompt_tokens', 0)
                        final_usage['completion_tokens'] += retry_usage.get('completion_tokens', 0)
                    retry_answer = _extract_action_answer(retry_content)
                    final_answer = retry_answer if retry_answer is not None else (
                        "I could not produce a verified final answer because the model did not return "
                        "a valid action answer object after the tool budget was exhausted."
                    )
            elif parse_tool_calls(final_answer):
                logger.warning("Final answer contained unexecuted tool JSON after step limit; suppressing protocol text")
                final_answer = (
                    "I could not complete this as a verified tool-backed action within the current tool budget. "
                    "The available observations did not satisfy the request, and the model attempted another tool call "
                    "after the runtime step limit was reached. Please retry or allow a larger tool budget if you want "
                    "the runtime to continue with an alternative source."
                )

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

