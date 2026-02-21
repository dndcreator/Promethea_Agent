"""
"""
import hmac
import hashlib
import base64
import time
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import aiohttp

from .base import BaseChannel, ChannelType, MessageType, Message, ChannelConfig


class DingTalkChannel(BaseChannel):
    """TODO: add docstring."""
    
    def __init__(self, config: ChannelConfig):
        super().__init__("dingtalk", ChannelType.DINGTALK, config)
        
        self.app_key = config.app_key
        self.app_secret = config.app_secret
        self.webhook_url = config.webhook_url
        self.robot_code = config.extra.get("robot_code")
        
        self.api_base = config.api_endpoint or "https://oapi.dingtalk.com"
        
        self.access_token = None
        self.token_expires_at = 0
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        """TODO: add docstring."""
        try:
            self.session = aiohttp.ClientSession()
            
            if self.app_key and self.app_secret:
                await self._refresh_access_token()
            
            self.is_connected = True
            self.logger.info("DingTalk channel connected")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect DingTalk: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """TODO: add docstring."""
        if self.session:
            await self.session.close()
            self.session = None
        
        self.is_connected = False
        self.logger.info("DingTalk channel disconnected")
        return True
    
    async def _refresh_access_token(self):
        """TODO: add docstring."""
        url = f"{self.api_base}/gettoken"
        params = {
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        async with self.session.get(url, params=params) as response:
            data = await response.json()
            if data.get("errcode") == 0:
                self.access_token = data.get("access_token")
                self.token_expires_at = time.time() + data.get("expires_in", 7200) - 300
                self.logger.info("DingTalk access token refreshed")
            else:
                raise Exception(f"Failed to get access token: {data}")
    
    async def _ensure_token(self):
        """TODO: add docstring."""
        if not self.access_token or time.time() >= self.token_expires_at:
            await self._refresh_access_token()
    
    def _generate_signature(self, timestamp: int, secret: str) -> str:
        """TODO: add docstring."""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
    
    async def send_message(
        self,
        receiver_id: str,  # chat_id / user_id
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
            self.logger.error(f"Error sending DingTalk message: {e}")
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
        
        url = self.webhook_url
        if self.app_secret:
            timestamp = int(time.time() * 1000)
            sign = self._generate_signature(timestamp, self.app_secret)
            url = f"{url}&timestamp={timestamp}&sign={sign}"
        
        if message_type == MessageType.TEXT:
            payload = {
                "msgtype": "text",
                "text": {"content": content}
            }
        elif message_type == MessageType.MARKDOWN:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "text": content
                }
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {"content": content}
            }
        
        at_users = kwargs.get("at_users", [])
        if at_users or kwargs.get("at_all", False):
            payload["at"] = {
                "atMobiles": at_users,
                "isAtAll": kwargs.get("at_all", False)
            }
        
        async with self.session.post(url, json=payload) as response:
            result = await response.json()
            
            return {
                "success": result.get("errcode") == 0,
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
        url = f"{self.api_base}/robot/send"
        params = {"access_token": self.access_token}
        
        payload = {
            "chatId": receiver_id,
            "msg": {
                "msgtype": "text",
                "text": {"content": content}
            }
        }
        
        async with self.session.post(url, params=params, json=payload) as response:
            result = await response.json()
            
            return {
                "success": result.get("errcode") == 0,
                "message_id": result.get("messageId"),
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
            url = self.webhook_url
            if self.app_secret:
                timestamp = int(time.time() * 1000)
                sign = self._generate_signature(timestamp, self.app_secret)
                url = f"{url}&timestamp={timestamp}&sign={sign}"
            
            payload = {
                "msgtype": "actionCard",
                "actionCard": {
                    "text": card_data.get("text", ""),
                    "btnOrientation": card_data.get("btn_orientation", "0"),
                    "btns": card_data.get("buttons", [])
                }
            }
            
            async with self.session.post(url, json=payload) as response:
                result = await response.json()
                
                return {
                    "success": result.get("errcode") == 0,
                    "message_id": str(uuid.uuid4()),
                    "result": result
                }
                
        except Exception as e:
            self.logger.error(f"Error sending DingTalk card: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            await self._ensure_token()
            
            url = f"{self.api_base}/topapi/v2/user/get"
            params = {"access_token": self.access_token}
            payload = {"userid": user_id}
            
            async with self.session.post(url, params=params, json=payload) as response:
                result = await response.json()
                
                if result.get("errcode") == 0:
                    return result.get("result")
                else:
                    self.logger.error(f"Failed to get user info: {result}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting DingTalk user info: {e}")
            return None
    
    async def validate_config(self) -> bool:
        if not self.config.enabled:
            return True
        
        has_webhook = bool(self.webhook_url)
        has_app = bool(self.app_key and self.app_secret)
        
        if not (has_webhook or has_app):
            self.logger.error("DingTalk config missing: need webhook_url or (app_key+app_secret)")
            return False
        
        return True
