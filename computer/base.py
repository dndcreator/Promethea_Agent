"""
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger("Computer.Base")


class ComputerCapability(str, Enum):
    """TODO: add docstring."""
    BROWSER = "browser"          # Browser control
    SCREEN = "screen"
    KEYBOARD = "keyboard"        # TODO: comment cleaned
    MOUSE = "mouse"              # Mouse control
    FILESYSTEM = "filesystem"    # TODO: comment cleaned
    PROCESS = "process"
    CLIPBOARD = "clipboard"      # Clipboard access
    SCREENSHOT = "screenshot"    # TODO: comment cleaned


class ComputerAction(BaseModel):
    """TODO: add docstring."""
    capability: ComputerCapability
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30


class ComputerResult(BaseModel):
    """TODO: add docstring."""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    screenshot: Optional[str] = None  # Base64-encoded screenshot
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComputerController(ABC):
    """TODO: add docstring."""
    
    def __init__(self, name: str, capability: ComputerCapability):
        self.name = name
        self.capability = capability
        self.is_initialized = False
        self.logger = logging.getLogger(f"Computer.{name}")
    
    @abstractmethod
    async def initialize(self) -> bool:
        pass
    
    @abstractmethod
    async def cleanup(self) -> bool:
        pass
    
    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        pass
    
    @abstractmethod
    def get_available_actions(self) -> List[Dict[str, Any]]:
        pass
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability.value,
            "initialized": self.is_initialized
        }
