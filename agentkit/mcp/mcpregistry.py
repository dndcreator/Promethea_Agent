from datetime import datetime
import sys
import json
import importlib
from pathlib import Path
from typing import Optional, Dict, Any, List
import types



MCP_REGISTRY = {}
MANIFEST_CACHE = {}

def load_tools_manifest(manifest_path: Path) -> Optional[Dict[str, Any]]:

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"加载manifest文件失败 {manifest_path}: {e}\n")
        return None

def create_service_instance(manifest: Dict[str, Any]) -> Optional[Any]:

    try:
        entry_point = manifest.get('entryPoint', {})
        module_name = entry_point.get('module')
        class_name = entry_point.get('class')
        if not module_name or not class_name:
            sys.stderr.write(f"manifest缺少entryPoint信息: {manifest.get('name', 'unknown')}\n")
            return None
        
        # 动态导入模块
        module = importlib.import_module(module_name)
        service_class = getattr(module, class_name)
        
        # 创建实例
        instance = service_class()

        return instance
    except Exception as e:
        sys.stderr.write(f"创建agent实例失败 {manifest.get('name', 'unknown')}: {e}\n")

        return None

def scan_and_register_services(service_dir: str = 'agentkit') -> List[str]:

    p = Path(service_dir)
    registered_services = []

    for manifest_file in p.glob('**/agent-manifest.json'):
        try:
            manifest = load_tools_manifest(manifest_file)
            if not manifest:
                continue
            service_type = manifest.get('serviceType')
            service_name = manifest.get('name')

            if not service_name:
                sys.stderr.write(f"manifest缺少name字段: {manifest_file}\n")
                continue
            
            if service_type == 'mcp':
                MANIFEST_CACHE[service_name] = manifest
                service_instance = create_service_instance(manifest)
                if service_instance:
                    MCP_REGISTRY[service_name] = service_instance
                    registered_services.append(service_name)
            elif service_type == 'agent':
                try:
                    from agentkit.agent_manager import get_agent_manager
                    agent_manager = get_agent_manager()

                    agent_config = {
                        'model_id': manifest.get('modelId', 'deepseek-chat'),
                        'name': manifest.get('label', service_name),
                        'base_name': service_name,
                        'system_prompt': manifest.get('systemPrompt', f'You are a helpful AI assistant named {manifest.get("label", service_name)}.'),
                        'max_tokens': manifest.get('maxTokens', 8192),
                        'temperature': manifest.get('temperature', 0.7),
                        'description': manifest.get('description', f'Assistant {manifest.get("label", service_name)}.'),
                        'model_provider': manifest.get('modelProvider', 'openai'),
                        'api_base_url': manifest.get('apiBaseUrl', ''),
                        'api_key': manifest.get('apiKey', '')
                    }

                    agent_manager._register_agent_from_manifest(service_name, agent_config)
                    registered_services.append(f"agent:{service_name}")
                    sys.stderr.write(f"✅ 已注册Agent到AgentManager: {service_name}\n")
                except Exception as e:
                    sys.stderr.write(f"注册Agent到AgentManager失败 {service_name}: {e}\n")
                    continue
        except Exception as e:
            sys.stderr.write(f"扫描和注册服务失败 {manifest_file}: {e}\n")
            continue
    
    return registered_services


def get_service_info(service_name: str) -> Optional[Dict[str, Any]]:

    if service_name not in MCP_REGISTRY:
        return None

    manifest = MANIFEST_CACHE.get(service_name, {})
    instance = MCP_REGISTRY.get(service_name)

    return {
        "name": service_name,
        "manifest": manifest,
        "instance": instance,
        "description": manifest.get('description', ''),
        "label": manifest.get('label', service_name),
        "version": manifest.get('version', '1.0.0'),
        "capabilities": manifest.get('capabilities', {}),
        "input_schema": manifest.get('inputSchema', {}),
        "available_tools": get_available_tools(service_name)
    }

def get_available_tools(service_name: str) -> List[Dict[str, Any]]:

    if service_name not in MCP_REGISTRY:
        return []
    manifest = MANIFEST_CACHE.get(service_name, {})
    capabilities = manifest.get('capabilities', {})
    invocation_commands = capabilities.get("invocation_commands", [])

    tools = []
    for command in invocation_commands:
        tools.append({
            "name": command.get('command', ''),
            "description": command.get('description', ''),
            "example": command.get('example', ''),
            "input_schema": manifest.get('inputSchema', {})
        })
    return tools

def get_all_services_info() -> Dict[str, Any]:

    services_info = {}
    for service_name in MCP_REGISTRY.keys():
        service_info = get_service_info(service_name)
        if service_info:
            services_info[service_name] = service_info
    
    return services_info

def query_services_by_capability(capability: str) -> List[str]:

    matching_services = []
    for service_name, manifest in MANIFEST_CACHE.items():
        description = manifest.get('description', '').lower()
        label = manifest.get('label', '').lower()
        if capability.lower() in description or capability.lower() in label:
            matching_services.append(service_name)
    
    return matching_services

def service_statistics() -> Dict[str, Any]:

    return {
        "total_services": len(MCP_REGISTRY),
        "total_tools": sum(len(get_available_tools(name)) for name in MCP_REGISTRY.keys()),
        "registered_services": list(MCP_REGISTRY.keys()),
        "last_update": datetime.utcnow().isoformat() + 'Z'
    }

def auto_registry():

    registered = scan_and_register_services()
    sys.stderr.write(f"MCP注册完成，共注册 {len(registered)} 个服务: {registered}\n")

    return registered

# 显式初始化函数
def initialize_mcp_registry(scan_dir: str = 'agentkit', force: bool = False) -> List[str]:
    """显式初始化 MCP 注册表
    
    Args:
        scan_dir: 扫描目录
        force: 是否强制重新扫描
    """
    if force or not is_initialized():
        return scan_and_register_services(scan_dir)
    return list(MCP_REGISTRY.keys())

# 状态检查函数
def is_initialized() -> bool:
    """检查是否已初始化"""
    return len(MCP_REGISTRY) > 0

# 便捷包装，供MCPManager调用
def get_service_statistics() -> Dict[str, Any]:
    return service_statistics()

# MVP 内置服务：当没有任何服务时，注册一个内置工具集合
def ensure_builtin_service():
    if MCP_REGISTRY:
        return []
    class BuiltinService:
        def __init__(self):
            self.name = "builtin"
        async def echo(self, text: str = "") -> str:
            return text
        async def sum(self, a: float = 0, b: float = 0) -> float:
            try:
                return float(a) + float(b)
            except Exception:
                return 0.0
        async def handle_handoff(self, task: Dict[str, Any]) -> Any:
            # 简易透传
            return {"status": "success", "result": task}
    MCP_REGISTRY["builtin"] = BuiltinService()
    MANIFEST_CACHE["builtin"] = {
        "name": "builtin",
        "label": "Builtin Tools",
        "version": "0.1.0",
        "description": "Built-in minimal tools for MVP",
        "capabilities": {
            "invocation_commands": [
                {"command": "echo", "description": "Echo text"},
                {"command": "sum", "description": "Sum two numbers"}
            ]
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "a": {"type": "number"},
                "b": {"type": "number"}
            }
        }
    }
    return ["builtin"]

# 条件执行（用于测试）
if __name__ == "__main__":
    initialize_mcp_registry()