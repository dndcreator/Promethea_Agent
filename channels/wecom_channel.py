"""
"""
import time
from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import aiohttp
import json

from .base import BaseChannel, ChannelType, MessageType, Message, ChannelConfig


class WeComChannel(BaseChannel):
    """TODO: add docstring."""
    
    def __init__(self, config: ChannelConfig):
        super().__init__("wecom", ChannelType.WECOM, config)
        
        self.corpid = config.extra.get("corpid")
        self.corpsecret = config.app_secret
        self.agentid = config.extra.get("agentid")
        self.webhook_url = config.webhook_url
        
        self.api_base = config.api_endpoint or "https://qyapi.weixin.qq.com/cgi-bin"
        
        self.access_token = None
        self.token_expires_at = 0
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        """TODO: add docstring."""
        try:
            self.session = aiohttp.ClientSession()
            
            if self.corpid and self.corpsecret:
                await self._refresh_access_token()
            
            self.is_connected = True
            self.logger.info("WeCom channel connected")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect WeCom: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """TODO: add docstring."""
        if self.session:
            await self.session.close()
            self.session = None
        
        self.is_connected = False
        self.logger.info("WeCom channel disconnected")
        return True
    
    async def _refresh_access_token(self):
        """TODO: add docstring."""
        url = f"{self.api_base}/gettoken"
        params = {
            "corpid": self.corpid,
            "corpsecret": self.corpsecret
        }
        
        async with self.session.get(url, params=params) as response:
            data = await response.json()
            if data.get("errcode") == 0:
                self.access_token = data.get("access_token")
                self.token_expires_at = time.time() + data.get("expires_in", 7200) - 300
                self.logger.info("WeCom access token refreshed")
            else:
                raise Exception(f"Failed to get access token: {data}")
    
    async def _ensure_token(self):
        """TODO: add docstring."""
        if not self.access_token or time.time() >= self.token_expires_at:
            await self._refresh_access_token()
    
    async def send_message(
        self,
        receiver_id: str,  # userid, partyid, tagid
        content: str,
        message_type: MessageType = MessageType.TEXT,
        **kwargs
    ) -> Dict[str, Any]:
        """TODO: add docstring."""
        try:
            if self.webhook_url and kwargs.get("use_webhook", True):
                return await self._send_webhook_message(content, message_type, **kwargs)
            
            else:
                await self._ensure_token()
                return await self._send_api_message(receiver_id, content, message_type, **kwargs)
                
        except Exception as e:
            self.logger.error(f"Error sending WeCom message: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_webhook_message(
        self,
        content: str,
        message_type: MessageType,
        **kwargs
    ) -> Dict[str, Any]:
        if not self.webhook_url:
            return {"success": False, "error": "Webhook URL not configured"}
        
        if message_type == MessageType.TEXT:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
            
            mentioned_list = kwargs.get("mentioned_list", [])
            mentioned_mobile_list = kwargs.get("mentioned_mobile_list", [])
            if mentioned_list or mentioned_mobile_list:
                payload["text"]["mentioned_list"] = mentioned_list
                payload["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        
        elif message_type == MessageType.MARKDOWN:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {"content": content}
            }
        
        async with self.session.post(self.webhook_url, json=payload) as response:
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
        """TODO: add docstring."""
        url = f"{self.api_base}/message/send"
        params = {"access_token": self.access_token}
        
        if message_type == MessageType.TEXT:
            msg_data = {
                "content": content
            }
            msgtype = "text"
        elif message_type == MessageType.MARKDOWN:
            msg_data = {
                "content": content
            }
            msgtype = "markdown"
        else:
            msg_data = {
                "content": content
            }
            msgtype = "text"
        
        
        payload = {
            "touser": touser,
            "toparty": toparty,
            "totag": totag,
            "msgtype": msgtype,
            "agentid": self.agentid,
            msgtype: msg_data
        }
        
        async with self.session.post(url, params=params, json=payload) as response:
            result = await response.json()
            
            return {
                "success": result.get("errcode") == 0,
                "message_id": result.get("msgid"),
                "result": result
            }
    
    async def send_card(
        self,
        receiver_id: str,
        card_data: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        try:
            await self._ensure_token()
            
            url = f"{self.api_base}/message/send"
            params = {"access_token": self.access_token}
            
            payload = {
                "touser": kwargs.get("touser", receiver_id),
                "toparty": kwargs.get("toparty", ""),
                "totag": kwargs.get("totag", ""),
                "msgtype": "textcard",
                "agentid": self.agentid,
                "textcard": {
                    "title": card_data.get("title", "Message"),
                    "description": card_data.get("description", ""),
                    "url": card_data.get("url", ""),
                    "btntxt": card_data.get("btntxt", "Details")
                }
            }
            
            async with self.session.post(url, params=params, json=payload) as response:
                result = await response.json()
                
                return {
                    "success": result.get("errcode") == 0,
                    "message_id": result.get("msgid"),
                    "result": result
                }
                
        except Exception as e:
            self.logger.error(f"Error sending WeCom card: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """TODO: add docstring."""
        try:
            await self._ensure_token()
            
            url = f"{self.api_base}/user/get"
            params = {
                "access_token": self.access_token,
                "userid": user_id
            }
            
            async with self.session.get(url, params=params) as response:
                result = await response.json()
                
                if result.get("errcode") == 0:
                    return result
                else:
                    self.logger.error(f"Failed to get user info: {result}")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting WeCom user info: {e}")
            return None
    
    async def validate_config(self) -> bool:
        """TODO: add docstring."""
        if not self.config.enabled:
            return True
        
        has_webhook = bool(self.webhook_url)
        has_app = bool(self.corpid and self.corpsecret and self.agentid)
        
        if not (has_webhook or has_app):
            self.logger.error("WeCom config missing: need webhook_url or (corpid+corpsecret+agentid)")
            return False
        
        return True
