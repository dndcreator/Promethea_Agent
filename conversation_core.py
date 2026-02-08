import os
import sys
from datetime import datetime
from typing import List, Dict, Optional, Any
from openai import AsyncOpenAI, OpenAI
from config import config
import time
from loguru import logger

def now():
    return time.strftime('%H:%M:%S:')+str(int(time.time()*1000)%10000) # 当前时间

from agentkit.mcp.mcp_manager import get_mcp_manager
from agentkit.mcp.mcpregistry import initialize_mcp_registry
from agentkit.mcp.tool_call import tool_call_loop

class PrometheaConversation:

    def __init__(self):
       self.dev_mode = False
       # 默认客户端（使用全局配置）
       self.client = OpenAI(api_key=config.api.api_key, base_url=config.api.base_url.rstrip("/")+'/')
       self.async_client = AsyncOpenAI(api_key=config.api.api_key, base_url=config.api.base_url.rstrip("/")+'/')

       # 初始化 MCP 系统
       self.mcp_manager = get_mcp_manager()
       self._init_tools()

    def _init_tools(self):
        """初始化工具注册表"""
        try:
            # 扫描并注册 agentkit/tools 下的所有工具
            services = initialize_mcp_registry(scan_dir='agentkit')
            logger.info(f"已加载工具服务: {services}")
        except Exception as e:
            logger.error(f"工具初始化失败: {e}")

    def prepare_messages(self, messages: List[Dict]) -> List[Dict]:
        """准备发送给LLM的消息（注入工具定义等）"""
        return self._inject_system_prompt(messages)

    def _inject_system_prompt(self, messages: List[Dict]) -> List[Dict]:
        """注入系统提示词和工具定义"""
        # 获取可用服务描述
        services_desc = self.mcp_manager.format_available_services()
        
        system_prompt = f"""你是一个全能的AI助手，名为普罗米娅 (Promethea)。
可以通过调用工具来完成各种任务，包括但不限于搜索网络、控制电脑、管理文件等。

### 可用工具
{services_desc}

### 工具调用规范
如果你需要使用工具，请**严格**按照以下 JSON 格式输出（不要使用 Markdown 代码块）：
{{ "tool_name": "工具名称", "args": {{ "参数名": "参数值" }} }}

支持一次输出多个工具调用来实现并行操作：
{{ "tool_name": "t1", ... }}
{{ "tool_name": "t2", ... }}

例如搜索和打开网页：
{{ "tool_name": "search", "args": {{ "query": "今日天气" }} }}
{{ "tool_name": "browser_action", "args": {{ "action": "goto", "url": "https://calendar.google.com" }} }}
"""
        # 检查是否已有 system prompt，如果有则追加，没有则新建
        new_messages = messages.copy()
        if new_messages and new_messages[0]['role'] == 'system':
            new_messages[0]['content'] += "\n\n" + system_prompt
        else:
            new_messages.insert(0, {'role': 'system', 'content': system_prompt})
            
        return new_messages

    async def run_chat_loop(self, messages: List[Dict], user_config: Optional[Dict[str, Any]] = None, session_id: str = None) -> Dict:
        """运行带工具调用的对话循环"""
        # 1. 注入工具定义的 System Prompt
        messages_with_tools = self._inject_system_prompt(messages)
        
        # 2. 运行工具循环 (Thinking -> Action -> Observation Loop)
        # 传入 self.call_llm 作为基础 LLM 调用器
        # 使用 lambda 包装 call_llm 以传递 user_config
        llm_caller = lambda msgs: self.call_llm(msgs, user_config)
        
        final_response = await tool_call_loop(
            messages=messages_with_tools,
            mcp_manager=self.mcp_manager,
            llm_caller=llm_caller, # 使用包装后的调用器
            is_streaming=False,
            session_id=session_id
        )
        
        return final_response
    
    def _get_client_params(self, user_config: Optional[Dict[str, Any]] = None):
        """获取 API 调用参数，优先使用用户配置"""
        # 默认使用全局配置
        api_key = config.api.api_key
        base_url = config.api.base_url
        model = config.api.model
        temperature = config.api.temperature
        max_tokens = config.api.max_tokens

        # 如果有用户配置，覆盖默认值
        if user_config and 'api' in user_config:
            user_api = user_config['api']
            if user_api.get('api_key'):
                api_key = user_api['api_key']
            if user_api.get('base_url'):
                base_url = user_api['base_url']
            if user_api.get('model'):
                model = user_api['model']
            if user_api.get('temperature') is not None:
                temperature = user_api['temperature']
            if user_api.get('max_tokens') is not None:
                max_tokens = user_api['max_tokens']
        
        return api_key, base_url, model, temperature, max_tokens

    async def call_llm(self, messages: List[Dict], user_config: Optional[Dict[str, Any]] = None) -> Dict:
        try:
            api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)
            
            # 如果是用户自定义配置，需要临时创建 client
            # 否则使用默认 client
            if user_config and 'api' in user_config:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip('/') + '/')
            else:
                client = self.async_client

            params = {
                'model': model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'stream': False
            }
            
            resp = await client.chat.completions.create(**params)
            
            # 安全获取content
            content = ''
            if resp.choices and len(resp.choices) > 0:
                message = getattr(resp.choices[0], 'message', None)
                if message:
                    content = getattr(message, 'content', '') or ''
            
            result = {
                'content': content,
                'status': 'success',
                'usage': {
                    'prompt_tokens': getattr(resp.usage, 'prompt_tokens', 0) if hasattr(resp, 'usage') and resp.usage else 0,
                    'completion_tokens': getattr(resp.usage, 'completion_tokens', 0) if hasattr(resp, 'usage') and resp.usage else 0,
                }
            }
            
            # 记录日志
            try:
                d = datetime.now().strftime('%Y-%m-%d')
                t = datetime.now().strftime('%H:%M:%S')
                log_dir = config.system.log_dir
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                log_file = os.path.join(log_dir, f"{d}.log")
                with open(log_file, 'a', encoding='utf-8') as f:
                    # 简化记录，只记录最后一轮
                    last_user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), "")
                    f.write(f"[{t}] 用户: {last_user}\n")
                    f.write(f"[{t}] 普罗米娅 ({model}): {content}\n")
                    f.write("-" * 50 + "\n")
            except Exception as e:
                logger.error(f"保存对话日志失败: {e}")

            return result
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常: {e}")
                # 重新创建客户端并重试
                # 注意：这里如果使用了 user_config，需要重新用 user_config 创建
                api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip('/') + '/')
                
                params = {
                    'model': model,
                    'messages': messages,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'stream': False
                }
                
                resp = await client.chat.completions.create(**params)
                
                # 安全获取content
                content = ''
                if resp.choices and len(resp.choices) > 0:
                    message = getattr(resp.choices[0], 'message', None)
                    if message:
                        content = getattr(message, 'content', '') or ''
                
                result = {
                    'content': content,
                    'status': 'success',
                    'usage': {
                        'prompt_tokens': getattr(resp.usage, 'prompt_tokens', 0) if hasattr(resp, 'usage') and resp.usage else 0,
                        'completion_tokens': getattr(resp.usage, 'completion_tokens', 0) if hasattr(resp, 'usage') and resp.usage else 0,
                    }
                }
                return result
            else:
                raise
        except Exception as e:
            logger.error(f"LLM API调用失败: {e}")
            return {
                'content': f"API调用失败: {str(e)}",
                'status': 'error',
                'usage': {'prompt_tokens': 0, 'completion_tokens': 0}
            }
    
    async def call_llm_stream(self, messages: List[Dict], user_config: Optional[Dict[str, Any]] = None):
        """流式调用LLM，返回异步生成器"""
        try:
            api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)
            
            if user_config and 'api' in user_config:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip('/') + '/')
            else:
                client = self.async_client

            stream = await client.chat.completions.create(
                model = model,
                messages = messages,
                temperature = temperature,
                max_tokens = max_tokens,
                stream = True
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM流式调用失败: {e}")
            yield f"[错误] {str(e)}"
