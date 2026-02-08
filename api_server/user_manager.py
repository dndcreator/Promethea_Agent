import uuid
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from loguru import logger
from passlib.context import CryptContext
from memory.neo4j_connector import Neo4jConnectionPool
from memory.models import Neo4jNode, NodeType

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserManager:
    def __init__(self):
        self.connector = Neo4jConnectionPool.get_connector()
        # 用户配置存储在 config/users/ 目录下
        self.users_dir = Path("config/users")
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """根据用户名获取用户"""
        if not self.connector:
            return None
        
        query = "MATCH (u:User {username: $username}) RETURN u"
        results = self.connector.query(query, {"username": username})
        return results[0]['u'] if results else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取用户"""
        if not self.connector:
            return None
            
        # user_id 可能是 "user_uuid" 格式
        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"
            
        query = "MATCH (u:User {id: $user_id}) RETURN u"
        results = self.connector.query(query, {"user_id": user_id})
        return results[0]['u'] if results else None

    def create_user(self, username, password, agent_name="Promethea") -> Optional[str]:
        """创建新用户"""
        if not self.connector:
            logger.error("Neo4j 连接不可用，无法创建用户")
            return None

        if self.get_user_by_username(username):
            logger.warning(f"用户 {username} 已存在")
            return None
        
        password_hash = pwd_context.hash(password)
        raw_uuid = str(uuid.uuid4())
        user_id = f"user_{raw_uuid}"
        
        user_node = Neo4jNode(
            id=user_id,
            type=NodeType.USER,
            content=f"用户 {username}",
            properties={
                "username": username,
                "password_hash": password_hash,
                "agent_name": agent_name,
                "user_id": raw_uuid, # 纯 UUID
                "created_at": datetime.now().isoformat()
            }
        )
        
        try:
            self.connector.create_node(user_node)
            logger.info(f"用户 {username} 创建成功: {user_id}")
            
            # 创建用户配置文件
            self.create_user_config(raw_uuid, agent_name)
            
            return raw_uuid
        except Exception as e:
            logger.error(f"创建用户失败: {e}")
            return None

    def create_user_config(self, user_uuid: str, agent_name: str):
        """创建用户默认配置文件"""
        user_dir = self.users_dir / user_uuid
        user_dir.mkdir(exist_ok=True)
        
        config_path = user_dir / "config.json"
        
        # 默认配置模板
        default_config = {
            "agent_name": agent_name,
            "system_prompt": "",  # 空则使用系统默认
            "api": {
                "api_key": "",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "nvidia/nemotron-3-nano-30b-a3b:free",
                "temperature": 0.7,
                "max_tokens": 2000
            }
        }
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"已创建用户配置文件: {config_path}")
        except Exception as e:
            logger.error(f"创建用户配置文件失败: {e}")

    def get_user_config(self, user_uuid: str) -> Dict[str, Any]:
        """获取用户配置"""
        # 用户配置文件直接存储在 config/users/{user_id}.json
        config_path = self.users_dir / f"{user_uuid}.json"
        if not config_path.exists():
            # 如果不存在，尝试重新创建（可能是旧用户）
            # 获取 agent_name
            user = self.get_user_by_id(user_uuid)
            agent_name = user.get('agent_name', 'Promethea') if user else 'Promethea'
            self.create_user_config(user_uuid, agent_name)
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取用户配置文件失败: {e}")
            return {}

    def update_user_config_file(self, user_uuid: str, config_data: Dict[str, Any]) -> bool:
        """更新用户配置文件"""
        # 用户配置文件直接存储在 config/users/{user_id}.json
        config_path = self.users_dir / f"{user_uuid}.json"
        
        # 读取现有配置以进行合并
        current_config = self.get_user_config(user_uuid)
        
        # 深度合并 (简单版)
        if 'api' in config_data:
            current_config.setdefault('api', {}).update(config_data['api'])
        if 'agent_name' in config_data:
            current_config['agent_name'] = config_data['agent_name']
        if 'system_prompt' in config_data:
            current_config['system_prompt'] = config_data['system_prompt']
            
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(current_config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"更新用户配置文件失败: {e}")
            return False

    def verify_user(self, username, password) -> Optional[Dict[str, Any]]:
        """验证用户登录"""
        user = self.get_user_by_username(username)
        if not user:
            return None
        
        if pwd_context.verify(password, user.get('password_hash')):
            return user
        return None

    def update_user_config(self, user_id: str, agent_name: str = None, system_prompt: str = None):
        """更新用户配置 (Neo4j + File)"""
        if not self.connector:
            return False
            
        # 1. 更新 Neo4j (保留作为索引/快速访问)
        if not user_id.startswith("user_"):
            neo4j_user_id = f"user_{user_id}"
        else:
            neo4j_user_id = user_id
            user_id = user_id.replace("user_", "") # 提取纯 UUID 用于文件路径
            
        updates = []
        params = {"user_id": neo4j_user_id}
        
        if agent_name:
            updates.append("u.agent_name = $agent_name")
            params["agent_name"] = agent_name
            
        if system_prompt:
            updates.append("u.system_prompt = $system_prompt")
            params["system_prompt"] = system_prompt
            
        if updates:
            query = f"MATCH (u:User {{id: $user_id}}) SET {', '.join(updates)} RETURN u"
            try:
                self.connector.query(query, params)
            except Exception as e:
                logger.error(f"更新用户配置(Neo4j)失败: {e}")
                return False

        # 2. 更新文件配置
        file_updates = {}
        if agent_name:
            file_updates['agent_name'] = agent_name
        if system_prompt:
            file_updates['system_prompt'] = system_prompt
            
        return self.update_user_config_file(user_id, file_updates)

    def bind_channel_account(self, user_id: str, channel: str, account_id: str) -> bool:
        """绑定渠道账号到用户"""
        if not self.connector:
            return False
            
        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"
            
        # 使用动态属性名 channel_{channel}
        prop_name = f"channel_{channel}"
        query = f"MATCH (u:User {{id: $user_id}}) SET u.{prop_name} = $account_id RETURN u"
        
        try:
            self.connector.query(query, {"user_id": user_id, "account_id": account_id})
            logger.info(f"用户 {user_id} 绑定渠道 {channel} 账号 {account_id} 成功")
            return True
        except Exception as e:
            logger.error(f"绑定渠道账号失败: {e}")
            return False
            
    def get_bound_channels(self, user_id: str) -> Dict[str, str]:
        """获取用户绑定的所有渠道账号"""
        if not self.connector:
            return {}
            
        if not user_id.startswith("user_"):
            user_id = f"user_{user_id}"
            
        query = "MATCH (u:User {id: $user_id}) RETURN u"
        try:
            results = self.connector.query(query, {"user_id": user_id})
            if not results:
                return {}
            
            user_props = results[0]['u']
            channels = {}
            for key, value in user_props.items():
                if key.startswith("channel_"):
                    channel_name = key.replace("channel_", "")
                    channels[channel_name] = value
            return channels
        except Exception as e:
            logger.error(f"获取绑定渠道失败: {e}")
            return {}

    def get_user_by_channel_account(self, channel: str, account_id: str) -> Optional[Dict[str, Any]]:
        """根据渠道账号获取用户"""
        if not self.connector:
            return None
            
        prop_name = f"channel_{channel}"
        query = f"MATCH (u:User) WHERE u.{prop_name} = $account_id RETURN u"
        
        try:
            results = self.connector.query(query, {"account_id": account_id})
            return results[0]['u'] if results else None
        except Exception as e:
            logger.error(f"根据渠道账号查找用户失败: {e}")
            return None

# 全局实例
user_manager = UserManager()
