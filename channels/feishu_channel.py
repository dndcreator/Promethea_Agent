"""
"""
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import aiohttp
import json

from .base import BaseChannel, ChannelType, MessageType, Message, ChannelConfig


class FeishuChannel(BaseChannel):
    """TODO: add docstring."""
    
    def __init__(self, config: ChannelConfig):
        super().__init__("feishu", ChannelType.FEISHU, config)
        
        self.app_id = config.app_key
        self.app_secret = config.app_secret
        self.webhook_url = config.webhook_url
        self.webhook_secret = config.extra.get("webhook_secret")
        
        self.api_base = config.api_endpoint or "https://open.feishu.cn/open-apis"
        
        self.tenant_access_token = None
        self.token_expires_at = 0
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        """TODO: add docstring."""
        try:
            self.session = aiohttp.ClientSession()
            
            if self.app_id and self.app_secret:
                await self._refresh_access_token()
            
            self.is_connected = True
            self.logger.info("Feishu channel connected")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect Feishu: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """TODO: add docstring."""
        if self.session:
            await self.session.close()
            self.session = None
        
        self.is_connected = False
        self.logger.info("Feishu channel disconnected")
        return True
    
    async def _refresh_access_token(self):
        """TODO: add docstring."""
        url = f"{self.api_base}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        async with self.session.post(url, json=payload) as response:
            data = await response.json()
            if data.get("code") == 0:
                self.tenant_access_token = data.get("tenant_access_token")
                self.token_expires_at = time.time() + data.get("expire", 7200) - 300
                self.logger.info("Feishu access token refreshed")
            else:
                raise Exception(f"Failed to get access token: {data}")
    
    async def _ensure_token(self):
        """TODO: add docstring."""
        if not self.tenant_access_token or time.time() >= self.token_expires_at:
            await self._refresh_access_token()
    
    def _generate_signature(self, timestamp: str, secret: str) -> str:
        """TODO: add docstring."""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = hmac_code.hex()
        return sign
    
    async def send_message(
        self,
        receiver_id: str,  # open_id, user_id, union_id, email, chat_id
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            if self.webhook_url and kwargs.get("use_webhook", True):
                return await self._send_webhook_message(content, message_type, **kwargs)
            
            else:
                await self._ensure_token()
                return await self._send_api_message(receiver_id, content, message_type, **kwargs)
                
        except Exception as e:
            self.logger.error(f"Error sending Feishu message: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_webhook_message(
        self,
        content: str,
        message_type: MessageType,
        **kwargs
    ) -> Dict[str, Any]:
        """TODO: add docstring."""
        if not self.webhook_url:
            return {"success": False, "error": "Webhook URL not configured"}
        
        if message_type == MessageType.TEXT:
            payload = {
                "msg_type": "text",
                "content": {
                    "text": content
                }
            }
        elif message_type == MessageType.MARKDOWN:
            payload = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "content": [[{"tag": "text", "text": content}]]
                        }
                    }
                }
            }
        else:
            payload = {
                "msg_type": "text",
                "content": {"text": content}
            }
        
        if self.webhook_secret:
            timestamp = str(int(time.time()))
            sign = self._generate_signature(timestamp, self.webhook_secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign
        
        async with self.session.post(self.webhook_url, json=payload) as response:
            result = await response.json()
            
            return {
                "success": result.get("StatusCode") == 0 or result.get("code") == 0,
                "message_id": str(uuid.uuid4()),
                "result": result
            }
    
    async def _send_api_message(
        self,
        receiver_id: str,
        content: str,
        message_type: MessageType,
        **kwargs
    ) -> Dict[str, Any]:
        url = f"{self.api_base}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        receive_id_type = kwargs.get("receive_id_type", "chat_id")  # open_id, user_id, union_id, email, chat_id
        
        if message_type == MessageType.TEXT:
            msg_type = "text"
            msg_content = {"text": content}
        elif message_type == MessageType.MARKDOWN:
            msg_type = "post"
            msg_content = {
                "zh_cn": {
                    "title": kwargs.get("title", "Message"),
                    "content": [[{"tag": "text", "text": content}]]
                }
            }
        else:
            msg_type = "text"
            msg_content = {"text": content}
        
        payload = {
            "receive_id": receiver_id,
            "msg_type": msg_type,
            "content": json.dumps(msg_content)
        }
        
        params = {"receive_id_type": receive_id_type}
        
        async with self.session.post(url, headers=headers, params=params, json=payload) as response:
            result = await response.json()
            
            return {
                "success": result.get("code") == 0,
                "message_id": result.get("data", {}).get("message_id"),
                "result": result
            }
    
    async def send_card(
        self,
        receiver_id: str,
        card_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """TODO: add docstring."""
        try:
            if self.webhook_url and kwargs.get("use_webhook", True):
                payload = {
                    "msg_type": "interactive",
                    "card": card_data
                }
                
                if self.webhook_secret:
                    timestamp = str(int(time.time()))
                    sign = self._generate_signature(timestamp, self.webhook_secret)
                    payload["timestamp"] = timestamp
                    payload["sign"] = sign
                
                async with self.session.post(self.webhook_url, json=payload) as response:
                    result = await response.json()
                    
                    return {
                        "success": result.get("StatusCode") == 0 or result.get("code") == 0,
                        "message_id": str(uuid.uuid4()),
                        "result": result
                    }
            
            else:
                await self._ensure_token()
                
                url = f"{self.api_base}/im/v1/messages"
                headers = {
                    "Authorization": f"Bearer {self.tenant_access_token}",
                    "Content-Type": "application/json; charset=utf-8"
                }
                
                payload = {
                    "receive_id": receiver_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card_data)
                }
                
                receive_id_type = kwargs.get("receive_id_type", "chat_id")
                params = {"receive_id_type": receive_id_type}
                
                async with self.session.post(url, headers=headers, params=params, json=payload) as response:
                    result = await response.json()
                    
                    return {
                        "success": result.get("code") == 0,
                        "message_id": result.get("data", {}).get("message_id"),
                        "result": result
                    }
                    
        except Exception as e:
            self.logger.error(f"Error sending Feishu card: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            await self._ensure_token()
            
            url = f"{self.api_base}/contact/v3/users/{user_id}"
            headers = {
                "Authorization": f"Bearer {self.tenant_access_token}"
            }
            
            async with self.session.get(url, headers=headers) as response:
                result = await response.json()
                
                if result.get("code") == 0:
                    return result.get("data", {}).get("user")
                else:
                    self.logger.error(f"Failed to get user info: {result}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting Feishu user info: {e}")
            return None
    
    async def validate_config(self) -> bool:
        if not self.config.enabled:
            return True
        
        has_webhook = bool(self.webhook_url)
        has_app = bool(self.app_id and self.app_secret)
        
        if not (has_webhook or has_app):
            self.logger.error("Feishu config missing: need webhook_url or (app_id+app_secret)")
            return False
        
        return True
