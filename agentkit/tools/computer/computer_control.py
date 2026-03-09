"""
Computer control MCP service adapter.

Expose low-level capabilities of the `computer` module to the MCP framework.
"""

import asyncio
import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from computer.base import ComputerCapability
from agentkit.security.sandbox import get_sandbox_policy


class ComputerControlService:
    """Computer control service (MCP wrapper)."""

    def __init__(self):
        self.name = "computer_control"
        self._browser_snapshot_refs: Dict[str, str] = {}
        self._content_tools = None
        self._runtime_tools = None
        self._cron_tools = None
        self._node_tools = None
        self._sandbox = get_sandbox_policy()

    async def _execute_action_raw(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            from gateway_integration import get_gateway_integration

            gateway = get_gateway_integration()
            if not gateway:
                return {"ok": False, "error": "gateway system is not initialized"}

            payload = params or {}
            logger.info(f"Executing computer action raw: {capability}.{action} params={payload}")
            result = await gateway.execute_computer_action(capability, action, payload)
            return {
                "ok": bool(result.success),
                "result": result.result,
                "error": result.error,
                "screenshot": result.screenshot,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _alias_browser_action(action: str) -> str:
        aliases = {
            "goto": "navigate",
            "content": "get_content",
        }
        return aliases.get(action, action)

    @staticmethod
    def _alias_screen_action(action: str) -> str:
        aliases = {
            "locate_on_screen": "locate",
            "position": "get_mouse_position",
            "size": "get_screen_size",
        }
        return aliases.get(action, action)

    async def execute_action(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any] | None = None,
    ) -> str:
        """Execute a computer control action via the gateway."""
        raw = await self._execute_action_raw(capability, action, params)
        if not raw.get("ok"):
            return f"ERROR: operation failed: {raw.get('error', 'unknown error')}"
        output = "SUCCESS: operation completed\n"
        if raw.get("result") is not None:
            output += f"Result: {raw.get('result')}\n"
        screenshot = raw.get("screenshot")
        if screenshot:
            output += f"[Including screenshot data: {len(screenshot)} bytes]\n"
        return output

    async def browser_action(
        self,
        action: str,
        url: str = "",
        selector: str = "",
        text: str = "",
        path: str = "",
        ref: str = "",
        key: str = "",
        value: str = "",
        timeout: int = 10000,
        max_nodes: int = 120,
        query: str = "",
        download_dir: str = "",
        poll_interval_ms: int = 500,
        tab_id: str = "",
        **kwargs,
    ) -> str:
        """Browser operations with higher-level snapshot/act/download helpers."""
        normalized = (action or "").strip().lower()
        if normalized in {"goto", "navigate"} and url:
            url_decision = self._sandbox.check_url(url)
            if not url_decision.allowed:
                return f"ERROR: sandbox blocked browser url: {url_decision.reason}"
        if normalized == "snapshot":
            return await self._browser_snapshot(max_nodes=max_nodes, query=query)
        if normalized == "act":
            return await self._browser_act(
                selector=selector,
                ref=ref,
                text=text,
                key=key,
                value=value,
                timeout=timeout,
            )
        if normalized in {"wait_download", "download_wait"}:
            return await self._browser_wait_download(
                download_dir=download_dir,
                timeout=timeout,
                poll_interval_ms=poll_interval_ms,
            )
        if normalized in {"tabs", "list_tabs"}:
            return await self.execute_action(ComputerCapability.BROWSER, "list_tabs", {})
        if normalized in {"tab_open", "new_tab"}:
            if url:
                url_decision = self._sandbox.check_url(url)
                if not url_decision.allowed:
                    return f"ERROR: sandbox blocked browser url: {url_decision.reason}"
            payload: Dict[str, Any] = {}
            if url:
                payload["url"] = url
            return await self.execute_action(ComputerCapability.BROWSER, "new_tab", payload)
        if normalized in {"tab_focus", "switch_tab"}:
            tab = (tab_id or value or text or "").strip()
            if not tab:
                return "ERROR: tab_focus requires tab_id (or value/text)"
            return await self.execute_action(
                ComputerCapability.BROWSER,
                "switch_tab",
                {"tab_id": tab},
            )
        if normalized in {"tab_close", "close_tab"}:
            tab = (tab_id or value or text or "").strip()
            payload = {"tab_id": tab} if tab else {}
            return await self.execute_action(ComputerCapability.BROWSER, "close_tab", payload)
        if normalized in {"workspace_state", "state"}:
            tabs = await self._execute_action_raw(ComputerCapability.BROWSER, "list_tabs", {})
            cur_url = await self._execute_action_raw(ComputerCapability.BROWSER, "get_url", {})
            cur_title = await self._execute_action_raw(ComputerCapability.BROWSER, "get_title", {})
            state = {
                "current_url": cur_url.get("result") if cur_url.get("ok") else "",
                "current_title": cur_title.get("result") if cur_title.get("ok") else "",
                "tabs": tabs.get("result") if tabs.get("ok") else [],
            }
            return f"SUCCESS: browser workspace_state\nResult: {state}"

        params: Dict[str, Any] = {}
        if url:
            params["url"] = url
        if selector:
            params["selector"] = selector
        if text:
            params["text"] = text
        if path:
            params["path"] = path
        if key:
            params["key"] = key
        if value:
            params["value"] = value
        if timeout:
            params["timeout"] = timeout
        if tab_id:
            params["tab_id"] = tab_id
        for k, v in (kwargs or {}).items():
            if v is not None and v != "":
                params[k] = v
        mapped_action = self._alias_browser_action(action)
        return await self.execute_action(ComputerCapability.BROWSER, mapped_action, params)

    async def _browser_snapshot(self, max_nodes: int = 120, query: str = "") -> str:
        script = """
        (payload) => {
          const q = String((payload && payload.query) || '').trim().toLowerCase();
          const maxN = Math.max(1, Number((payload && payload.max_nodes) || 120));
          const cssPath = (el) => {
            if (!el || el.nodeType !== 1) return '';
            if (el.id) return `#${el.id}`;
            const parts = [];
            let cur = el;
            while (cur && cur.nodeType === 1 && parts.length < 5) {
              let p = cur.tagName.toLowerCase();
              if (cur.className && typeof cur.className === 'string') {
                const cls = cur.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.');
                if (cls) p += '.' + cls;
              }
              parts.unshift(p);
              cur = cur.parentElement;
            }
            return parts.join(' > ');
          };
          const nodes = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"],[onclick],[tabindex]'));
          const out = [];
          for (const el of nodes) {
            const txt = String(el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
            if (q && !txt.toLowerCase().includes(q)) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            out.push({
              tag: (el.tagName || '').toLowerCase(),
              text: txt.slice(0, 220),
              role: String(el.getAttribute('role') || ''),
              href: String(el.getAttribute('href') || ''),
              selector: cssPath(el),
              x: Math.round(r.left + r.width/2),
              y: Math.round(r.top + r.height/2),
              width: Math.round(r.width),
              height: Math.round(r.height),
            });
            if (out.length >= maxN) break;
          }
          return out;
        }
        """
        data = await self._execute_action_raw(
            ComputerCapability.BROWSER,
            "evaluate",
            {"script": script, "arg": {"query": query or "", "max_nodes": max(1, int(max_nodes))}},
        )
        if not data.get("ok"):
            return f"ERROR: snapshot failed: {data.get('error')}"

        rows = data.get("result") or []
        self._browser_snapshot_refs = {}
        out: List[Dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            ref_id = f"n{i}"
            selector_val = str((row or {}).get("selector") or "")
            if selector_val:
                self._browser_snapshot_refs[ref_id] = selector_val
            node = dict(row or {})
            node["ref"] = ref_id
            out.append(node)

        return f"SUCCESS: browser snapshot\nResult: {{'count': {len(out)}, 'nodes': {out}}}"

    async def _browser_act(
        self,
        selector: str = "",
        ref: str = "",
        text: str = "",
        key: str = "",
        value: str = "",
        timeout: int = 10000,
    ) -> str:
        target = (selector or "").strip()
        if not target and ref:
            target = self._browser_snapshot_refs.get(ref, "")
        if not target:
            return "ERROR: browser act requires selector or ref"

        if text or value:
            payload: Dict[str, Any] = {"selector": target, "text": text or value}
            if timeout:
                payload["timeout"] = int(timeout)
            return await self.execute_action(ComputerCapability.BROWSER, "type", payload)

        if key:
            await self.execute_action(ComputerCapability.BROWSER, "click", {"selector": target})
            return await self.execute_action(ComputerCapability.KEYBOARD, "press", {"key": key})

        payload = {"selector": target}
        if timeout:
            payload["timeout"] = int(timeout)
        return await self.execute_action(ComputerCapability.BROWSER, "click", payload)

    async def _browser_wait_download(
        self,
        download_dir: str = "",
        timeout: int = 30000,
        poll_interval_ms: int = 500,
    ) -> str:
        base = Path(download_dir) if download_dir else Path.home() / "Downloads"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            return f"ERROR: invalid download_dir: {base}"

        start = time.time()
        known = {p.name for p in base.glob('*') if p.is_file()}
        wait_s = max(0.1, float(timeout) / 1000.0)
        interval_s = max(0.1, float(poll_interval_ms) / 1000.0)

        while (time.time() - start) < wait_s:
            current = [p for p in base.glob('*') if p.is_file()]
            for p in current:
                if p.name in known:
                    continue
                lower = p.name.lower()
                if lower.endswith('.crdownload') or lower.endswith('.part'):
                    continue
                return f"SUCCESS: download detected\nResult: {{'path': '{str(p)}', 'name': '{p.name}', 'size': {p.stat().st_size}}}"
            await asyncio.sleep(interval_s)

        return f"ERROR: no completed download found in {base} within {timeout}ms"

    async def screen_action(
        self,
        action: str,
        x: int = 0,
        y: int = 0,
        text: str = "",
        key: str = "",
        path: str = "",
    ) -> str:
        """Screen, mouse and keyboard operations."""
        params: Dict[str, Any] = {}
        if x or y:
            params["x"] = x
            params["y"] = y
        if text:
            params["text"] = text
        if key:
            params["key"] = key
        if path:
            params["path"] = path

        action = self._alias_screen_action(action)
        cap = ComputerCapability.SCREEN
        if action in ["move", "click", "scroll"]:
            cap = ComputerCapability.MOUSE
        if action in ["type", "press"]:
            cap = ComputerCapability.KEYBOARD
        if action == "screenshot":
            cap = ComputerCapability.SCREENSHOT

        return await self.execute_action(cap, action, params)

    async def fs_action(
        self,
        action: str,
        path: str = "",
        content: str = "",
        recursive: bool = False,
        pattern: str = "",
        src: str = "",
        dst: str = "",
        encoding: str = "utf-8",
    ) -> str:
        """File system operations."""
        normalized = (action or "").strip().lower()
        write_ops = {"write", "append", "delete", "move", "copy", "mkdir"}
        intent = "write" if normalized in write_ops else "read"
        if path:
            p_decision = self._sandbox.check_path(path, intent=intent)
            if not p_decision.allowed:
                return f"ERROR: sandbox blocked path: {p_decision.reason}"
        if src:
            s_decision = self._sandbox.check_path(src, intent="write")
            if not s_decision.allowed:
                return f"ERROR: sandbox blocked src: {s_decision.reason}"
        if dst:
            d_decision = self._sandbox.check_path(dst, intent="write")
            if not d_decision.allowed:
                return f"ERROR: sandbox blocked dst: {d_decision.reason}"
        params: Dict[str, Any] = {}
        if path:
            params["path"] = path
        if content:
            params["content"] = content
        if recursive:
            params["recursive"] = recursive
        if pattern:
            params["pattern"] = pattern
        if src:
            params["src"] = src
        if dst:
            params["dst"] = dst
        if encoding:
            params["encoding"] = encoding
        return await self.execute_action(ComputerCapability.FILESYSTEM, action, params)

    async def process_action(
        self,
        action: str,
        command: str = "",
        cwd: str = "",
        timeout: int = 30,
        pid: int = 0,
        shell: bool = True,
    ) -> str:
        """Process/runtime operations."""
        normalized = (action or "").strip().lower()
        if normalized in {"run", "run_async"} and command:
            cmd_decision = self._sandbox.check_command(command, cwd=cwd or ".")
            if not cmd_decision.allowed:
                return f"ERROR: sandbox blocked command: {cmd_decision.reason}"
        params: Dict[str, Any] = {}
        if command:
            params["command"] = command
        if cwd:
            params["cwd"] = cwd
        if timeout:
            params["timeout"] = timeout
        if pid:
            params["pid"] = pid
        params["shell"] = bool(shell)
        return await self.execute_action(ComputerCapability.PROCESS, action, params)

    async def _screen_ocr_scan(self, min_confidence: float = 40.0) -> Dict[str, Any]:
        shot = await self._execute_action_raw(ComputerCapability.SCREEN, "screenshot", {})
        if not shot.get("ok"):
            return {"ok": False, "error": f"screenshot failed: {shot.get('error')}"}

        result = shot.get("result") or {}
        b64 = result.get("screenshot")
        if not b64:
            return {"ok": False, "error": "screenshot payload missing base64 data"}

        try:
            from PIL import Image
            import pytesseract
        except Exception as e:
            return {"ok": False, "error": f"OCR dependencies unavailable: {e}"}

        try:
            raw = base64.b64decode(str(b64))
            img = Image.open(BytesIO(raw))
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        except Exception as e:
            return {"ok": False, "error": f"OCR failed: {e}"}

        words: List[Dict[str, Any]] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = str((data.get("text") or [""])[i] or "").strip()
            if not text:
                continue
            try:
                conf = float((data.get("conf") or ["0"])[i] or 0.0)
            except Exception:
                conf = 0.0
            if conf < float(min_confidence):
                continue
            left = int((data.get("left") or [0])[i] or 0)
            top = int((data.get("top") or [0])[i] or 0)
            width = int((data.get("width") or [0])[i] or 0)
            height = int((data.get("height") or [0])[i] or 0)
            words.append(
                {
                    "text": text,
                    "conf": conf,
                    "x": left + (width // 2),
                    "y": top + (height // 2),
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                }
            )

        full_text = " ".join(w["text"] for w in words)
        return {
            "ok": True,
            "text": full_text,
            "items": words,
            "image_width": result.get("width"),
            "image_height": result.get("height"),
        }

    async def _find_browser_candidates(
        self,
        needle: str,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        script = """
            (payload) => {
              const needle = (payload && payload.needle) ? String(payload.needle) : "";
              const maxN = (payload && payload.maxN) ? Number(payload.maxN) : 8;
              const q = needle.toLowerCase();
              const nodes = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role="button"],[onclick],[tabindex]'));
              const out = [];
              const cssPath = (el) => {
                if (el.id) return `#${el.id}`;
                const parts = [];
                let cur = el;
                while (cur && cur.nodeType === 1 && parts.length < 4) {
                  let part = cur.tagName.toLowerCase();
                  if (cur.className && typeof cur.className === 'string') {
                    const c = cur.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.');
                    if (c) part += '.' + c;
                  }
                  parts.unshift(part);
                  cur = cur.parentElement;
                }
                return parts.join(' > ');
              };
              for (const el of nodes) {
                const txt = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                if (!txt) continue;
                const low = txt.toLowerCase();
                if (!low.includes(q)) continue;
                const r = el.getBoundingClientRect();
                const exact = low === q;
                const starts = low.startsWith(q);
                let score = 0;
                if (exact) score += 1.0;
                else if (starts) score += 0.8;
                else score += 0.6;
                if (el.tagName.toLowerCase() === 'button' || el.getAttribute('role') === 'button') score += 0.2;
                out.push({
                  selector: cssPath(el),
                  text: txt.slice(0, 180),
                  tag: el.tagName.toLowerCase(),
                  x: Math.round(r.left + r.width/2),
                  y: Math.round(r.top + r.height/2),
                  width: Math.round(r.width),
                  height: Math.round(r.height),
                  score,
                });
              }
              out.sort((a,b)=>b.score-a.score);
              return out.slice(0, Math.max(1, maxN || 8));
            }
            """
        found = await self._execute_action_raw(
            ComputerCapability.BROWSER,
            "evaluate",
            {"script": script, "arg": {"needle": needle, "maxN": max(1, int(max_candidates))}},
        )
        if not found.get("ok"):
            return {"ok": False, "error": found.get("error", "browser evaluate failed"), "candidates": []}
        return {"ok": True, "candidates": found.get("result") or []}

    async def _find_screen_text_candidates(
        self,
        needle: str,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        scan = await self._screen_ocr_scan(min_confidence=35.0)
        if not scan.get("ok"):
            return {"ok": False, "error": scan.get("error", "ocr scan failed"), "candidates": []}
        q = needle.lower()
        candidates: List[Dict[str, Any]] = []
        for row in scan.get("items") or []:
            text_val = str(row.get("text") or "")
            low = text_val.lower()
            if q not in low:
                continue
            score = 1.0 if low == q else (0.85 if low.startswith(q) else 0.7)
            cand = dict(row)
            cand["score"] = score
            candidates.append(cand)
        candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return {"ok": True, "candidates": candidates[: max(1, int(max_candidates))]}

    async def perception_action(
        self,
        mode: str = "observe",
        target_text: str = "",
        image_path: str = "",
        max_candidates: int = 8,
        include_screenshot: bool = False,
    ) -> str:
        """Cross-surface perception helpers for robust UI workflows."""
        mode = (mode or "observe").strip().lower()

        if mode == "observe":
            observation: Dict[str, Any] = {"mode": "observe"}
            url = await self._execute_action_raw(ComputerCapability.BROWSER, "get_url", {})
            title = await self._execute_action_raw(ComputerCapability.BROWSER, "get_title", {})
            content = await self._execute_action_raw(
                ComputerCapability.BROWSER,
                "get_content",
                {"type": "text"},
            )
            screen_size = await self._execute_action_raw(ComputerCapability.SCREEN, "get_screen_size", {})
            mouse_pos = await self._execute_action_raw(ComputerCapability.SCREEN, "get_mouse_position", {})

            observation["browser"] = {
                "url": url.get("result") if url.get("ok") else None,
                "title": title.get("result") if title.get("ok") else None,
                "text_excerpt": (
                    str(content.get("result") or "")[:1200] if content.get("ok") else ""
                ),
            }
            observation["screen"] = {
                "size": screen_size.get("result") if screen_size.get("ok") else None,
                "mouse": mouse_pos.get("result") if mouse_pos.get("ok") else None,
            }
            if include_screenshot:
                shot = await self._execute_action_raw(ComputerCapability.SCREEN, "screenshot", {})
                if shot.get("ok"):
                    result = shot.get("result") or {}
                    observation["screen"]["screenshot_size"] = result.get("size")
                    observation["screen"]["screenshot_format"] = result.get("format")
            return f"SUCCESS: perception observe\nResult: {observation}"

        if mode == "find_browser_target":
            needle = (target_text or "").strip()
            if not needle:
                return "ERROR: target_text is required for find_browser_target"
            found = await self._find_browser_candidates(needle=needle, max_candidates=max_candidates)
            if not found.get("ok"):
                return f"ERROR: find_browser_target failed: {found.get('error')}"
            data = found.get("candidates") or []
            return f"SUCCESS: perception find_browser_target\nResult: {data}"

        if mode == "locate_template":
            if not image_path:
                return "ERROR: image_path is required for locate_template"
            located = await self._execute_action_raw(
                ComputerCapability.SCREEN,
                "locate",
                {"image_path": image_path},
            )
            if not located.get("ok"):
                return f"ERROR: locate_template failed: {located.get('error')}"
            return f"SUCCESS: perception locate_template\nResult: {located.get('result')}"

        if mode == "ocr_screen":
            scan = await self._screen_ocr_scan(min_confidence=35.0)
            if not scan.get("ok"):
                return f"ERROR: ocr_screen failed: {scan.get('error')}"
            summary = {
                "text_excerpt": str(scan.get("text") or "")[:1200],
                "items": len(scan.get("items") or []),
                "image_width": scan.get("image_width"),
                "image_height": scan.get("image_height"),
            }
            return f"SUCCESS: perception ocr_screen\nResult: {summary}"

        if mode == "find_text_on_screen":
            needle = (target_text or "").strip()
            if not needle:
                return "ERROR: target_text is required for find_text_on_screen"
            found = await self._find_screen_text_candidates(needle=needle, max_candidates=max_candidates)
            if not found.get("ok"):
                return f"ERROR: find_text_on_screen failed: {found.get('error')}"
            top = found.get("candidates") or []
            return (
                "SUCCESS: perception find_text_on_screen\n"
                f"Result: {{'target': {needle!r}, 'matches': {len(top)}, 'candidates': {top}}}"
            )

        if mode == "click_text_on_screen":
            needle = (target_text or "").strip()
            if not needle:
                return "ERROR: target_text is required for click_text_on_screen"
            found = await self._find_screen_text_candidates(needle=needle, max_candidates=max_candidates)
            if not found.get("ok"):
                return f"ERROR: click_text_on_screen failed: {found.get('error')}"
            top = found.get("candidates") or []
            if not top:
                return f"ERROR: click_text_on_screen target not found: {needle}"
            best = top[0]
            click_out = await self.execute_action(
                ComputerCapability.MOUSE,
                "click",
                {"x": int(best.get("x") or 0), "y": int(best.get("y") or 0)},
            )
            if not click_out.startswith("SUCCESS"):
                return f"ERROR: click_text_on_screen click failed: {click_out}"
            return (
                "SUCCESS: perception click_text_on_screen\n"
                f"Result: {{'target': {needle!r}, 'x': {int(best.get('x') or 0)}, 'y': {int(best.get('y') or 0)}, 'text': {str(best.get('text') or '')!r}}}"
            )

        if mode == "execute_target_with_fallback":
            needle = (target_text or "").strip()
            if not needle:
                return "ERROR: target_text is required for execute_target_with_fallback"
            browser = await self._find_browser_candidates(needle=needle, max_candidates=max_candidates)
            if browser.get("ok") and (browser.get("candidates") or []):
                first = (browser.get("candidates") or [])[0]
                selector = str(first.get("selector") or "").strip()
                if selector:
                    dom_click = await self.execute_action(
                        ComputerCapability.BROWSER,
                        "click",
                        {"selector": selector},
                    )
                    if dom_click.startswith("SUCCESS"):
                        return (
                            "SUCCESS: perception execute_target_with_fallback\n"
                            f"Result: {{'path': 'dom', 'selector': {selector!r}, 'text': {str(first.get('text') or '')!r}}}"
                        )
            screen_click = await self.perception_action(
                mode="click_text_on_screen",
                target_text=needle,
                max_candidates=max_candidates,
            )
            if screen_click.startswith("SUCCESS"):
                return (
                    "SUCCESS: perception execute_target_with_fallback\n"
                    f"Result: {{'path': 'ocr'}}"
                )
            return f"ERROR: execute_target_with_fallback failed: {screen_click}"

        if mode == "suggest_next_action":
            intent = (target_text or "").strip().lower()
            suggestions: List[Dict[str, Any]] = []
            if any(k in intent for k in ["download", "open", "click", "button"]):
                suggestions.append({
                    "service": "computer_control",
                    "command": "perception_action",
                    "params": {"mode": "find_browser_target", "target_text": target_text, "max_candidates": max_candidates},
                    "why": "locate clickable UI target before acting",
                })
                suggestions.append({
                    "service": "computer_control",
                    "command": "browser_action",
                    "params": {"action": "click", "selector": "<selector-from-candidate>"},
                    "why": "click top-ranked candidate",
                })
                suggestions.append({
                    "service": "computer_control",
                    "command": "perception_action",
                    "params": {"mode": "execute_target_with_fallback", "target_text": target_text, "max_candidates": max_candidates},
                    "why": "execute target with DOM-first and OCR fallback",
                })
            else:
                suggestions.append({
                    "service": "computer_control",
                    "command": "perception_action",
                    "params": {"mode": "observe", "include_screenshot": include_screenshot},
                    "why": "collect current UI state first",
                })
            return f"SUCCESS: perception suggest_next_action\nResult: {suggestions}"

        return f"ERROR: unknown perception mode: {mode}"

    # Friendly aliases for common scenarios
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        return await self.fs_action("read", path=path, encoding=encoding)

    async def write_file(self, path: str, content: str, encoding: str = "utf-8") -> str:
        return await self.fs_action("write", path=path, content=content, encoding=encoding)

    async def list_files(self, path: str = ".", recursive: bool = False) -> str:
        return await self.fs_action("list", path=path, recursive=recursive)

    async def delete_file(self, path: str) -> str:
        return await self.fs_action("delete", path=path)

    async def execute_command(
        self,
        command: str,
        cwd: str = "",
        timeout: int = 30,
        shell: bool = True,
    ) -> str:
        return await self.process_action(
            "run",
            command=command,
            cwd=cwd,
            timeout=timeout,
            shell=shell,
        )























    def _get_content_tools(self):
        if self._content_tools is None:
            from agentkit.tools.content_tools.content_tools import ContentToolsService

            self._content_tools = ContentToolsService()
        return self._content_tools

    def _get_runtime_tools(self):
        if self._runtime_tools is None:
            from agentkit.tools.runtime_tools.runtime_tools import RuntimeToolsService

            self._runtime_tools = RuntimeToolsService()
        return self._runtime_tools

    def _get_cron_tools(self):
        if self._cron_tools is None:
            from agentkit.tools.cron_tools.cron_tools import CronToolsService

            self._cron_tools = CronToolsService()
        return self._cron_tools

    def _get_node_tools(self):
        if self._node_tools is None:
            from agentkit.tools.node_tools.node_tools import NodeToolsService

            self._node_tools = NodeToolsService()
        return self._node_tools

    async def content_action(
        self,
        action: str = "web_fetch",
        url: str = "",
        path: str = "",
        page: int = 0,
        max_pages: int = 5,
        max_chars: int = 12000,
        timeout: int = 20,
        include_links: bool = False,
    ) -> Dict[str, Any]:
        svc = self._get_content_tools()
        mode = (action or "web_fetch").strip().lower()
        if mode == "web_fetch":
            url_decision = self._sandbox.check_url(url)
            if not url_decision.allowed:
                return {"ok": False, "error": f"sandbox blocked web_fetch: {url_decision.reason}"}
            return await svc.web_fetch(
                url=url,
                max_chars=max_chars,
                timeout=timeout,
                include_links=include_links,
            )
        if mode in {"pdf", "pdf_action"}:
            return await svc.pdf_action(
                action="extract_text",
                path=path,
                page=page,
                max_pages=max_pages,
                max_chars=max_chars,
            )
        if mode == "pdf_metadata":
            return await svc.pdf_action(action="metadata", path=path)
        if mode in {"image", "image_action"}:
            return await svc.image_action(action="metadata", path=path, max_chars=max_chars)
        if mode == "image_ocr":
            return await svc.image_action(action="ocr", path=path, max_chars=max_chars)
        raise ValueError(f"unsupported content action: {action}")

    async def runtime_action(
        self,
        action: str = "gateway_status",
        session_id: str = "",
        user_id: str = "default_user",
        agent_name: str = "",
        agent_type: str = "",
        query: str = "",
        channel: str = "",
        receiver_id: str = "",
        content: str = "",
    ) -> Dict[str, Any]:
        svc = self._get_runtime_tools()
        mode = (action or "gateway_status").strip().lower()

        if mode in {"gateway_status", "gateway_routes", "gateway_tools"}:
            sub = {
                "gateway_status": "status",
                "gateway_routes": "routes",
                "gateway_tools": "tools",
            }[mode]
            return await svc.gateway_action(action=sub)

        if mode in {"sessions_list", "session_detail", "session_delete", "session_set_agent"}:
            sub = {
                "sessions_list": "list",
                "session_detail": "detail",
                "session_delete": "delete",
                "session_set_agent": "set_agent_type",
            }[mode]
            return await svc.sessions_action(
                action=sub,
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
            )

        if mode in {"agents_list", "agent_get"}:
            sub = "list" if mode == "agents_list" else "get"
            return await svc.agents_action(action=sub, agent_name=agent_name)

        if mode in {"memory_stats", "memory_search", "memory_cluster", "memory_summarize"}:
            sub = {
                "memory_stats": "stats",
                "memory_search": "search",
                "memory_cluster": "cluster",
                "memory_summarize": "summarize",
            }[mode]
            return await svc.memory_action(action=sub, query=query, session_id=session_id, user_id=user_id)

        if mode in {"channels_list", "message_send"}:
            sub = "list_channels" if mode == "channels_list" else "send"
            return await svc.message_action(
                action=sub,
                channel=channel,
                receiver_id=receiver_id,
                content=content,
            )

        if mode in {"plugins_list", "plugins_diagnostics"}:
            sub = "list" if mode == "plugins_list" else "diagnostics"
            return await svc.plugins_action(action=sub)

        raise ValueError(f"unsupported runtime action: {action}")

    async def schedule_action(
        self,
        action: str = "list_jobs",
        job_id: str = "",
        name: str = "",
        interval_seconds: int = 60,
        service_name: str = "",
        tool_name: str = "",
        args: Dict[str, Any] | None = None,
        enabled: bool = True,
        enabled_only: bool = False,
        max_jobs: int = 10,
    ) -> Dict[str, Any]:
        svc = self._get_cron_tools()
        mode = (action or "list_jobs").strip().lower()
        if mode == "create_job":
            return await svc.create_job(
                name=name,
                interval_seconds=interval_seconds,
                service_name=service_name,
                tool_name=tool_name,
                args=args or {},
                enabled=enabled,
            )
        if mode == "list_jobs":
            return await svc.list_jobs(enabled_only=enabled_only)
        if mode == "remove_job":
            return await svc.remove_job(job_id=job_id)
        if mode == "pause_job":
            return await svc.pause_job(job_id=job_id)
        if mode == "resume_job":
            return await svc.resume_job(job_id=job_id)
        if mode == "run_due_jobs":
            return await svc.run_due_jobs(max_jobs=max_jobs)
        raise ValueError(f"unsupported schedule action: {action}")

    async def graph_action(
        self,
        action: str = "list_nodes",
        node_id: str = "",
        kind: str = "",
        data: Dict[str, Any] | None = None,
        tags: List[str] | None = None,
        tag: str = "",
        limit: int = 100,
        source: str = "",
        target: str = "",
        relation: str = "related_to",
        weight: float = 1.0,
    ) -> Dict[str, Any]:
        svc = self._get_node_tools()
        mode = (action or "list_nodes").strip().lower()
        if mode == "upsert_node":
            return await svc.upsert_node(node_id=node_id, kind=kind or "generic", data=data or {}, tags=tags or [])
        if mode == "get_node":
            return await svc.get_node(node_id=node_id)
        if mode == "list_nodes":
            return await svc.list_nodes(kind=kind, tag=tag, limit=limit)
        if mode == "delete_node":
            return await svc.delete_node(node_id=node_id)
        if mode == "link_nodes":
            return await svc.link_nodes(source=source, target=target, relation=relation, weight=weight)
        if mode == "list_links":
            return await svc.list_links(node_id=node_id)
        raise ValueError(f"unsupported graph action: {action}")






