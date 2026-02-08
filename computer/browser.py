"""
浏览器控制器 - 基于 Playwright
"""
import asyncio
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
import logging

logger = logging.getLogger("Computer.Browser")


class BrowserController(ComputerController):
    """浏览器控制器"""
    
    def __init__(self):
        super().__init__("Browser", ComputerCapability.BROWSER)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._pages: Dict[str, Any] = {}  # tab_id -> page
    
    async def initialize(self) -> bool:
        """初始化浏览器"""
        try:
            # 动态导入 Playwright
            from playwright.async_api import async_playwright
            
            self.playwright = await async_playwright().start()
            
            # 启动浏览器（默认使用 Chromium）
            self.browser = await self.playwright.chromium.launch(
                headless=False,  # 显示浏览器窗口
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                ]
            )
            
            # 创建浏览器上下文
            # 尝试加载保存的状态（Cookies, LocalStorage）
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
            
            # 自动保存状态的钩子 (简单起见，我们在每次操作后尝试保存，或者提供显式保存)
            # 这里我们至少在 cleanup 时保存

            
            # 创建第一个页面
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
        """清理浏览器资源"""
        try:
            if self.context:
                # 保存状态
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
        """执行浏览器操作"""
        if not self.is_initialized:
            return ComputerResult(
                success=False,
                error="Browser not initialized. Call initialize() first."
            )
        
        try:
            # 路由到具体的操作方法
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
        """获取可用操作列表"""
        return [
            {"name": "navigate", "description": "导航到URL", "params": ["url"]},
            {"name": "click", "description": "点击元素", "params": ["selector"]},
            {"name": "type", "description": "输入文本", "params": ["selector", "text"]},
            {"name": "screenshot", "description": "截图", "params": ["full_page?"]},
            {"name": "get_content", "description": "获取页面内容", "params": []},
            {"name": "evaluate", "description": "执行JavaScript", "params": ["script"]},
            {"name": "wait", "description": "等待", "params": ["selector?", "timeout?"]},
            {"name": "new_tab", "description": "打开新标签页", "params": ["url?"]},
            {"name": "close_tab", "description": "关闭标签页", "params": ["tab_id?"]},
            {"name": "switch_tab", "description": "切换标签页", "params": ["tab_id"]},
            {"name": "list_tabs", "description": "列出所有标签页", "params": []},
            {"name": "back", "description": "后退", "params": []},
            {"name": "forward", "description": "前进", "params": []},
            {"name": "reload", "description": "刷新", "params": []},
            {"name": "get_url", "description": "获取当前URL", "params": []},
            {"name": "get_title", "description": "获取页面标题", "params": []},
        ]
    
    # ============ 具体操作实现 ============
    
    async def _navigate(self, params: Dict[str, Any]) -> str:
        """导航到URL"""
        url = params.get('url')
        if not url:
            raise ValueError("Missing required parameter: url")
        
        await self.page.goto(url, wait_until='domcontentloaded')
        return f"Navigated to {url}"
    
    async def _click(self, params: Dict[str, Any]) -> str:
        """点击元素"""
        selector = params.get('selector')
        if not selector:
            raise ValueError("Missing required parameter: selector")
        
        await self.page.click(selector)
        return f"Clicked {selector}"
    
    async def _type(self, params: Dict[str, Any]) -> str:
        """输入文本"""
        selector = params.get('selector')
        text = params.get('text')
        
        if not selector or text is None:
            raise ValueError("Missing required parameters: selector, text")
        
        await self.page.fill(selector, text)
        return f"Typed '{text}' into {selector}"
    
    async def _screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """截图"""
        full_page = params.get('full_page', False)
        path = params.get('path')
        
        screenshot_bytes = await self.page.screenshot(
            full_page=full_page,
            type='png'
        )
        
        # 转换为 Base64
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
        """获取页面内容"""
        content_type = params.get('type', 'text')
        
        if content_type == 'html':
            return await self.page.content()
        elif content_type == 'text':
            return await self.page.inner_text('body')
        else:
            raise ValueError(f"Unknown content type: {content_type}")
    
    async def _evaluate(self, params: Dict[str, Any]) -> Any:
        """执行JavaScript"""
        script = params.get('script')
        if not script:
            raise ValueError("Missing required parameter: script")
        
        return await self.page.evaluate(script)
    
    async def _wait(self, params: Dict[str, Any]) -> str:
        """等待"""
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
        """打开新标签页"""
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
        """关闭标签页"""
        tab_id = params.get('tab_id', 'default')
        
        if tab_id not in self._pages:
            raise ValueError(f"Tab not found: {tab_id}")
        
        page = self._pages[tab_id]
        await page.close()
        del self._pages[tab_id]
        
        return f"Closed tab {tab_id}"
    
    async def _switch_tab(self, params: Dict[str, Any]) -> str:
        """切换标签页"""
        tab_id = params.get('tab_id')
        if not tab_id or tab_id not in self._pages:
            raise ValueError(f"Invalid tab_id: {tab_id}")
        
        self.page = self._pages[tab_id]
        return f"Switched to tab {tab_id}"
    
    async def _list_tabs(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """列出所有标签页"""
        tabs = []
        for tab_id, page in self._pages.items():
            tabs.append({
                "tab_id": tab_id,
                "url": page.url,
                "title": await page.title()
            })
        return tabs
    
    async def _back(self, params: Dict[str, Any]) -> str:
        """后退"""
        await self.page.go_back()
        return "Navigated back"
    
    async def _forward(self, params: Dict[str, Any]) -> str:
        """前进"""
        await self.page.go_forward()
        return "Navigated forward"
    
    async def _reload(self, params: Dict[str, Any]) -> str:
        """刷新页面"""
        await self.page.reload()
        return "Page reloaded"
    
    async def _get_url(self, params: Dict[str, Any]) -> str:
        """获取当前URL"""
        return self.page.url
    
    async def _get_title(self, params: Dict[str, Any]) -> str:
        """获取页面标题"""
        return await self.page.title()
