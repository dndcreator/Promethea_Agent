"""
电脑控制模块 - Computer Control Module
提供浏览器、屏幕、键鼠、文件系统、进程管理等电脑控制能力
"""
from .base import ComputerController, ComputerCapability, ComputerResult
from .browser import BrowserController
from .screen import ScreenController
from .filesystem import FileSystemController
from .process import ProcessController

__all__ = [
    'ComputerController',
    'ComputerCapability',
    'ComputerResult',
    'BrowserController',
    'ScreenController',
    'FileSystemController',
    'ProcessController',
]
