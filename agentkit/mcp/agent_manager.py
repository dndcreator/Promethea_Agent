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
            logger.warning("Failed to import config, using default history settings")
        self.context_ttl_hours = 24
        self.debug_mode = True

        if self.config_dir:
            self.config_dir.mkdir(exist_ok=True)
            self._load_agent_configs()
        else:
            logger.info("AgentManager running in MCP mode, skip external config loading")
        
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            pass
        logger.info(f"AgentManager initialized, loaded {len(self.agents)} agents")
    
    def _load_agent_configs(self):

        if not self.config_dir:
            logger.info("Config directory not found, skip agent-config loading")

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
                        logger.info(f"Loaded agent: {agent_key} ({agent_config.name})")
            except Exception as e:
                logger.error(f"Failed to load agent config file {config_file}: {e}")
    
    def _validate_agent_config(self, config: Dict[str, Any]) -> bool:

        required_fields = ['model_id', 'name']
        for field in required_fields:
            if field not in config or not config[field]:
                logger.warning(f"Agent config missing required field: {field}")
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
                    logger.debug("Running periodic agent-session context cleanup...")
                for agent_name, sessions in list(self.agent_sessions.items()):
                    for session_id, session_data in list(sessions.items()):
                        if self._is_context_expired(session_data.timestamp):
                            sessions.pop(session_id, None)
                            if self.debug_mode:
                                logger.debug(
                                    f"Cleaned expired agent session context: agent={agent_name}, session={session_id}"
                                )
                    if not sessions:
                        self.agent_sessions.pop(agent_name, None)
            except Exception as e:
                logger.error(f"Periodic agent-session context cleanup failed: {e}")
    
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
            error_msg = f"Requested agent {agent_name} is not found or not configured."
            if available_agents:
                error_msg += f" Loaded agents: {\", \".join(available_agents)}."
            else:
                error_msg += " No agent is currently loaded."
            error_msg += " Please verify the agent name."
            logger.error(f"Agent call failed: {error_msg}")
            
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
                return {"status": "error", "error": "Invalid message sequence format"}
            if self.debug_mode:
                logger.debug("Agent call message sequence:")
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
            error_msg = f"Error when calling Agent '{agent_name}': {str(e)}"
            logger.error(f"Agent call exception: {error_msg}")
            return {"status": "error", "error": error_msg}

    async def call_agent_stream(self, agent_name: str, prompt: str, session_id: str = None):
        if agent_name not in self.agents:
            available_agents = list(self.agents.keys())
            error_msg = f"Requested agent {agent_name} is not found or not configured."
            if available_agents:
                error_msg += f" Loaded agents: {\", \".join(available_agents)}."
            else:
                error_msg += " No agent is currently loaded."
            error_msg += " Please verify the agent name."
            logger.error(f"Agent stream call failed: {error_msg}")
            raise ValueError(error_msg)

        agent_config = self.agents[agent_name]
        if not session_id:
            session_id = f"agent_{agent_config.base_name}_default_user_session"

        history = self.get_agent_session_history(agent_name, session_id)
        messages = []
        system_message = self._build_system_message(agent_config)
        messages.append(system_message)
        messages.extend(history)
        user_message = self._build_user_message(prompt, agent_config)
        messages.append(user_message)

        if not self._validate_messages(messages):
            raise ValueError("Invalid message sequence format")

        if self.debug_mode:
            logger.debug("Agent stream message sequence:")
            for i, msg in enumerate(messages):
                logger.debug(f"  [{i}] {msg['role']}: {msg['content'][:100]}...")

        content_parts: List[str] = []
        async for chunk in self._call_llm_api_stream(agent_config, messages):
            if chunk:
                content_parts.append(chunk)
                yield chunk

        assistant_response = "".join(content_parts)
        if assistant_response:
            self.update_agent_session_history(
                agent_name, user_message["content"], assistant_response, session_id
            )
    
    async def _call_llm_api(self, agent_config: AgentConfig, messages: List[Dict[str, str]]) -> Dict[str, Any]:

        try:
            from openai import AsyncOpenAI
            if self.debug_mode:
                logger.debug(f"Calling LLM API - Agent: {agent_config.name}")
                logger.debug(f"  Model: {agent_config.id}")
                logger.debug(f"  Messages: {messages}")
                logger.debug(f"  Temperature: {agent_config.temperature}")
                logger.debug(f"  Max tokens: {agent_config.max_output_tokens}")
                logger.debug(f"  Message count: {len(messages)}")

            if not agent_config.id:
                return {"status": "error", "error": "Agent config missing model ID"}
            if not agent_config.api_key:
                return {"status": "error", "error": "Agent config missing API key"}
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
                logger.debug(f"API call params: {api_params}")
            
            response = await client.chat.completions.create(**api_params)
            assistant_content = response.choices[0].message.content
            if self.debug_mode:
                usage = response.usage
                logger.debug("API response success:")
                logger.debug(
                    f"  Tokens used: {usage.prompt_tokens} (in) + "
                    f"{usage.completion_tokens} (out) = {usage.total_tokens} (total)"
                )
                logger.debug(f"  Response length: {len(assistant_content)} characters")
            return {"status": "success", "result": assistant_content}

        except Exception as e:
            error_msg = f"LLM API call failed: {str(e)}"
            logger.error(f"Agent '{agent_config.name}' API call failed: {error_msg}")
            if self.debug_mode:
                import traceback
                logger.debug("Detailed error traceback:")
                logger.debug(traceback.format_exc())

            return {"status": "error", "error": error_msg}

    async def _call_llm_api_stream(self, agent_config: AgentConfig, messages: List[Dict[str, str]]):
        from openai import AsyncOpenAI

        if not agent_config.id:
            raise ValueError("Agent config missing model ID")
        if not agent_config.api_key:
            raise ValueError("Agent config missing API key")

        client = AsyncOpenAI(
            api_key=agent_config.api_key,
            base_url=agent_config.api_base_url or "https://api.deepseek.com/v1",
        )

        api_params = {
            "model": agent_config.id,
            "messages": messages,
            "max_tokens": agent_config.max_output_tokens,
            "temperature": agent_config.temperature,
            "stream": True,
        }
        if self.debug_mode:
            logger.debug(f"API stream params: {api_params}")

        stream = await client.chat.completions.create(**api_params)
        async for event in stream:
            delta = event.choices[0].delta
            content = getattr(delta, "content", None)
            if content is None and isinstance(delta, dict):
                content = delta.get("content")
            if content:
                yield content
    
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
        logger.info("Agent configs reloaded")

    def _register_agent_from_manifest(self, agent_name: str, agent_config: Dict[str, Any]):

        try:
            if not self._validate_agent_config(agent_config):
                logger.warning(f"Agent config validation failed: {agent_name}")
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
            logger.info(f"Registered Agent from manifest: {agent_name} ({agent_config_obj.name})")
            return True
        except Exception as e:
            logger.error(f"Agent registration from manifest failed for {agent_name}: {e}")
            return False
    
    async def call_agent_by_action(self, agent_name: str, action_args: Dict[str, Any]) -> str:

        try:
            if agent_name not in self.agents:
                return f"Agent {agent_name} is not found or not configured"
            agent_config = self.agents[agent_name]
            action = action_args.get('action', '')
            user_prompt = self._build_action_prompt(action, action_args)
            result = await self.call_agent(agent_name, user_prompt)
            if result.get("status") == "success":
                return result.get("result", "")
            else:
                return result.get("error", "Call failed")
        except Exception as e:
            logger.error(f"Agent call exception: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _build_action_prompt(self, action: str, action_args: Dict[str, Any]) -> str:

        clean_args = {k: v for k, v in action_args.items() 
                     if k not in ['service_name', 'action']}
        
        if clean_args:
            args_str = ", ".join([f"{k}: {v}" for k, v in clean_args.items()])
            return f"Please perform action '{action}' with arguments: {args_str}"
        else:
            return f"Please perform action '{action}'"

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

        
