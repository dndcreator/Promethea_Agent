"""
电脑控制基类
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger("Computer.Base")


class ComputerCapability(str, Enum):
    """电脑能力枚举"""
    BROWSER = "browser"          # 浏览器控制
    SCREEN = "screen"            # 屏幕捕获
    KEYBOARD = "keyboard"        # 键盘输入
    MOUSE = "mouse"              # 鼠标控制
    FILESYSTEM = "filesystem"    # 文件系统
    PROCESS = "process"          # 进程管理
    CLIPBOARD = "clipboard"      # 剪贴板
    SCREENSHOT = "screenshot"    # 截图


class ComputerAction(BaseModel):
    """电脑操作模型"""
    capability: ComputerCapability
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30  # 秒


class ComputerResult(BaseModel):
    """操作结果"""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    screenshot: Optional[str] = None  # Base64编码的截图
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ComputerController(ABC):
    """电脑控制器基类"""
    
    def __init__(self, name: str, capability: ComputerCapability):
        self.name = name
        self.capability = capability
        self.is_initialized = False
        self.logger = logging.getLogger(f"Computer.{name}")
    
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化控制器"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> bool:
        """清理资源"""
        pass
    
    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        """执行操作"""
        pass
    
    @abstractmethod
    def get_available_actions(self) -> List[Dict[str, Any]]:
        """获取可用操作列表"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """获取控制器状态"""
        return {
            "name": self.name,
            "capability": self.capability.value,
            "initialized": self.is_initialized
        }
