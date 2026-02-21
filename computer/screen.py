"""
Screen and input controller - based on PyAutoGUI.
"""
from typing import Dict, Any, List, Optional, Tuple
from .base import ComputerController, ComputerCapability, ComputerResult
import logging
import base64
from io import BytesIO

logger = logging.getLogger("Computer.Screen")


class ScreenController(ComputerController):
    """Screen + mouse + keyboard controller."""
    
    def __init__(self):
        super().__init__("Screen", ComputerCapability.SCREEN)
        self.pyautogui = None
        self.pil_image = None
    
    async def initialize(self) -> bool:
        """Initialize screen controller (PyAutoGUI + Pillow)."""
        try:
            # Lazy-import PyAutoGUI to avoid hard dependency at import time.
            import pyautogui
            from PIL import Image
            
            self.pyautogui = pyautogui
            self.pil_image = Image
            
            # Configure safety options.
            self.pyautogui.FAILSAFE = True  # Move mouse to corner to abort.
        self.pyautogui.PAUSE = 0.1      # Small pause after each action.
            
            self.is_initialized = True
            logger.info("Screen controller initialized")
            return True
            
        except ImportError:
            logger.error("PyAutoGUI not installed. Run: pip install pyautogui pillow")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize screen controller: {e}")
            return False
    
    async def cleanup(self) -> bool:
        """Clean up screen-controller resources."""
        self.is_initialized = False
        logger.info("Screen controller cleaned up")
        return True
    
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        """Execute screen / mouse / keyboard operation."""
        if not self.is_initialized:
            return ComputerResult(
                success=False,
                error="Screen controller not initialized"
            )
        
        try:
            action_map = {
                # Mouse actions
                'move': self._move_mouse,
                'click': self._click,
                'double_click': self._double_click,
                'right_click': self._right_click,
                'drag': self._drag,
                'scroll': self._scroll,
                
                # Keyboard actions
                'type': self._type,
                'press': self._press,
                'hotkey': self._hotkey,
                
                # Screen actions
                'screenshot': self._screenshot,
                'locate': self._locate_on_screen,
                'get_screen_size': self._get_screen_size,
                'get_mouse_position': self._get_mouse_position,
                
                # Clipboard actions
                'get_clipboard': self._get_clipboard,
                'set_clipboard': self._set_clipboard,
            }
            
            handler = action_map.get(action)
            if not handler:
                return ComputerResult(
                    success=False,
                    error=f"Unknown action: {action}"
                )
            
            result = await handler(params)
            return ComputerResult(success=True, result=result)
            
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return ComputerResult(success=False, error=str(e))
    
    def get_available_actions(self) -> List[Dict[str, Any]]:
        """Return available screen and input actions."""
        return [
            # Mouse actions
            {"name": "move", "description": "Move mouse", "params": ["x", "y", "duration?"]},
            {"name": "click", "description": "Click", "params": ["x?", "y?", "button?"]},
            {"name": "double_click", "description": "Double click", "params": ["x?", "y?"]},
            {"name": "right_click", "description": "Right click", "params": ["x?", "y?"]},
            {"name": "drag", "description": "Drag", "params": ["x1", "y1", "x2", "y2", "duration?"]},
            {"name": "scroll", "description": "Scroll", "params": ["clicks", "x?", "y?"]},
            
            # Keyboard actions
            {"name": "type", "description": "Type text", "params": ["text", "interval?"]},
            {"name": "press", "description": "Press key", "params": ["key", "presses?", "interval?"]},
            {"name": "hotkey", "description": "Hotkey", "params": ["keys"]},
            
            # Screen actions
            {"name": "screenshot", "description": "Take screenshot", "params": ["region?", "path?"]},
            {"name": "locate", "description": "Locate image", "params": ["image_path"]},
            {"name": "get_screen_size", "description": "Get screen size", "params": []},
            {"name": "get_mouse_position", "description": "Get mouse position", "params": []},
            
            # Clipboard helpers
            {"name": "get_clipboard", "description": "Get clipboard", "params": []},
            {"name": "set_clipboard", "description": "Set clipboard", "params": ["text"]},
        ]
    
    # ============ Mouse actions ============
    
    async def _move_mouse(self, params: Dict[str, Any]) -> str:
        """Move mouse to target position."""
        x = params.get('x')
        y = params.get('y')
        duration = params.get('duration', 0.2)
        
        if x is None or y is None:
            raise ValueError("Missing required parameters: x, y")
        
        self.pyautogui.moveTo(x, y, duration=duration)
        return f"Moved mouse to ({x}, {y})"
    
    async def _click(self, params: Dict[str, Any]) -> str:
        """Click at optional (x, y) with given button."""
        x = params.get('x')
        y = params.get('y')
        button = params.get('button', 'left')
        
        if x is not None and y is not None:
            self.pyautogui.click(x, y, button=button)
            return f"Clicked at ({x}, {y}) with {button} button"
        else:
            self.pyautogui.click(button=button)
            return f"Clicked with {button} button at current position"
    
    async def _double_click(self, params: Dict[str, Any]) -> str:
        """Double-click at optional (x, y)."""
        x = params.get('x')
        y = params.get('y')
        
        if x is not None and y is not None:
            self.pyautogui.doubleClick(x, y)
            return f"Double clicked at ({x}, {y})"
        else:
            self.pyautogui.doubleClick()
            return "Double clicked at current position"
    
    async def _right_click(self, params: Dict[str, Any]) -> str:
        """Right-click at optional (x, y)."""
        x = params.get('x')
        y = params.get('y')
        
        if x is not None and y is not None:
            self.pyautogui.rightClick(x, y)
            return f"Right clicked at ({x}, {y})"
        else:
            self.pyautogui.rightClick()
            return "Right clicked at current position"
    
    async def _drag(self, params: Dict[str, Any]) -> str:
        """Drag from (x1, y1) to (x2, y2)."""
        x1 = params.get('x1')
        y1 = params.get('y1')
        x2 = params.get('x2')
        y2 = params.get('y2')
        duration = params.get('duration', 0.5)
        
        if None in (x1, y1, x2, y2):
            raise ValueError("Missing required parameters: x1, y1, x2, y2")
        
        self.pyautogui.moveTo(x1, y1, duration=0.1)
        self.pyautogui.dragTo(x2, y2, duration=duration, button='left')
        return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})"
    
    async def _scroll(self, params: Dict[str, Any]) -> str:
        """Scroll vertically, optionally at (x, y)."""
        clicks = params.get('clicks')
        x = params.get('x')
        y = params.get('y')
        
        if clicks is None:
            raise ValueError("Missing required parameter: clicks")
        
        if x is not None and y is not None:
            self.pyautogui.scroll(clicks, x, y)
            return f"Scrolled {clicks} clicks at ({x}, {y})"
        else:
            self.pyautogui.scroll(clicks)
            return f"Scrolled {clicks} clicks"
    
    # ============ Keyboard actions ============
    
    async def _type(self, params: Dict[str, Any]) -> str:
        """Type text with optional interval between characters."""
        text = params.get('text')
        interval = params.get('interval', 0.05)
        
        if text is None:
            raise ValueError("Missing required parameter: text")
        
        self.pyautogui.write(text, interval=interval)
        return f"Typed: {text}"
    
    async def _press(self, params: Dict[str, Any]) -> str:
        """Press a key one or more times."""
        key = params.get('key')
        presses = params.get('presses', 1)
        interval = params.get('interval', 0.1)
        
        if key is None:
            raise ValueError("Missing required parameter: key")
        
        self.pyautogui.press(key, presses=presses, interval=interval)
        return f"Pressed {key} {presses} times"
    
    async def _hotkey(self, params: Dict[str, Any]) -> str:
        """Press a hotkey combination (list of keys)."""
        keys = params.get('keys')
        
        if not keys or not isinstance(keys, list):
            raise ValueError("Missing or invalid parameter: keys (should be a list)")
        
        self.pyautogui.hotkey(*keys)
        return f"Pressed hotkey: {'+'.join(keys)}"
    
    # ============ Screen actions ============
    
    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Take a screenshot and return metadata + base64 image."""
        region = params.get('region')  # (x, y, width, height)
        path = params.get('path')
        
        screenshot = self.pyautogui.screenshot(region=region)
        
        # Encode screenshot to Base64.
        buffer = BytesIO()
        screenshot.save(buffer, format='PNG')
        screenshot_bytes = buffer.getvalue()
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        result = {
            "screenshot": screenshot_base64,
            "format": "png",
            "size": len(screenshot_bytes),
            "width": screenshot.width,
            "height": screenshot.height
        }
        
        if path:
            screenshot.save(path)
            result['path'] = path
        
        return result
    
    async def _locate_on_screen(self, params: Dict[str, Any]) -> Optional[Dict[str, int]]:
        """Locate an image on screen and return bounding box if found."""
        image_path = params.get('image_path')
        confidence = params.get('confidence', 0.8)
        
        if not image_path:
            raise ValueError("Missing required parameter: image_path")
        
        try:
            location = self.pyautogui.locateOnScreen(
                image_path,
                confidence=confidence
            )
            
            if location:
                return {
                    "x": location.left,
                    "y": location.top,
                    "width": location.width,
                    "height": location.height
                }
            else:
                return None
        except Exception as e:
            logger.warning(f"Could not locate image: {e}")
            return None
    
    async def _get_screen_size(self, params: Dict[str, Any]) -> Dict[str, int]:
        """Get current screen size."""
        size = self.pyautogui.size()
        return {
            "width": size.width,
            "height": size.height
        }
    
    async def _get_mouse_position(self, params: Dict[str, Any]) -> Dict[str, int]:
        """Get current mouse position."""
        pos = self.pyautogui.position()
        return {
            "x": pos.x,
            "y": pos.y
        }
    
    # ============ Clipboard helper actions ============
    
    async def _get_clipboard(self, params: Dict[str, Any]) -> str:
        """Get current clipboard text."""
        try:
            import pyperclip
            return pyperclip.paste()
        except ImportError:
            raise ImportError("pyperclip not installed. Run: pip install pyperclip")
    
    async def _set_clipboard(self, params: Dict[str, Any]) -> str:
        """Set clipboard text."""
        text = params.get('text')
        
        if text is None:
            raise ValueError("Missing required parameter: text")
        
        try:
            import pyperclip
            pyperclip.copy(text)
            return f"Clipboard set to: {text}"
        except ImportError:
            raise ImportError("pyperclip not installed. Run: pip install pyperclip")
