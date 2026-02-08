from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class PluginKind(str, Enum):
    channel = "channel"
    memory = "memory"
    tools = "tools"
    service = "service"


class PluginDiagnostic(BaseModel):
    level: str = Field(default="info")  # info|warn|error
    plugin_id: Optional[str] = None
    source: Optional[str] = None
    message: str


class PluginManifest(BaseModel):
    id: str
    kind: Optional[PluginKind] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None

    # Moltbot-style: require a config schema field even if we don't fully validate yet
    config_schema: Dict[str, Any] = Field(default_factory=dict, alias="configSchema")


class PluginCandidate(BaseModel):
    root_dir: str
    source: str
    origin: str = "local"
    workspace_dir: Optional[str] = None


class ChannelEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    channel_id: str
    channel: Any
    source: str


class ServiceEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    service_id: str
    service: Any
    source: str


class PluginRecord(BaseModel):
    id: str
    source: str
    enabled: bool = True
    status: str = "loaded"  # loaded|disabled|error
    error: Optional[str] = None
    kind: Optional[PluginKind] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None


class PluginRegistry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plugins: List[PluginRecord] = Field(default_factory=list)
    channels: List[ChannelEntry] = Field(default_factory=list)
    services: List[ServiceEntry] = Field(default_factory=list)
    diagnostics: List[PluginDiagnostic] = Field(default_factory=list)

