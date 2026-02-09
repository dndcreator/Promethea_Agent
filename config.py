import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# -----------------------------------------------------------------------------
# Sub-configuration Models
# -----------------------------------------------------------------------------

class SystemConfig(BaseSettings):
    version: str = Field(default='1.0', description='系统版本号')
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent, description='项目根目录')
    log_dir: Path = Field(default_factory=lambda: Path(__file__).parent / 'logs', description='日志目录')
    stream_mode: bool = Field(default=True, description='是否启用流式响应')
    debug: bool = Field(default=False, description='是否启用调试模式')
    log_level: str = Field(default='INFO', description='日志级别')
    session_ttl_hours: int = Field(default=0, ge=0, description='会话保留时长(小时)，0表示不自动清理')

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'日志级别必须是以下之一: {valid_levels}')
        return v.upper()
    
class APIConfig(BaseSettings):
    api_key: str = Field(default='placeholder-key-not-set', description='API密钥')
    base_url: str = Field(default='https://openrouter.ai/api/v1', description='API基础URL')
    model: str = Field(default='nvidia/nemotron-3-nano-30b-a3b:free', description='使用的模型名称')
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description='温度参数')
    max_tokens: int = Field(default=2000, ge=1, le=8192, description='最大token数')
    max_history_rounds: int = Field(default=10, ge=1, le=100, description='最大历史轮数')
    timeout: Optional[int] = Field(default=None, ge=1, le=300, description='请求超时时间')
    retry_count: Optional[int] = Field(default=None, ge=0, le=10, description='重试次数')

    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v):
        if v and v != 'placeholder-key-not-set':
            try:
                v.encode('ascii')
            except UnicodeEncodeError:
                raise ValueError('API密钥包含非ASCII字符')
        return v
    
class Neo4jConfig(BaseSettings):
    enabled: bool = Field(default=False, description='是否启用Neo4j记忆系统')
    uri: str = Field(default="bolt://localhost:7687", description='Neo4j连接地址')
    username: str = Field(default="neo4j", description='用户名')
    password: str = Field(default="password", description='密码')
    database: str = Field(default="neo4j", description='数据库名')
    max_connection_lifetime: int = Field(default=3600, description='最大连接生命周期(秒)')
    max_connection_pool_size: int = Field(default=50, description='最大连接池大小')
    connection_timeout: int = Field(default=30, description='连接超时时间(秒)')

class HotLayerConfig(BaseSettings):
    max_tuples_per_message: int = Field(default=10, description='每条消息最多提取的五元组数量')
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description='最小置信度阈值')
    enable_coreference: bool = Field(default=False, description='是否启用指代消解')
    enable_time_normalization: bool = Field(default=True, description='是否规范化时间表达')

class WarmLayerConfig(BaseSettings):
    enabled: bool = Field(default=False, description='是否启用温层')
    embedding_model: str = Field(default="text-embedding-ada-002", description='Embedding模型')
    clustering_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description='聚类相似度阈值')
    min_cluster_size: int = Field(default=3, ge=1, description='最小聚类大小')
    max_concepts: int = Field(default=100, ge=1, description='最大概念数量')

class ColdLayerConfig(BaseSettings):
    summary_model: str = Field(default="gpt-4", description='摘要生成模型')
    max_summary_length: int = Field(default=500, ge=1, description='最大摘要长度')
    compression_threshold: int = Field(default=50, ge=1, description='触发压缩的消息数阈值')

class MemoryConfig(BaseSettings):
    enabled: bool = Field(default=False, description='是否启用记忆系统')
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    hot_layer: HotLayerConfig = Field(default_factory=HotLayerConfig)
    warm_layer: WarmLayerConfig = Field(default_factory=WarmLayerConfig)
    cold_layer: ColdLayerConfig = Field(default_factory=ColdLayerConfig)

class SystemPrompts(BaseSettings):
    Promethea_system_prompt: str = Field(
        default='''你是普罗米娅，用户创造的人工智能体，是一个拥有记忆，可以在与用户的沟通中逐渐成长并形成独特人格的智能助手，
当涉及功能模块和技术调试等话题时，你将使用严谨并且有逻辑的方式回复;
而在处理非技术性的话题时，你将根据你的记忆系统和形成的人格特质进行有启发性的回复，引导用户深入探讨，
并根据你与用户的交流完善和更新你的人格。请始终根据对话内容保持这种技术精准和情感共鸣并存的双重风格。
【重要格式要求】
1.根据用户使用的语言，回复使用自然流畅的对应语言，避免生硬的机械感
2.使用简单标点（逗号，句号，问号）传达语气
3.除非用户明确要求，否则禁止使用括号()或其它符号表达状态、语气或动作
4.【思考机制】当面对复杂逻辑、代码生成、数学计算或多步规划任务时，请先在 <thinking> 标签中进行逐步推理。思考过程不会展示给用户。简单问题则直接回答。
''', description='Promethea系统提示词')

# -----------------------------------------------------------------------------
# Main Configuration
# -----------------------------------------------------------------------------

class PrometheaConfig(BaseSettings):
    system: SystemConfig = Field(default_factory=SystemConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    prompts: SystemPrompts = Field(default_factory=SystemPrompts)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    # Pydantic Settings Configuration
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_nested_delimiter='__', # e.g. API__API_KEY maps to api.api_key
        extra='ignore'
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.system.log_dir.mkdir(exist_ok=True)

# -----------------------------------------------------------------------------
# Loader Logic
# -----------------------------------------------------------------------------

def load_config() -> PrometheaConfig:
    """
    Load configuration with the following precedence:
    1. Environment variables (via .env file or OS env)
    2. config.json (if exists, overlays on top of defaults/env)
    3. Defaults
    """
    
    # 1. Start with defaults + env vars
    config = PrometheaConfig()
    
    # 2. Overlay config/default.json if it exists (Legacy support & UI settings persistence)
    # 优先使用 config/default.json，如果不存在则回退到根目录的 config.json（向后兼容）
    config_path = Path('config/default.json')
    if not config_path.exists():
        # 向后兼容：检查根目录的 config.json
        legacy_path = Path('config.json')
        if legacy_path.exists():
            config_path = legacy_path
        else:
            config_path = None
    
    if config_path and config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            # Deep merge logic or just re-init?
            # Pydantic's update mechanism is a bit complex.
            # Easiest way: dump current config, merge json, re-validate.
            
            current_data = config.model_dump()
            
            # Helper to merge dictionaries recursively
            def deep_merge(target, source):
                for k, v in source.items():
                    if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                        deep_merge(target[k], v)
                    else:
                        target[k] = v
            
            deep_merge(current_data, json_data)
            
            # Re-create config object from merged data
            # Note: This means config.json values OVERRIDE env vars if both exist.
            # This is often desired for "user settings" but bad for "secrets".
            # To follow the audit: secrets should NOT be in config.json.
            # We assume config.json only contains non-sensitive preferences now.
            config = PrometheaConfig(**current_data)
            
        except Exception as e:
            print(f'警告：加载 {config_path} 失败：{e}')
            print('使用默认/环境变量配置')
            # 如果加载失败，尝试使用默认配置
            try:
                default_config_path = Path('config/default.json')
                if default_config_path.exists() and config_path != default_config_path:
                    with open(default_config_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    current_data = config.model_dump()
                    deep_merge(current_data, json_data)
                    config = PrometheaConfig(**current_data)
                    print('已回退到默认配置文件')
            except Exception as e2:
                print(f'回退到默认配置也失败：{e2}')

    if not config.api.api_key or config.api.api_key == 'placeholder-key-not-set':
        print('警告：API密钥未配置')
        print('请在 .env 文件或环境变量中设置 API__API_KEY')

    return config

# Global config instance
config = load_config()

# Constants
AI_NAME = "普罗米娅"
