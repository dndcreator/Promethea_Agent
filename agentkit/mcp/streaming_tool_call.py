import re
import json
import logging
import asyncio
import sys
import os
from typing import Callable, Optional, Dict, Any, Union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import config, AI_NAME
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import config, AI_NAME

from .tool_call import parse_tool_calls, execute_tool_calls

logger = logging.getLogger("StreamingToolCall")

class CallbackManager:

    def __init__(self):

        self.callbacks = {}
        self.callback_types = {}

    def register_callback(self, name: str, callback: Optional[Callable]):

        self.callbacks[name] = callback
        if callback:
            self.callback_types[name] = asyncio.iscoroutinefunction(callback)
        else:
            self.callback_types[name] = False
    
    async def call_callback(self, name: str, *args, **kwargs):

        callback = self.callbacks.get(name)
        if not callback:
            return None
        try:
            if self.callback_types.get(name, False):
                return await callback(*args, **kwargs)
            else:
                return callback(*args, **kwargs)
        except Exception as e:
            logger.error(f"回调函数 {name} 执行错误: {e}")
            return None



class StreamingToolCall:

    def __init__(self, mcp_manager=None):

        self.tool_call_buffer = ""
        self.is_in_tool_call = False
        self.brace_count = 0
        self.mcp_manager = mcp_manager
        self.text_buffer = ""
        self.sentence_endings = r"[。？！；\.\?\!\;]"

        self.callback_manager = CallbackManager()
        
        self.voice_integration = None

        self.tool_calls_queue = None
    
    def set_callbacks(self, 
                     on_text_chunk: Optional[Callable] = None,
                     on_sentence: Optional[Callable] = None,
                     on_tool_result: Optional[Callable] = None,
                     voice_integration=None,
                     tool_calls_queue=None,
                     tool_call_detected_signal=None):
        
        self.callback_manager.register_callback("text_chunk", on_text_chunk)
        self.callback_manager.register_callback("sentence", on_sentence)
        self.callback_manager.register_callback("tool_result", on_tool_result)

        self.voice_integration = voice_integration
        self.tool_calls_queue = tool_calls_queue
        self.tool_call_detected_signal = tool_call_detected_signal

    async def process_text_chunk(self, text_chunk: str):

        if not text_chunk:
            return None
        
        results = []
        for char in text_chunk:
            if char in '{｛':
                if not self.is_in_tool_call:
                    if self.text_buffer:
                        result = await self._flush_text_buffer()
                        if result:
                            results.append(result)
                    
                    self.is_in_tool_call = True
                    self.tool_call_buffer = char
                    self.brace_count = 1
                else:
                    self.tool_call_buffer += char
                    self.brace_count += 1
                
            elif char in '}｝':
                if self.is_in_tool_call:
                    self.tool_call_buffer += char
                    self.brace_count -= 1
                    
                    if self.brace_count == 0:
                        tool_call = self.tool_call_buffer
                        self.tool_call_buffer = ""
                        self.is_in_tool_call = False

                        result = await self._extract_tool_call(tool_call)
                        if result:
                            results.append(result)
            else:
                if self.is_in_tool_call:
                    self.tool_call_buffer += char
                else:
                    self.text_buffer += char
                    if re.search(self.sentence_endings, char):
                        sentences = re.split(self.sentence_endings, self.text_buffer)
                        if len(sentences) > 1:
                            complete_sentence = sentences[0] + char
                            if complete_sentence.strip():
                                result = await self.callback_manager.call_callback(
                                    "text_chunk", complete_sentence, "chunk"
                                )
                                if result:
                                    results.append(result)
                                
                                await self.callback_manager.call_callback(
                                    "sentence", complete_sentence, "sentence"
                                )
                                await self._send_to_voice_integration(complete_sentence)
                            remaining_sentences = [s for s in sentences[1:] if s.strip()]
                            self.text_buffer = "".join(remaining_sentences)
        return results
    
    async def _flush_text_buffer(self):

        if self.text_buffer:
            result = await self.callback_manager.call_callback(
                "text_chunk", self.text_buffer, "chunk"
            )
            await self._send_to_voice_integration(self.text_buffer)

            self.text_buffer = ""
            return result

        return None

    async def _send_to_voice_integration(self, text: str):

        if self.voice_integration:
            try:
                import threading
                threading.Thread(
                    target=self.voice_integration.receive_text_chunk,
                    args=(text,),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"语音集成错误: {e}")

    async def _extract_tool_call(self, tool_call: str):

        try:
            logger.info(f"检测到工具调用: {tool_call[:100]}...")
            tool_calls = parse_tool_calls(tool_call)

            if tool_calls:
                logger.info(f"解析到 {len(tool_calls)} 个工具调用")
                if self.tool_calls_queue:
                    for tool_call in tool_calls:
                        # 兼容 asyncio.Queue，使用 put_nowait (非阻塞)
                        if hasattr(self.tool_calls_queue, 'put_nowait'):
                            self.tool_calls_queue.put_nowait(tool_call)
                        else:
                            # 兼容普通 Queue
                            self.tool_calls_queue.put(tool_call)
                    logger.info(f"已将 {len(tool_calls)} 个工具调用添加到队列")
                
                if self.tool_call_detected_signal:
                    try:
                        self.tool_call_detected_signal("正在执行工具调用...")
                    except Exception as e:
                        logger.error(f"工具调用检测信号执行错误: {e}")
                
                return (AI_NAME, f"<span style='color:#888;font-size:14pt;font-family:Lucida Console;'>🔧 检测到工具调用，正在执行...</span>")
            else:
                logger.warning("工具调用解析失败")
        except Exception as e:
            error_msg = f"工具调用提取失败: {str(e)}"
            logger.error(error_msg)
        
        return None
    
    async def finish_processing(self):

        results = []
        
        if self.text_buffer:
            result = await self._flush_text_buffer()
            if result:
                results.append(result)
        
        if self.is_in_tool_call and self.tool_call_buffer:
            logger.warning(f"检测到未完成的工具调用: {self.tool_call_buffer}")
            # 可以选择丢弃或特殊处理
        return results if results else None

    def reset(self):

        self.tool_call_buffer = ""
        self.is_in_tool_call = False
        self.brace_count = 0
        self.text_buffer = ""



class StreamingToolCallProcessor:

    def __init__(self, mcp_manager=None):

        self.tool_call_extractor = StreamingToolCall(mcp_manager)
        self.response_buffer = ""
        self.is_processing = False

    async def process_ai_response(self, response_stream, callbacks: Dict[str, Callable]):

        self.is_processing = True
        self.response_buffer = ""

        self.tool_call_extractor.set_callbacks(**callbacks)
        try:
            async for chunk in response_stream:
                if not self.is_processing:
                    break
                
                chunk_text = str(chunk)
                self.response_buffer += chunk_text
                await self.tool_call_extractor.process_text_chunk(chunk_text)
        except Exception as e:
            logger.error(f"AI流式响应处理错误: {e}")
        finally:
            self.is_processing = False
            await self.tool_call_extractor.finish_processing()
        
    def stop_processing(self):
        
        self.is_processing = False
    
    def get_response_buffer(self) -> str:

        return self.response_buffer
