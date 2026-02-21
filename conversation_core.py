from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI, OpenAI

from agentkit.mcp.mcp_manager import get_mcp_manager
from agentkit.mcp.mcpregistry import initialize_mcp_registry
from agentkit.mcp.tool_call import tool_call_loop
from config import config


class PrometheaConversation:
    def __init__(self):
        self.dev_mode = False
        self.client = OpenAI(
            api_key=config.api.api_key,
            base_url=config.api.base_url.rstrip("/") + "/",
        )
        self.async_client = AsyncOpenAI(
            api_key=config.api.api_key,
            base_url=config.api.base_url.rstrip("/") + "/",
        )

        self.mcp_manager = get_mcp_manager()
        self._init_tools()

    def _init_tools(self):
        try:
            services = initialize_mcp_registry(scan_dir="agentkit")
            logger.info(f"Loaded tool services: {services}")
        except Exception as e:
            logger.error(f"Tool initialization failed: {e}")

    def prepare_messages(self, messages: List[Dict]) -> List[Dict]:
        return self._inject_system_prompt(messages)

    def _inject_system_prompt(self, messages: List[Dict]) -> List[Dict]:
        services_desc = self.mcp_manager.format_available_services()

        system_prompt = (
            "You are Promethea, an assistant that can call tools.\n"
            "When you need tools, output strict JSON objects with keys tool_name and args.\n"
            "Available tools:\n"
            f"{services_desc}"
        )

        new_messages = list(messages)
        if new_messages and new_messages[0].get("role") == "system":
            new_messages[0]["content"] = f"{new_messages[0].get('content', '')}\n\n{system_prompt}"
        else:
            new_messages.insert(0, {"role": "system", "content": system_prompt})

        return new_messages

    @staticmethod
    def _safe_user_segment(user_id: Optional[str]) -> str:
        uid = str(user_id or "default_user").strip() or "default_user"
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in uid)
        return safe[:128] or "default_user"

    async def run_chat_loop(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        session_id: str = None,
        user_id: Optional[str] = None,
        tool_executor=None,
    ) -> Dict:
        messages_with_tools = self._inject_system_prompt(messages)
        llm_caller = lambda msgs: self.call_llm(msgs, user_config, user_id=user_id)

        final_response = await tool_call_loop(
            messages=messages_with_tools,
            mcp_manager=self.mcp_manager,
            llm_caller=llm_caller,
            is_streaming=False,
            session_id=session_id,
            tool_executor=tool_executor,
        )

        return final_response

    def _get_client_params(self, user_config: Optional[Dict[str, Any]] = None):
        api_key = config.api.api_key
        base_url = config.api.base_url
        model = config.api.model
        temperature = config.api.temperature
        max_tokens = config.api.max_tokens

        if user_config and "api" in user_config:
            user_api = user_config["api"]
            if user_api.get("api_key"):
                api_key = user_api["api_key"]
            if user_api.get("base_url"):
                base_url = user_api["base_url"]
            if user_api.get("model"):
                model = user_api["model"]
            if user_api.get("temperature") is not None:
                temperature = user_api["temperature"]
            if user_api.get("max_tokens") is not None:
                max_tokens = user_api["max_tokens"]

        return api_key, base_url, model, temperature, max_tokens

    async def call_llm(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict:
        try:
            api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)

            if user_config and "api" in user_config:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip("/") + "/")
            else:
                client = self.async_client

            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )

            content = ""
            if resp.choices and len(resp.choices) > 0:
                message = getattr(resp.choices[0], "message", None)
                if message:
                    content = getattr(message, "content", "") or ""

            result = {
                "content": content,
                "status": "success",
                "usage": {
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0)
                    if hasattr(resp, "usage") and resp.usage
                    else 0,
                    "completion_tokens": getattr(resp.usage, "completion_tokens", 0)
                    if hasattr(resp, "usage") and resp.usage
                    else 0,
                },
            }

            try:
                d = datetime.now().strftime("%Y-%m-%d")
                t = datetime.now().strftime("%H:%M:%S")
                user_log_dir = os.path.join(str(config.system.log_dir), self._safe_user_segment(user_id))
                if not os.path.exists(user_log_dir):
                    os.makedirs(user_log_dir, exist_ok=True)

                log_file = os.path.join(user_log_dir, f"{d}.log")
                with open(log_file, "a", encoding="utf-8") as f:
                    last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
                    f.write(f"[{t}] USER: {last_user}\n")
                    f.write(f"[{t}] ASSISTANT ({model}): {content}\n")
                    f.write("-" * 50 + "\n")
            except Exception as e:
                logger.error(f"save conversation log failed: {e}")

            return result
        except RuntimeError as e:
            if "handler is closed" in str(e):
                logger.debug(f"ignore closed-handler and retry once: {e}")
                api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip("/") + "/")
                resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                content = ""
                if resp.choices and len(resp.choices) > 0:
                    message = getattr(resp.choices[0], "message", None)
                    if message:
                        content = getattr(message, "content", "") or ""
                return {
                    "content": content,
                    "status": "success",
                    "usage": {
                        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0)
                        if hasattr(resp, "usage") and resp.usage
                        else 0,
                        "completion_tokens": getattr(resp.usage, "completion_tokens", 0)
                        if hasattr(resp, "usage") and resp.usage
                        else 0,
                    },
                }
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return {
                "content": f"API call failed: {e}",
                "status": "error",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }

    async def call_llm_stream(
        self,
        messages: List[Dict],
        user_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ):
        try:
            api_key, base_url, model, temperature, max_tokens = self._get_client_params(user_config)
            if user_config and "api" in user_config:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url.rstrip("/") + "/")
            else:
                client = self.async_client

            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM streaming call failed: {e}")
            yield f"[error] {e}"
