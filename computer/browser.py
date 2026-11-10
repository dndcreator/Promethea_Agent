"""
Browser controller - based on Playwright.
"""
import asyncio
import os
from pathlib import Path
from uuid import uuid4
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
from .browser_runtime import launch_browser
from .browser_preview import WorkspaceBrowserPreview
from .browser_recording import BrowserRecording
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
        self._next_tab_id = 0
        self._headless: Optional[bool] = None
        self.sandbox = get_sandbox_policy()
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.state_path = self.workspace_root / "browser_state.json"
        self._downloads: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._download_tasks: set[asyncio.Task] = set()
        self._download_pages: Dict[int, Any] = {}
        self.initialization_error: Optional[Dict[str, str]] = None
        self.profile = None
        self._protected_profile = False
        self._evaluated = False
        self._protected_selectors: set[str] = set()
        self._preview = None
        self._recording = None
    
    async def initialize(self) -> bool:
        """Initialize browser, context and first page."""
        self.initialization_error = None
        try:
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()

            launch_timeout_ms = int(os.getenv("COMPUTER_BROWSER_LAUNCH_TIMEOUT_MS", "5000"))
            from config import config

            launch_args = []
            if config.sandbox.browser_disable_chromium_sandbox:
                logger.warning("Chromium process sandbox explicitly disabled by configuration")
                launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])
            
            self._headless = config.system.browser_headless
            self.browser = await launch_browser(
                self.playwright,
                headless=config.system.browser_headless,
                chromium_sandbox=not config.sandbox.browser_disable_chromium_sandbox,
                timeout=launch_timeout_ms,
                args=launch_args,
            )
            
            from .browser_state import BrowserProfile
            self.profile = BrowserProfile(self.workspace_root)
            saved = self.profile.load()
            self._protected_profile = bool(saved and saved.get("protected"))
            self._evaluated = False
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                **({"storage_state": saved["state"]} if saved else {}),
            )
            
            self.context.on("page", self._register_page)
            # Create first page.
            self.page = await self.context.new_page()
            if not config.system.browser_headless:
                await self.page.bring_to_front()
            self._register_page(self.page)
            
            self.is_initialized = True
            logger.info("Browser controller initialized")
            return True
            
        except ImportError:
            self.initialization_error = {"code": "BROWSER_DEPENDENCY_MISSING", "message": "Playwright Python dependency is missing."}
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return False
        except Exception as e:
            self.initialization_error = {"code": getattr(e, "code", "BROWSER_LAUNCH_FAILED"), "message": str(e)}
            logger.error(f"Failed to initialize browser: {e}")
            await self.cleanup()
            return False
        except asyncio.CancelledError:
            await self.cleanup()
            raise
    
    async def cleanup(self) -> bool:
        """Clean up browser resources and save state."""
        try:
            for task in tuple(self._download_tasks):
                task.cancel()
            await asyncio.gather(*tuple(self._download_tasks), return_exceptions=True)
            self._download_tasks.clear()
            self._download_pages.clear()
            if self._recording is not None:
                await self._recording.close()
                self._recording = None
            if self._preview is not None:
                await self._preview.close()
                self._preview = None
            if self.context:
                # Persist browser state to disk so it can be restored later.
                try:
                    state = await self.context.storage_state()
                    if self.profile:
                        self.profile.save(state, protected=self._protected_profile)
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
            self._next_tab_id = 0
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
            if action.startswith("record_"):
                if self._recording is None:
                    self._recording = BrowserRecording(self.browser, self.workspace_root, self.sandbox)
                self._recording.sandbox = self.sandbox
                return ComputerResult(success=True, result=await self._recording.execute(action, params))
            if action == "preview":
                if self._preview is None:
                    self._preview = WorkspaceBrowserPreview(self.browser, self.workspace_root, self.sandbox)
                self._preview.sandbox = self.sandbox
                return ComputerResult(success=True, result=await self._preview.execute(params))
            self._prune_pages()
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
            if self.page is None and action not in {"new_tab", "list_tabs", "list_credentials"}:
                return ComputerResult(success=False, error="No open browser page; inspect tabs or explicitly open a new tab.",
                                      metadata={"browser_state": self._runtime_state()})
            action_map = {
                'navigate': self._navigate,
                'click': self._click,
                'type': self._type,
                'press': self._press,
                'wait_download': self._wait_download,
                'screenshot': self._screenshot,
                'get_content': self._get_content,
                'evaluate': self._evaluate,
                'snapshot': self._snapshot,
                'create_credential': self._create_credential,
                'fill_credential': self._fill_credential,
                'list_credentials': self._list_credentials,
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
            metadata = {"browser_state": self._runtime_state()}
            if self.profile and self.profile.store and self.profile.store.available() and self.context:
                try:
                    self.profile.save(await self.context.storage_state(), protected=self._protected_profile)
                    metadata["profile_persistence"] = "os_protected"
                except Exception:
                    metadata["profile_persistence"] = "failed_after_action"
            return ComputerResult(success=True, result=result, metadata=metadata)
            
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return ComputerResult(success=False, error=str(e), metadata={"browser_state": self._runtime_state()})

    def _prune_pages(self):
        self._pages = {key: page for key, page in self._pages.items() if not page.is_closed()}
        if self.page is None or self.page.is_closed():
            self.page = next(reversed(self._pages.values()), None)

    def _register_page(self, page):
        existing = next((key for key, value in self._pages.items() if value is page), None)
        if existing is not None:
            return existing
        tab_id = "default" if self._next_tab_id == 0 else f"tab_{self._next_tab_id}"
        self._next_tab_id += 1
        self._pages[tab_id] = page
        page.on("close", lambda *_: self._prune_pages())
        self._track_downloads(page)
        self._prune_pages()
        return tab_id

    def _runtime_state(self):
        self._prune_pages()
        return {"connected": self.browser.is_connected() if self.browser else False,
                "mode": "unknown" if self._headless is None else "headless" if self._headless else "headed",
                "active_tab_id": next((key for key, page in self._pages.items() if page is self.page), None),
                "open_tab_ids": list(self._pages), "user_visibility_verified": False}
    
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
            {"name": "snapshot", "description": "Read fixed DOM controls and frame metadata", "params": ["query?", "max_nodes?"]},
            {"name": "create_credential", "description": "Generate a protected credential reference for the current HTTPS origin", "params": ["username?", "length?"]},
            {"name": "fill_credential", "description": "Fill a password using its origin-bound protected reference", "params": ["selector", "credential_ref"]},
            {"name": "list_credentials", "description": "List this owner's account metadata, never passwords", "params": []},
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
        field = self.page.locator(selector)
        field_type = str(await field.get_attribute('type') or '').lower()
        autocomplete = str(await field.get_attribute('autocomplete') or '').lower().split()
        if field_type == 'password' or set(autocomplete) & {'current-password', 'new-password'}:
            raise PermissionError("Protected credential input is required; plaintext password arguments are not accepted")
        await self.page.fill(selector, text)
        return "Filled the requested field"
    
    def has_background_activity(self) -> bool:
        return bool(self._recording and self._recording.active) or any(not task.done() for task in self._download_tasks)

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
        
        masks = [self.page.locator('input[type="password"],input[autocomplete~="new-password"],input[autocomplete~="current-password"]')]
        masks.extend(self.page.locator(selector) for selector in self._protected_selectors)
        screenshot_bytes = await self.page.screenshot(
            full_page=full_page,
            type='png', mask=masks,
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
            return await self.page.evaluate("""() => {
              const root = document.documentElement.cloneNode(true);
              root.querySelectorAll('script,style,noscript').forEach(el => el.remove());
              root.querySelectorAll('input').forEach(el => el.removeAttribute('value'));
              root.querySelectorAll('textarea').forEach(el => { el.textContent = ''; });
              return root.outerHTML;
            }""")
        elif content_type == 'text':
            return await self.page.inner_text('body')
        else:
            raise ValueError(f"Unknown content type: {content_type}")
    
    async def _evaluate(self, params: Dict[str, Any]) -> Any:
        """Evaluate JavaScript."""
        if self._protected_profile:
            raise PermissionError("arbitrary JavaScript is disabled in a protected credential profile; use snapshot/content")
        self._evaluated = True
        script = params.get('script')
        if not script:
            raise ValueError("Missing required parameter: script")
        
        arg = params.get('arg', None)
        if arg is None:
            return await self.page.evaluate(script)
        return await self.page.evaluate(script, arg)

    async def _snapshot(self, params):
        from .browser_observation import snapshot
        result = await snapshot(self.page, query=params.get("query", ""), max_nodes=params.get("max_nodes", 120))
        result["credential_storage_supported"] = bool(self.profile and self.profile.store and self.profile.store.available())
        result["protected_profile"] = self._protected_profile
        result["profile_persistence"] = self.profile.persistence if self.profile else "ephemeral"
        result["browser_state"] = self._runtime_state()
        return result

    def _credential_store(self):
        from agentkit.security.credential_store import ProtectedStorageUnavailable
        if not self.profile or not self.profile.store or not self.profile.store.available():
            raise ProtectedStorageUnavailable("credential operations require a trusted owner and OS-protected storage")
        return self.profile.store

    async def _create_credential(self, params):
        if self._evaluated:
            raise PermissionError("protected credentials require a fresh browser context without arbitrary script execution")
        metadata = self._credential_store().create_credential(url=self.page.url, username=str(params.get("username") or ""),
                                                            length=int(params.get("length", 32)))
        self._protected_profile = True
        self.profile.save(await self.context.storage_state(), protected=True)
        return metadata

    async def _list_credentials(self, params):
        return self._credential_store().list_credentials()

    async def _fill_credential(self, params):
        from agentkit.security.credential_store import web_origin
        if self._evaluated:
            raise PermissionError("protected credentials require a fresh browser context")
        selector = str(params.get("selector") or "")
        if not selector or not params.get("credential_ref"):
            raise ValueError("selector and credential_ref are required")
        field = await self.page.query_selector(selector)
        if field is None:
            raise ValueError("credential field was not found")
        kind = str(await field.get_attribute("type") or "").lower()
        autocomplete = str(await field.get_attribute("autocomplete") or "").lower().split()
        if kind != "password" and not set(autocomplete) & {"new-password", "current-password"}:
            raise PermissionError("protected credentials can only fill password fields")
        origin = await field.evaluate("node => node.ownerDocument.location.origin")
        if web_origin(origin) != web_origin(self.page.url):
            raise PermissionError("credential field origin differs from the current page")
        password = self._credential_store().password_for_origin(str(params["credential_ref"]), origin)
        self._protected_profile = True
        self.profile.save(await self.context.storage_state(), protected=True)
        self._protected_selectors.add(selector)
        try:
            await field.fill(password)
        except Exception:
            raise RuntimeError("protected credential fill failed; inspect page state before retrying") from None
        return {"filled": True, "origin": origin, "credential_ref": params["credential_ref"]}
    
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
        tab_id = self._register_page(page)
        
        url = params.get('url')
        if url:
            await page.goto(url)
        
        return {
            "tab_id": tab_id,
            "url": url or "about:blank",
            "active": self.page is page,
        }
    
    async def _close_tab(self, params: Dict[str, Any]) -> str:
        """Close a tab."""
        tab_id = params.get('tab_id', 'default')
        
        if tab_id not in self._pages:
            raise ValueError(f"Tab not found: {tab_id}")
        
        page = self._pages[tab_id]
        await page.close()
        self._prune_pages()
        
        return f"Closed tab {tab_id}"
    
    async def _switch_tab(self, params: Dict[str, Any]) -> str:
        """Switch active tab."""
        tab_id = params.get('tab_id')
        if not tab_id or tab_id not in self._pages:
            raise ValueError(f"Invalid tab_id: {tab_id}")
        
        self.page = self._pages[tab_id]
        await self.page.bring_to_front()
        return f"Switched to tab {tab_id}"
    
    async def _list_tabs(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List all open tabs."""
        self._prune_pages()
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
