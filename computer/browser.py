"""
Browser controller - based on Playwright.
"""
import asyncio
import os
from pathlib import Path
from uuid import uuid4
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
from agentkit.security.sandbox import get_sandbox_policy
import logging

logger = logging.getLogger("Computer.Browser")


class BrowserController(ComputerController):
    """Browser controller."""
    
    def __init__(self, workspace_root: Optional[str] = None):
        super().__init__("Browser", ComputerCapability.BROWSER)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._pages: Dict[str, Any] = {}  # tab_id -> page
        self.sandbox = get_sandbox_policy()
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.state_path = self.workspace_root / "browser_state.json"
        self._downloads: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._download_tasks: set[asyncio.Task] = set()
        self._download_pages: Dict[int, Any] = {}
    
    async def initialize(self) -> bool:
        """Initialize browser, context and first page."""
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()

            executable_path = Path(self.playwright.chromium.executable_path)
            if not executable_path.exists():
                logger.warning(
                    "Playwright Chromium is not installed; skipping browser controller. "
                    "Run: playwright install chromium"
                )
                await self.playwright.stop()
                self.playwright = None
                return False

            launch_timeout_ms = int(os.getenv("COMPUTER_BROWSER_LAUNCH_TIMEOUT_MS", "5000"))
            from config import config

            launch_args = []
            if config.sandbox.browser_disable_chromium_sandbox:
                logger.warning("Chromium process sandbox explicitly disabled by configuration")
                launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])
            
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                chromium_sandbox=not config.sandbox.browser_disable_chromium_sandbox,
                timeout=launch_timeout_ms,
                args=launch_args,
            )
            
            # Create browser context and try to restore saved state (cookies, local storage, etc.).
            state_path = str(self.state_path)
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
            
            self.context.on("page", self._track_downloads)
            # Create first page.
            self.page = await self.context.new_page()
            self._track_downloads(self.page)
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
            for task in tuple(self._download_tasks):
                task.cancel()
            await asyncio.gather(*tuple(self._download_tasks), return_exceptions=True)
            self._download_tasks.clear()
            self._download_pages.clear()
            if self.context:
                # Persist browser state to disk so it can be restored later.
                try:
                    await self.context.storage_state(path=str(self.state_path))
                    logger.info("Saved browser state to browser_state.json")
                except Exception as e:
                    logger.error(f"Failed to save browser state: {e}")

                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            self.is_initialized = False
            self.page = self.context = self.browser = self.playwright = None
            self._pages.clear()
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
            if action == "screenshot" and params.get("path"):
                decision = self.sandbox.check_path(str(params["path"]), intent="write", workspace_root=self.workspace_root)
                if not decision.allowed:
                    return ComputerResult(success=False, error=f"Sandbox blocked screenshot path: {decision.reason}")
                params = {**params, "path": str((self.workspace_root / str(params["path"])).resolve())}
            if action in {"navigate", "new_tab"}:
                url = str(params.get("url") or "").strip()
                if url:
                    decision = self.sandbox.check_url(url)
                    if not decision.allowed:
                        return ComputerResult(success=False, error=f"Sandbox blocked browser URL: {decision.reason}")
            action_map = {
                'navigate': self._navigate,
                'click': self._click,
                'type': self._type,
                'press': self._press,
                'wait_download': self._wait_download,
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
            {"name": "press", "description": "Press a key on an element", "params": ["selector", "key"]},
            {"name": "wait_download", "description": "Wait for a browser download", "params": ["timeout?"]},
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
    
    def has_background_activity(self) -> bool:
        return any(not task.done() for task in self._download_tasks)

    def _track_downloads(self, page) -> None:
        page_key = id(page)
        if page_key in self._download_pages:
            return
        self._download_pages[page_key] = page

        def enqueue(download):
            task = asyncio.create_task(self._save_download(download))
            self._download_tasks.add(task)
            task.add_done_callback(self._download_tasks.discard)

        page.on("download", enqueue)
        page.on("close", lambda *_: self._download_pages.pop(page_key, None))

    async def _save_download(self, download) -> None:
        name = Path(str(download.suggested_filename or "download")).name
        name = "".join("_" if ch in '<>:"/\\|?*\x00' else ch for ch in name).strip(" .")[:160] or "download"
        target = self.workspace_root / ".promethea" / "downloads" / f"{uuid4().hex}-{name}"
        try:
            decision = self.sandbox.check_path(str(target), intent="write", workspace_root=self.workspace_root)
            if not decision.allowed:
                raise PermissionError(decision.reason)
            target.parent.mkdir(parents=True, exist_ok=True)
            await download.save_as(str(target))
            result = {"path": str(target), "name": name, "size": target.stat().st_size}
        except asyncio.CancelledError:
            await download.cancel()
            raise
        except Exception as exc:
            result = {"error": str(exc)}
        if self._downloads.full():
            self._downloads.get_nowait()
        self._downloads.put_nowait(result)

    async def _wait_download(self, params: Dict[str, Any]) -> Dict[str, Any]:
        timeout = max(0.1, min(float(params.get("timeout", 30000)) / 1000, 600))
        result = await asyncio.wait_for(self._downloads.get(), timeout)
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result

    async def _press(self, params: Dict[str, Any]) -> str:
        selector, key = params.get("selector"), params.get("key")
        if not selector or not key:
            raise ValueError("selector and key are required")
        await self.page.press(selector, key)
        return f"Pressed '{key}' on '{selector}'"

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
        
        arg = params.get('arg', None)
        if arg is None:
            return await self.page.evaluate(script)
        return await self.page.evaluate(script, arg)
    
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
