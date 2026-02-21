"""
Browser controller - based on Playwright.
"""
import asyncio
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
import logging

logger = logging.getLogger("Computer.Browser")


class BrowserController(ComputerController):
    """Browser controller."""
    
    def __init__(self):
        super().__init__("Browser", ComputerCapability.BROWSER)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._pages: Dict[str, Any] = {}  # tab_id -> page
    
    async def initialize(self) -> bool:
        """Initialize browser, context and first page."""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )
            
            # Create browser context and try to restore saved state (cookies, local storage, etc.).
            import os
            state_path = "browser_state.json"
            if os.path.exists(state_path):
                logger.info(f"Loading browser state from {state_path}")
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    storage_state=state_path
                )
            else:
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
            
            # Create first page.
            self.page = await self.context.new_page()
            self._pages['default'] = self.page
            
            self.is_initialized = True
            logger.info("Browser controller initialized")
            return True
            
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            return False
    
    async def cleanup(self) -> bool:
        """Clean up browser resources and save state."""
        try:
            if self.context:
                # Persist browser state to disk so it can be restored later.
                try:
                    await self.context.storage_state(path="browser_state.json")
                    logger.info("Saved browser state to browser_state.json")
                except Exception as e:
                    logger.error(f"Failed to save browser state: {e}")

                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            self.is_initialized = False
            logger.info("Browser controller cleaned up")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up browser: {e}")
            return False
    
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        """Execute a browser action."""
        if not self.is_initialized:
            return ComputerResult(
                success=False,
                error="Browser not initialized. Call initialize() first."
            )
        
        try:
            action_map = {
                'navigate': self._navigate,
                'click': self._click,
                'type': self._type,
                'screenshot': self._screenshot,
                'get_content': self._get_content,
                'evaluate': self._evaluate,
                'wait': self._wait,
                'new_tab': self._new_tab,
                'close_tab': self._close_tab,
                'switch_tab': self._switch_tab,
                'list_tabs': self._list_tabs,
                'back': self._back,
                'forward': self._forward,
                'reload': self._reload,
                'get_url': self._get_url,
                'get_title': self._get_title,
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
        """Get list of supported browser actions."""
        return [
            {"name": "navigate", "description": "Navigate to URL", "params": ["url"]},
            {"name": "click", "description": "Click element", "params": ["selector"]},
            {"name": "type", "description": "Type text", "params": ["selector", "text"]},
            {"name": "screenshot", "description": "Screenshot", "params": ["full_page?"]},
            {"name": "get_content", "description": "Get page content", "params": []},
            {"name": "evaluate", "description": "Execute JavaScript", "params": ["script"]},
            {"name": "wait", "description": "Wait for selector or timeout", "params": ["selector?", "timeout?"]},
            {"name": "new_tab", "description": "Open new tab", "params": ["url?"]},
            {"name": "close_tab", "description": "Close current tab", "params": ["tab_id?"]},
            {"name": "switch_tab", "description": "Switch tab", "params": ["tab_id"]},
            {"name": "list_tabs", "description": "List all tabs", "params": []},
            {"name": "back", "description": "Navigate back", "params": []},
            {"name": "forward", "description": "Navigate forward", "params": []},
            {"name": "reload", "description": "Reload page", "params": []},
            {"name": "get_url", "description": "Get current URL", "params": []},
            {"name": "get_title", "description": "Get page title", "params": []},
        ]
    
    # ============ Concrete browser operations ============
    
    async def _navigate(self, params: Dict[str, Any]) -> str:
        """Navigate to URL."""
        url = params.get('url')
        if not url:
            raise ValueError("Missing required parameter: url")
        
        await self.page.goto(url, wait_until='domcontentloaded')
        return f"Navigated to {url}"
    
    async def _click(self, params: Dict[str, Any]) -> str:
        """Click an element."""
        selector = params.get('selector')
        if not selector:
            raise ValueError("Missing required parameter: selector")
        
        await self.page.click(selector)
        return f"Clicked {selector}"
    
    async def _type(self, params: Dict[str, Any]) -> str:
        """Type text into an element."""
        selector = params.get('selector')
        text = params.get('text')
        
        if not selector or text is None:
            raise ValueError("Missing required parameters: selector, text")
        
        await self.page.fill(selector, text)
        return f"Typed '{text}' into {selector}"
    
    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Take a screenshot and return base64 data."""
        full_page = params.get('full_page', False)
        path = params.get('path')
        
        screenshot_bytes = await self.page.screenshot(
            full_page=full_page,
            type='png'
        )
        
        # Convert to Base64.
        import base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        result = {
            "screenshot": screenshot_base64,
            "format": "png",
            "size": len(screenshot_bytes)
        }
        
        if path:
            with open(path, 'wb') as f:
                f.write(screenshot_bytes)
            result['path'] = path
        
        return result
    
    async def _get_content(self, params: Dict[str, Any]) -> str:
        """Get page content (HTML or text)."""
        content_type = params.get('type', 'text')
        
        if content_type == 'html':
            return await self.page.content()
        elif content_type == 'text':
            return await self.page.inner_text('body')
        else:
            raise ValueError(f"Unknown content type: {content_type}")
    
    async def _evaluate(self, params: Dict[str, Any]) -> Any:
        """Evaluate JavaScript."""
        script = params.get('script')
        if not script:
            raise ValueError("Missing required parameter: script")
        
        return await self.page.evaluate(script)
    
    async def _wait(self, params: Dict[str, Any]) -> str:
        """Wait for a selector or for a fixed time."""
        selector = params.get('selector')
        timeout = params.get('timeout', 30000)
        
        if selector:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return f"Waited for {selector}"
        else:
            wait_time = params.get('time', 1000) / 1000
            await asyncio.sleep(wait_time)
            return f"Waited {wait_time}s"
    
    async def _new_tab(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Open a new tab."""
        page = await self.context.new_page()
        tab_id = f"tab_{len(self._pages)}"
        self._pages[tab_id] = page
        
        url = params.get('url')
        if url:
            await page.goto(url)
        
        return {
            "tab_id": tab_id,
            "url": url or "about:blank"
        }
    
    async def _close_tab(self, params: Dict[str, Any]) -> str:
        """Close a tab."""
        tab_id = params.get('tab_id', 'default')
        
        if tab_id not in self._pages:
            raise ValueError(f"Tab not found: {tab_id}")
        
        page = self._pages[tab_id]
        await page.close()
        del self._pages[tab_id]
        
        return f"Closed tab {tab_id}"
    
    async def _switch_tab(self, params: Dict[str, Any]) -> str:
        """Switch active tab."""
        tab_id = params.get('tab_id')
        if not tab_id or tab_id not in self._pages:
            raise ValueError(f"Invalid tab_id: {tab_id}")
        
        self.page = self._pages[tab_id]
        return f"Switched to tab {tab_id}"
    
    async def _list_tabs(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List all open tabs."""
        tabs = []
        for tab_id, page in self._pages.items():
            tabs.append({
                "tab_id": tab_id,
                "url": page.url,
                "title": await page.title()
            })
        return tabs
    
    async def _back(self, params: Dict[str, Any]) -> str:
        """Navigate back."""
        await self.page.go_back()
        return "Navigated back"
    
    async def _forward(self, params: Dict[str, Any]) -> str:
        """Navigate forward."""
        await self.page.go_forward()
        return "Navigated forward"
    
    async def _reload(self, params: Dict[str, Any]) -> str:
        """Reload current page."""
        await self.page.reload()
        return "Page reloaded"
    
    async def _get_url(self, params: Dict[str, Any]) -> str:
        """Get current page URL."""
        return self.page.url
    
    async def _get_title(self, params: Dict[str, Any]) -> str:
        """Get current page title."""
        return await self.page.title()
