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
    
    
    async def call_llm(self, messages: List[Dict], enable_logprobs: bool = False) -> Dict:
        try:
            params = {
                'model': config.api.model,
                'messages': messages,
                'temperature': config.api.temperature,
                'max_tokens': config.api.max_tokens,
                'stream': False
            }
            
            # 启用logprobs（用于置信度分析）
            if enable_logprobs:
                params['logprobs'] = True
                params['top_logprobs'] = 5
                logger.debug(f"已启用logprobs，模型: {config.api.model}")
            
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
            
            # 返回logprobs数据（如果启用）
            if enable_logprobs and resp.choices and len(resp.choices) > 0:
                choice = resp.choices[0]
                if hasattr(choice, 'logprobs') and choice.logprobs:
                    try:
                        logprobs_obj = choice.logprobs
                        # 兼容不同API的logprobs结构
                        logprobs_content = []
                        content_data = getattr(logprobs_obj, 'content', None) or []
                        
                        for item in content_data:
                            token = getattr(item, 'token', None)
                            logprob = getattr(item, 'logprob', None)
                            if token is None or logprob is None:
                                continue
                            
                            top_logprobs_data = getattr(item, 'top_logprobs', None) or []
                            top_probs = []
                            for top in top_logprobs_data:
                                top_token = getattr(top, 'token', None)
                                top_logprob = getattr(top, 'logprob', None)
                                if top_token is not None and top_logprob is not None:
                                    top_probs.append({'token': top_token, 'logprob': top_logprob})
                            
                            logprobs_content.append({
                                'token': token,
                                'logprob': logprob,
                                'top_logprobs': top_probs
                            })
                        
                        if logprobs_content:
                            result['logprobs'] = {'content': logprobs_content}
                            logger.debug(f"✅ 成功获取logprobs，token数: {len(logprobs_content)}")
                        else:
                            logger.warning(f"⚠️ logprobs数据为空")
                    except Exception as e:
                        logger.warning(f"⚠️ 解析logprobs失败: {e}")
                else:
                    logger.warning(f"⚠️ 模型 {config.api.model} 未返回logprobs（可能不支持此功能）")
            
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
                
                if enable_logprobs and resp.choices and len(resp.choices) > 0:
                    choice = resp.choices[0]
                    if hasattr(choice, 'logprobs') and choice.logprobs:
                        try:
                            logprobs_obj = choice.logprobs
                            logprobs_content = []
                            content_data = getattr(logprobs_obj, 'content', None) or []
                            
                            for item in content_data:
                                token = getattr(item, 'token', None)
                                logprob = getattr(item, 'logprob', None)
                                if token is None or logprob is None:
                                    continue
                                
                                top_logprobs_data = getattr(item, 'top_logprobs', None) or []
                                top_probs = []
                                for top in top_logprobs_data:
                                    top_token = getattr(top, 'token', None)
                                    top_logprob = getattr(top, 'logprob', None)
                                    if top_token is not None and top_logprob is not None:
                                        top_probs.append({'token': top_token, 'logprob': top_logprob})
                                
                                logprobs_content.append({
                                    'token': token,
                                    'logprob': logprob,
                                    'top_logprobs': top_probs
                                })
                            
                            if logprobs_content:
                                result['logprobs'] = {'content': logprobs_content}
                                logger.debug(f"✅ 成功获取logprobs (重试后)，token数: {len(logprobs_content)}")
                            else:
                                logger.warning(f"⚠️ logprobs数据为空 (重试后)")
                        except Exception as e:
                            logger.warning(f"⚠️ 解析logprobs失败 (重试后): {e}")
                    else:
                        logger.warning(f"⚠️ 模型未返回logprobs (重试后)")
                
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
    