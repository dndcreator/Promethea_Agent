"""Bounded canvas artifacts and browser verification owned by Self Evolve."""
from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, quote

from pydantic import BaseModel, ConfigDict, Field
from computer.canvas_document import artifact_files, render_canvas_html, canvas_csp
from computer.browser_runtime import launch_browser


class BrowserStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern="^(click|fill|check|select|expect_text|expect_count)$")
    selector: str = Field(min_length=1, max_length=500)
    value: str = Field(default="", max_length=4000)


class CanvasSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entrypoint: str = "index.html"
    tests: list[BrowserStep] = Field(min_length=1, max_length=32)


async def verify_canvas(root: Path, spec: dict[str, Any], screenshot: Path, *, browser_channel: str = "") -> dict[str, Any]:
    """Run declared interactions without host credentials, internet, or file URLs."""
    from playwright.async_api import async_playwright

    definition = CanvasSpec.model_validate(spec)
    files = artifact_files(root)
    entry = (root / definition.entrypoint).resolve()
    entry.relative_to(root.resolve())
    if entry not in files or entry.suffix.lower() != ".html":
        raise ValueError("canvas entrypoint must be a packaged HTML file")
    errors: list[str] = []
    steps = []
    async with async_playwright() as playwright:
        browser = await launch_browser(playwright, headless=True, chromium_sandbox=True, channel=browser_channel)
        try:
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)[:1000]))
            page.on("console", lambda message: errors.append(message.text[:1000]) if message.type == "error" else None)

            async def route_request(route):
                url = urlsplit(route.request.url)
                target = (root / unquote(url.path).lstrip("/")).resolve()
                if url.netloc != "canvas.invalid" or target not in files:
                    errors.append(f"Blocked undeclared resource: {url.path[:200]}")
                    await route.abort()
                    return
                body = render_canvas_html(target.read_text(encoding="utf-8"), root=root, entrypoint=target) if target.suffix == ".html" else target.read_bytes()
                await route.fulfill(body=body, headers={"Content-Security-Policy": canvas_csp()}, content_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")

            await context.route("**/*", route_request)
            async def block_websocket(route):
                errors.append("Outbound WebSocket is not permitted during canvas verification")
                await route.close()
            await context.route_web_socket("**/*", block_websocket)
            # Exercise the actual opaque iframe bridge, not a different in-page API.
            await page.set_content(f'<style>html,body{{margin:0;height:100%}}iframe{{width:100%;height:100%;border:0}}</style><iframe sandbox="allow-scripts" src="http://canvas.invalid/{quote(definition.entrypoint, safe="/")}"></iframe>')
            await page.evaluate("""() => {
              const frame = document.querySelector('iframe');
              let state = {revision: 0, value: {}};
              const connect = () => {
                const channel = new MessageChannel();
                channel.port1.onmessage = ({data}) => {
                  if (data.method === 'state.set') {
                    if (data.params.expected_revision !== state.revision) {
                      channel.port1.postMessage({id:data.id, error:'state revision conflict'}); return;
                    }
                    state = {revision:state.revision + 1, value:data.params.value};
                  }
                  channel.port1.postMessage({id:data.id, result:state});
                };
                frame.contentWindow.postMessage({type:'promethea:connect'}, '*', [channel.port2]);
              };
              frame.addEventListener('load', connect);
              connect();
            }""")
            for step in definition.tests:
                locator = page.frame_locator('iframe').locator(step.selector)
                try:
                    if step.action == "click":
                        await locator.click(timeout=3000)
                    elif step.action == "fill":
                        await locator.fill(step.value, timeout=3000)
                    elif step.action == "check":
                        await locator.check(timeout=3000)
                    elif step.action == "select":
                        await locator.select_option(step.value, timeout=3000)
                    else:
                        from playwright.async_api import expect
                        if step.action == "expect_text":
                            await expect(locator).to_have_text(step.value, timeout=3000)
                        else:
                            await expect(locator).to_have_count(int(step.value), timeout=3000)
                    steps.append({**step.model_dump(), "ok": True})
                except Exception as exc:
                    steps.append({**step.model_dump(), "ok": False, "error": str(exc)[:2000]})
                    errors.append(str(exc)[:2000])
                    break
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot), full_page=True)
        finally:
            await browser.close()
    return {"ok": not errors, "errors": errors[:16], "steps": steps, "screenshot": str(screenshot)}
