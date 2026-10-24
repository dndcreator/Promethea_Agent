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


async def _verify_semantics(page, document):
    """Compare a declaration to live DOM and bridge state, never infer meaning."""
    from computer.canvas_semantics import nodes
    components = [node.model_dump() | {"parent_id": parent} for node, parent in nodes(document)]
    await page.frame_locator('iframe').locator('body').wait_for(timeout=3000)
    frame = next(frame for frame in page.frames if urlsplit(frame.url).netloc == "canvas.invalid")
    # A component may commit asynchronously after the final browser step.
    await frame.wait_for_function("""components => {
      return components.every(node => {
        const element = document.getElementById(node.id);
        return element && (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLButtonElement) || !element.disabled);
      });
    }""", arg=components, timeout=3000)
    compare = """({components, values}) => {
      const errors = [];
      for (const node of components) {
        const matches = document.querySelectorAll('#' + CSS.escape(node.id));
        const element = matches[0];
        if (matches.length !== 1) { errors.push(node.id + ': missing or duplicate DOM id'); continue; }
        if (node.parent_id && !element.parentElement?.closest('#' + CSS.escape(node.parent_id))) errors.push(node.id + ': declared parent does not contain component');
        if (!element.getClientRects().length) errors.push(node.id + ': declared component is not rendered');
        if (node.type === 'button' && (element.tagName !== 'BUTTON' || element.textContent.trim() !== node.label)) errors.push(node.id + ': button does not match declaration');
        if (node.type === 'input' || node.type === 'checkbox') {
          if (element.tagName !== 'INPUT' || element.type !== (node.type === 'checkbox' ? 'checkbox' : node.input_type) || element.readOnly) errors.push(node.id + ': input type does not match declaration');
        }
        if (node.type === 'select') {
          if (element.tagName !== 'SELECT' || JSON.stringify(Array.from(element.options || [], option => option.value)) !== JSON.stringify(node.options.map(option => option.value))) errors.push(node.id + ': options do not match declaration');
        }
        if (['input','checkbox','select'].includes(node.type)) {
          if (!Array.from(element.labels || []).some(label => {
            const copy = label.cloneNode(true);
            for (const control of copy.querySelectorAll('input,select,textarea,button')) control.remove();
            return copy.textContent.trim() === node.label;
          })) errors.push(node.id + ': label does not match declaration');
          if (node.type === 'checkbox' ? element.checked !== values[node.bind] : element.value !== String(values[node.bind])) errors.push(node.id + ': visible value differs from Runtime app state');
        }
        if (node.type === 'text' && element.textContent !== String(node.bind ? values[node.bind] : node.text)) errors.push(node.id + ': text differs from declaration or Runtime app state');
      }
      return errors;
    }"""
    for attempt in range(10):
        state = await page.evaluate("window.canvasVerificationSnapshot()")
        values = {**document.initial_state, **state["value"]}
        failures = await frame.evaluate(compare, {"components": components, "values": values})
        if not failures or any("differs" not in failure for failure in failures):
            break
        await asyncio.sleep(0.05)
    return failures


async def _verify_state_updates(page, document, source):
    from computer.canvas_semantics import nodes, interact
    from computer.canvas_components import CanvasInput, CanvasCheckbox, CanvasSelect
    import hashlib
    state = await page.evaluate("window.canvasVerificationSnapshot()")
    original = {**document.initial_state, **state["value"]}
    revision = hashlib.sha256(source.encode()).hexdigest()
    tested = 0
    try:
        for node, _ in nodes(document):
            if not isinstance(node, (CanvasInput, CanvasCheckbox, CanvasSelect)):
                continue
            current = original[node.bind]
            if isinstance(node, CanvasSelect):
                value = next((option.value for option in node.options if option.value != current), current)
            elif isinstance(current, bool):
                value = not current
            elif type(current) in (int, float):
                value = 1 if current == 0 else 0
            else:
                value = "verification" if not current else ""
            if value == current:
                continue
            values = interact(source, {"value": original}, component_id=node.id, operation="set", value=value, definition_revision=revision)
            await page.evaluate("value => window.canvasVerificationSetState(value)", values)
            failures = await _verify_semantics(page, document)
            if failures:
                return failures, tested
            tested += 1
    finally:
        await page.evaluate("value => window.canvasVerificationSetState(value)", original)
    return await _verify_semantics(page, document), tested


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
    from computer.canvas_semantics import read_document, snapshot
    source = entry.read_text(encoding="utf-8")
    document = read_document(source)
    semantics = snapshot(source, {"value": {}, "revision": 0})
    semantic_report = {"status": semantics["status"], "component_count": len(semantics["components"]), "definition_revision": semantics["definition_revision"], "browser_verified": False}
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
              const ports = new Set();
              window.canvasVerificationSnapshot = () => structuredClone(state);
              window.canvasVerificationSetState = (value) => {
                state = {revision: state.revision + 1, value};
                for (const port of ports) port.postMessage({event:'state.changed', state});
              };
              const connect = () => {
                const channel = new MessageChannel();
                ports.add(channel.port1);
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
            if document is not None:
                try:
                    errors.extend(await _verify_semantics(page, document))
                except Exception as exc:
                    errors.append("Semantic contract verification failed: " + str(exc)[:2000])
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
            if document is not None and not errors:
                try:
                    errors.extend(await _verify_semantics(page, document))
                    if not errors:
                        failures, tested = await _verify_state_updates(page, document, source)
                        errors.extend(failures)
                        semantic_report["state_update_checks"] = tested
                    semantic_report["browser_verified"] = not errors
                except Exception as exc:
                    errors.append("Semantic state verification failed: " + str(exc)[:2000])
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot), full_page=True)
        finally:
            await browser.close()
    return {"ok": not errors, "errors": errors[:16], "steps": steps, "screenshot": str(screenshot), "semantics": semantic_report}
