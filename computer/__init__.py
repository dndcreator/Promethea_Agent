"""
"""
from importlib import import_module
from typing import TYPE_CHECKING

from .base import ComputerController, ComputerCapability, ComputerResult

if TYPE_CHECKING:
    from .browser import BrowserController
    from .screen import ScreenController
    from .filesystem import FileSystemController
    from .process import ProcessController
    from .environment import EnvironmentController

_CONTROLLER_MODULES = {
    "BrowserController": ".browser",
    "ScreenController": ".screen",
    "FileSystemController": ".filesystem",
    "ProcessController": ".process",
    "EnvironmentController": ".environment",
}

__all__ = [
    'ComputerController',
    'ComputerCapability',
    'ComputerResult',
    'BrowserController',
    'ScreenController',
    'FileSystemController',
    'ProcessController',
    'EnvironmentController',
]


def __getattr__(name: str):
    module_name = _CONTROLLER_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name, __name__), name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
