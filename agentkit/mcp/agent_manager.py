import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import json
from pathlib import Path
import asyncio


logging.basicConfig(level = logging.INFO)
logger = logging.getLogger("AgentManager")

@dataclass
class AgentConfig:

    id: str
    name: str
    base_name: str
    system_prompt: str
    max_output_tokens: int = 40000
    temperature: float = 0.7
    description: str = ""
    model_provider: str = "openai"
    api_base_url: str = ""
    api_key: str = ""

@dataclass
class AgentSession:

    timestamp: float = field(default_factory=time.time)
    history: List[Dict[str, str]] = field(default_factory=list)
    session_id: str = "default_user_session"

class AgentManager:

    def __init__(self, config_dir: str = None):

        self.config_dir = Path(config_dir) if config_dir else None
        self.agents: Dict[str, AgentConfig] = {}
        self.agent_sessions: Dict[str, Dict[str, AgentSession]] = {}

        try:
            from config import config, AI_NAME
            self.max_history_rounds = config.api.max_history_rounds
        except ImportError:
            self.max_history_rounds = 10
            logger.warning("无法导入配置，使用默认历史轮数设置")
        self.context_ttl_hours = 24
        self.debug_mode = True

        if self.config_dir:
            self.config_dir.mkdir(exist_ok=True)
            self._load_agent_configs()
        else:
            logger.info("AgentManager使用MCP架构，跳过外部配置文件加载")
        
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            pass
        logger.info(f"AgentManager初始化完成,已加载 {len(self.agents)} 个Agent")
    
    def _load_agent_configs(self):

        if not self.config_dir:
            logger.info(f"未找到配置目录，跳过配置加载")

            return
        
        config_files = list(self.config_dir.glob("*.json"))

        for config_file in config_files:
            try:
                with open(config_file, "r", encoding = "utf-8") as f:
                    config_data = json.load(f)
                
                for agent_key, agent_data in config_data.items():
                    if self._validate_agent_config(agent_data):
                        agent_config = AgentConfig(
                            id = agent_data.get("model_id",""),
                            name = agent_data.get("name",agent_key),
                            base_name = agent_data.get("base_name",agent_key),
                            system_prompt = agent_data.get("system_prompt", f"You are a helpful AI assistant named {agent_data.get('name', agent_key)}."),
                            max_output_tokens = agent_data.get("max_output_tokens",40000),
                            temperature = agent_data.get("temperature",0.7),
                            description = agent_data.get("description", f"Assistant {agent_data.get('name', agent_key)}."),
                            model_provider = agent_data.get("model_provider","openai"),
                            api_base_url = agent_data.get("api_base_url",""),
                            api_key = agent_data.get("api_key",""),
                        )
                        self.agents[agent_key] = agent_config
                        logger.info(f"已加载Agent: {agent_key} ({agent_config.name})")
            except Exception as e:
                logger.error(f"加载配置文件 {config_file} 失败: {e}")
    
    def _validate_agent_config(self, config: Dict[str, Any]) -> bool:

        required_fields = ['model_id', 'name']
        for field in required_fields:
            if field not in config or not config[field]:
                logger.warning(f"Agent配置缺少必需字段: {field}")
                return False
        return True

    def get_agent_session_history(self, agent_name: str, session_id: str = 'default_user_session') -> List[Dict[str, str]]:

        if agent_name not in self.agent_sessions:
            self.agent_sessions[agent_name] = {}
        agent_sessions = self.agent_sessions[agent_name]
        if session_id not in agent_sessions or self._is_context_expired(agent_sessions[session_id].timestamp):
            agent_sessions[session_id] = AgentSession(session_id=session_id)

        return agent_sessions[session_id].history
    
    def update_agent_session_history(self, agent_name: str, user_message: str, assistant_message: str, session_id: str = 'default_user_session'):

        if agent_name not in self.agent_sessions:
            self.agent_sessions[agent_name] = {}
        agent_sessions = self.agent_sessions[agent_name]
        if session_id not in agent_sessions or self._is_context_expired(agent_sessions[session_id].timestamp):
            agent_sessions[session_id] = AgentSession(session_id=session_id)
        session_data = agent_sessions[session_id]
        session_data.history.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_message}
        ])
        session_data.timestamp = time.time()
        max_messages = self.max_history_rounds * 2
        if len(session_data.history) > max_messages:
            session_data.history = session_data.history[-max_messages:]
    
    def _is_context_expired(self, timestamp: float) -> bool:

        return (time.time() - timestamp) > (self.context_ttl_hours * 3600)
    
    async def _periodic_cleanup(self):

        while True:
            try:
                await asyncio.sleep(3600)
                if self.debug_mode:
                    logger.debug("执行定期上下文清理...")
                for agent_name, sessions in list(self.agent_sessions.items()):
                    for session_id, session_data in list(sessions.items()):
                        if self._is_context_expired(session_data.timestamp):
                            sessions.pop(session_id, None)
                            if self.debug_mode:
                                logger.debug(f"清理过期上下文: {agent_name}, session {session_id}")
                    if not sessions:
                        self.agent_sessions.pop(agent_name, None)
            except Exception as e:
                logger.error(f"定期上下文清理失败: {e}")
    
    def _replace_placeholders(self, text: str, agent_config: AgentConfig) -> str:

        if not text:

            return ""
        processed_text = str(text)
        if agent_config:
            processed_text = processed_text.replace("{{AgentName}}", agent_config.name)
            processed_text = processed_text.replace("{{MaidName}}", agent_config.name)
            processed_text = processed_text.replace("{{BaseName}}", agent_config.base_name)
            processed_text = processed_text.replace("{{Description}}", agent_config.description)
            processed_text = processed_text.replace("{{ModelId}}", agent_config.id)
            processed_text = processed_text.replace("{{Temperature}}", str(agent_config.temperature))
            processed_text = processed_text.replace("{{MaxTokens}}", str(agent_config.max_output_tokens))
            processed_text = processed_text.replace("{{ModelProvider}}", agent_config.model_provider)
            processed_text = processed_text.replace("{{ApiBaseUrl}}", agent_config.api_base_url)
            processed_text = processed_text.replace("{{ApiKey}}", agent_config.api_key)
        import os
        import re
        env_pattern = r'\{\{([A-Z_][A-Z0-9_]*)\}\}'
        for match in re.finditer(env_pattern, processed_text):
            env_var_name = match.group(1)
            env_value = os.getenv(env_var_name, '')
            processed_text = processed_text.replace(f"{{{{{env_var_name}}}}}", env_value)
        
        from datetime import datetime
        now = datetime.now()
        processed_text = processed_text.replace("{{CurrentTime}}", now.strftime("%H:%M:%S"))
        processed_text = processed_text.replace("{{CurrentDate}}", now.strftime("%Y-%m-%d"))
        processed_text = processed_text.replace("{{CurrentDateTime}}", now.strftime("%Y-%m-%d %H:%M:%S"))

        return processed_text
    
    def _build_system_message(self, agent_config: AgentConfig) -> Dict[str, str]:

        processed_system_prompt = self._replace_placeholders(agent_config.system_prompt, agent_config)

        return {
            "role": "system",
            "content": processed_system_prompt
        }
    
    def _build_user_message(self, prompt: str, agent_config: AgentConfig) -> Dict[str, str]:

        processed_prompt = self._replace_placeholders(prompt, agent_config)

        return {
            "role": "user",
            "content": processed_prompt
        }
    
    def _build_assistant_message(self, content: str) -> Dict[str, str]:

        return {
            "role": "assistant",
            "content": content
        }
    
    def _validate_messages(self, messages: List[Dict[str, str]]) -> bool:

        if not messages:
            return False
        
        for message in messages:
            if not isinstance(message, dict):
                return False
            if 'role' not in message or 'content' not in message:
                return False
            if message['role'] not in ['system', 'user', 'assistant']:
                return False
            if not isinstance(message['content'], str):
                return False
        if messages[0]['role'] != 'system':
            return False

        return True
    
    async def call_agent(self, agent_name: str, prompt: str, session_id: str = None) -> Dict[str, Any]:

        if agent_name not in self.agents:
            available_agents = list(self.agents.keys())
            error_msg = f"请求的Agent '{agent_name}' 未找到或未正确配置。"
            if available_agents:
                error_msg += f" 已加载的Agent: {', '.join(available_agents)}。"
            else:
                error_msg += "未检测到Agent"
            error_msg += " 请确认您请求的Agent名称是否准确。"
            logger.error(f"Agent调用失败: {error_msg}")
            
            return {"status": "error", "error": error_msg}
        agent_config = self.agents[agent_name]
        if not session_id:
            session_id = f"agent_{agent_config.base_name}_default_user_session"
        try:
            history = self.get_agent_session_history(agent_name, session_id)
            messages = []

            system_message = self._build_system_message(agent_config)
            messages.append(system_message)
            
            messages.extend(history)
            user_message = self._build_user_message(prompt, agent_config)
            messages.append(user_message)
            if not self._validate_messages(messages):
                return {"status": "error", "error": "消息序列格式无效"}
            if self.debug_mode:
                logger.debug(f"Agent调用消息序列:")
                for i, msg in enumerate(messages):
                    logger.debug(f"  [{i}] {msg['role']}: {msg['content'][:100]}...")
            response = await self._call_llm_api(agent_config, messages)

            if response.get("status") == "success":
                assistant_response = response.get("result", "")
                self.update_agent_session_history(agent_name, user_message['content'], assistant_response, session_id)
                return {"status": "success", "result": assistant_response}
            else:
                return response
        except Exception as e:
            error_msg = f"调用Agent '{agent_name}' 时发生错误: {str(e)}"
            logger.error(f"Agent调用异常: {error_msg}")
            return {"status": "error", "error": error_msg}
    
    async def _call_llm_api(self, agent_config: AgentConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:

        try:
            from openai import AsyncOpenAI
            if self.debug_mode:
                logger.debug(f"调用LLM API - Agent: {agent_config.name}")
                logger.debug(f"  模型: {agent_config.id}")
                logger.debug(f"  消息序列: {messages}")
                logger.debug(f"  温度: {agent_config.temperature}")
                logger.debug(f"  最大Token: {agent_config.max_output_tokens}")
                logger.debug(f"  消息数量: {len(messages)}")

            if not agent_config.id:
                return {"status": "error", "error": "Agent配置缺少模型ID"}
            if not agent_config.api_key:
                return {"status": "error", "error": "Agent配置缺少API密钥"}
            client = AsyncOpenAI(
                api_key=agent_config.api_key,
                base_url=agent_config.api_base_url or "https://api.deepseek.com/v1"
            )
            api_params = {
                "model": agent_config.id,
                "messages": messages,
                "max_tokens": agent_config.max_output_tokens,
                "temperature": agent_config.temperature,
                "stream": False
            }
            if self.debug_mode:
                logger.debug(f"API调用参数: {api_params}")
            
            response = await client.chat.completions.create(**api_params)
            assistant_content = response.choices[0].message.content
            if self.debug_mode:
                usage = response.usage
                logger.debug(f"API响应成功:")
                logger.debug(f"  使用Token: {usage.prompt_tokens} (输入) + {usage.completion_tokens} (输出) = {usage.total_tokens} (总计)")
                logger.debug(f"  响应长度: {len(assistant_content)} 字符")
            return {"status": "success", "result": assistant_content}

        except Exception as e:
            error_msg = f"LLM API调用失败: {str(e)}"
            logger.error(f"Agent '{agent_config.name}' API调用失败: {error_msg}")
            if self.debug_mode:
                import traceback
                logger.debug(f"详细错误信息:")
                logger.debug(traceback.format_exc())

            return {"status": "error", "error": error_msg}
    
    def get_available_agents(self) -> List[Dict[str, Any]]:

        return [
            {
                "name": agent_config.name,
                "base_name": agent_config.base_name,
                "description": agent_config.description,
                "model_id": agent_config.id,
                "temperature": agent_config.temperature,
                "max_output_tokens": agent_config.max_output_tokens
            }
            for agent_config in self.agents.values()
        ]
    
    def get_agent_info(self, agent_name: str) -> Optional[Dict[str, Any]]:

        if agent_name not in self.agents:
            return None
        
        agent_config = self.agents[agent_name]
        return {
            "name": agent_config.name,
            "base_name": agent_config.base_name,
            "description": agent_config.description,
            "model_id": agent_config.id,
            "temperature": agent_config.temperature,
            "max_output_tokens": agent_config.max_output_tokens
        }
    
    def reload_configs(self):
        
        self.agents.clear()
        self._load_agent_configs()
        logger.info("Agent配置已重新加载")

    def _register_agent_from_manifest(self, agent_name: str, agent_config: Dict[str, Any]):

        try:
            if not self._validate_agent_config(agent_config):
                logger.warning(f"Agent配置验证失败: {agent_name}")
                return False
            
            agent_config_obj = AgentConfig(
                id = agent_config.get("model_id", ""),
                name = agent_config.get("name", agent_name),
                base_name = agent_config.get("base_name", agent_name),
                system_prompt = agent_config.get("system_prompt", f"You are a helpful AI assistant named {agent_config.get('name', agent_name)}."),
                max_output_tokens = agent_config.get("max_output_tokens", 8192),
                temperature = agent_config.get("temperature", 0.7),
                description = agent_config.get("description", f"Assistant {agent_config.get('name', agent_name)}."),
                model_provider = agent_config.get("model_provider", "openai"),
                api_base_url = agent_config.get("api_base_url", ""),
                api_key = agent_config.get("api_key", ""))
            
            self.agents[agent_name] = agent_config_obj
            logger.info(f"已从manifest注册Agent: {agent_name} ({agent_config_obj.name})")
            return True
        except Exception as e:
            logger.error(f"从manifest注册Agent失败 {agent_name}: {e}")
            return False
    
    async def call_agent_by_action(self, agent_name: str, action_args: Dict[str, Any]) -> str:

        try:
            if agent_name not in self.agents:
                return f"Agent '{agent_name}' 未找到或未正确配置"
            agent_config = self.agents[agent_name]
            action = action_args.get('action', '')
            user_prompt = self._build_action_prompt(action, action_args)
            result = await self.call_agent(agent_name, user_prompt)
            if result.get("status") == "success":
                return result.get("result", "")
            else:
                return result.get("error", "调用失败")
        except Exception as e:
            logger.error(f"Agent调用异常: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _build_action_prompt(self, action: str, action_args: Dict[str, Any]) -> str:

        clean_args = {k: v for k, v in action_args.items() 
                     if k not in ['service_name', 'action']}
        
        if clean_args:
            args_str = ", ".join([f"{k}: {v}" for k, v in clean_args.items()])
            return f"请执行动作 '{action}'，参数: {args_str}"
        else:
            return f"请执行动作 '{action}'"

_AGENT_MANAGER = None

def get_agent_manager() -> AgentManager:

    global _AGENT_MANAGER
    if _AGENT_MANAGER is None:
        _AGENT_MANAGER = AgentManager()
    return _AGENT_MANAGER

async def call_agent(agent_name: str, prompt: str, session_id: str = None) -> Dict[str, Any]:

    manager = get_agent_manager()
    return await manager.call_agent(agent_name, prompt, session_id)

def list_agents() -> List[Dict[str, Any]]:

    manager = get_agent_manager()
    return manager.get_available_agents()

def get_agent_info(agent_name: str) -> Optional[Dict[str, Any]]:

    manager = get_agent_manager()
    return manager.get_agent_info(agent_name)

        