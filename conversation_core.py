import os
import sys
import logging
from datetime import datetime
from typing import List, Dict
from openai import AsyncOpenAI, OpenAI
from config import config
import traceback
import time

def now():
    return time.strftime('%H:%M:%S:')+str(int(time.time()*1000)%10000) # 当前时间

log_level = getattr(logging, config.system.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("PrometheaConversation")



class PrometheaConversation:

    def __init__(self):
       self.dev_mode = False
       self.client = OpenAI(api_key=config.api.api_key, base_url=config.api.base_url.rstrip("/")+'/')
       self.async_client = AsyncOpenAI(api_key=config.api.api_key, base_url=config.api.base_url.rstrip("/")+'/')

    def save_log(self, u, a): # 启动对话日志
        if self.dev_mode:
            return
        d = datetime.now().strftime('%Y-%m-%d')
        t = datetime.now().strftime('%H:%M:%S')

        log_dir = config.system.log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            logger.info(f"已创建日志目录: {log_dir}")
        
        log_file = os.path.join(log_dir, f"{d}.log")
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{t}] 用户: {u}\n")
                f.write(f"[{t}] 普罗米娅: {a}\n")
                f.write("-" * 50 + "\n")
        except Exception as e:
            logger.error(f"保存日志失败: {e}")
    
    
    async def call_llm(self, messages: List[Dict]) -> Dict:
        try:
            params = {
                'model': config.api.model,
                'messages': messages,
                'temperature': config.api.temperature,
                'max_tokens': config.api.max_tokens,
                'stream': False
            }
            
            resp = await self.async_client.chat.completions.create(**params)
            
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
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"忽略连接关闭异常: {e}")
                # 重新创建客户端并重试
                self.async_client = AsyncOpenAI(api_key=config.api.api_key, base_url=config.api.base_url.rstrip('/') + '/')
                resp = await self.async_client.chat.completions.create(**params)
                
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
    
    async def call_llm_stream(self, messages: List[Dict]):
        """流式调用LLM，返回异步生成器"""
        try:
            stream = await self.async_client.chat.completions.create(
                model = config.api.model,
                messages = messages,
                temperature = config.api.temperature,
                max_tokens = config.api.max_tokens,
                stream = True
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM流式调用失败: {e}")
            yield f"[错误] {str(e)}"
    