import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agentkit.mcp.invocation_context import bind_invocation_context
from agentkit.tools.self_evolve.canvas import verify_canvas
from agentkit.tools.self_evolve.self_evolve import SelfEvolveService
from computer.canvas_components import CanvasDocument, render_component_document
from computer.canvas_document import render_canvas_html
from computer.canvas_document import canvas_csp
from gateway.public_contracts import build_public_contract_schema


def document():
    return {
        "version": "canvas.ui.v1", "title": "Trip budget", "language": "en",
        "initial_state": {"price": 12.5, "quantity": 2, "total": 0, "done": False, "note": "", "mode": "train"},
        "root": {"type": "stack", "id": "budget", "children": [
            {"type": "text", "id": "title", "text": "Trip budget", "emphasis": "heading"},
            {"type": "stack", "id": "fields", "direction": "row", "children": [
                {"type": "input", "id": "price", "label": "Price", "bind": "price", "input_type": "number"},
                {"type": "input", "id": "quantity", "label": "Quantity", "bind": "quantity", "input_type": "number"},
            ]},
            {"type": "button", "id": "calculate", "label": "Calculate", "actions": [
                {"op": "calculate", "field": "total", "operation": "product", "inputs": ["price", "quantity"]},
            ]},
            {"type": "text", "id": "total", "bind": "total"},
            {"type": "checkbox", "id": "done", "label": "Booked", "bind": "done"},
            {"type": "input", "id": "note", "label": "Note", "bind": "note"},
            {"type": "select", "id": "mode", "label": "Travel", "bind": "mode", "options": [
                {"label": "Train", "value": "train"}, {"label": "Bus", "value": "bus"},
            ]},
            {"type": "table", "id": "rates", "columns": ["Mode", "Price"], "rows": [["Train", 12.5], ["Bus", 8]]},
        ]},
    }


def test_public_schema_has_one_component_source_and_deterministic_rendering():
    value = document()
    bundle = build_public_contract_schema()
    assert bundle["$defs"]["CanvasDocument"]["additionalProperties"] is False
    assert bundle["$defs"]["CanvasStack"]["properties"]["children"]["items"]["discriminator"]["propertyName"] == "type"
    assert render_component_document(value) == render_component_document(value)
    assert "canvas_components.js" not in render_component_document(value)  # self-contained artifact
    assert CanvasDocument.model_validate(value).initial_state["price"] == 12.5


@pytest.mark.parametrize("change", [
    lambda value: value.update(script="alert(1)"),
    lambda value: value["root"]["children"].append({"type": "iframe", "id": "unsafe", "src": "https://example.com"}),
    lambda value: value["root"]["children"][0].update(id="budget"),
    lambda value: value["root"]["children"][0].update(id="canvas_document"),
    lambda value: value["root"]["children"][3].update(bind="unknown"),
    lambda value: value["initial_state"].update(price=True),
    lambda value: value["initial_state"].update(mode="plane"),
    lambda value: value["initial_state"].update(constructor="unsafe"),
    lambda value: value["initial_state"].update(price=float("nan")),
    lambda value: value["root"]["children"][2]["actions"][0].update(operation="eval"),
    lambda value: value["root"]["children"][2]["actions"][0].update(inputs=["done"]),
    lambda value: value["root"]["children"][2]["actions"][0].update(op="set", value="bad", inputs=[], operation=None),
    lambda value: value["root"]["children"][-1].update(rows=[[1]]),
    lambda value: value.update(title="x" * 64_001),
])
def test_invalid_component_documents_are_rejected(change):
    value = document()
    change(value)
    with pytest.raises(ValueError):
        render_component_document(value)


def test_component_limits_and_literals_cannot_inject_html_or_scripts():
    value = document()
    value["title"] = '</title><script>window.injected=true</script>'
    value["root"]["children"][0]["text"] = '</script><img src=x onerror="window.injected=true">'
    source = render_component_document(value)
    assert "</title><script>window.injected" not in source
    assert '</script><img src=x' not in source
    injected = render_canvas_html(source)
    assert injected.index("Object.defineProperty(window, 'promethea'") < injected.index("const doc = JSON.parse")
    for index in range(10):
        value["root"] = {"type": "stack", "id": f"stack{index}", "children": [value["root"]]}
    with pytest.raises(ValueError, match="limit"):
        render_component_document(value)


@pytest.mark.asyncio
async def test_composition_reuses_owned_staging_checkpoints_and_validation(tmp_path, monkeypatch):
    with bind_invocation_context({"user_id": "alice"}):
        service = SelfEvolveService(str(tmp_path))
        spec = {"tests": [{"action": "click", "selector": "#calculate"}, {"action": "expect_text", "selector": "#total", "value": "25"}]}
        task = (await service.evolve_create_task(goal="Budget", capability_id="budget", version="1.0", description="Budget", canvas=spec))["task"]
        task_id = task["task_id"]
        schema = await service.evolve_get_canvas_schema()
        assert schema["schema"] == CanvasDocument.model_json_schema()
        await service.evolve_compose_canvas(task_id, document())
        source = (service._task_root(task_id) / "index.html").read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="changed since inspection"):
            await service.evolve_compose_canvas(task_id, document(), expected_sha256="stale")
        validate = AsyncMock(return_value={"ok": True, "errors": [], "steps": []})
        monkeypatch.setattr("agentkit.tools.self_evolve.self_evolve.verify_canvas", validate)
        assert (await service.evolve_validate(task_id))["ok"]
        changed = document()
        changed["title"] = "Updated budget"
        await service.evolve_compose_canvas(task_id, changed)
        task = service._get_task_or_raise(task_id)
        assert task["status"] == "draft" and "validated_digest" not in task
        await service.evolve_restore(task_id, task["checkpoints"][-1]["checkpoint_id"])
        assert (service._task_root(task_id) / "index.html").read_text(encoding="utf-8") == source
        with bind_invocation_context({"user_id": "bob"}):
            with pytest.raises(FileNotFoundError):
                await service.evolve_compose_canvas(task_id, document())
        assert (await service.evolve_validate(task_id))["ok"]
        await service.evolve_publish(task_id)
        with pytest.raises(PermissionError, match="immutable"):
            await service.evolve_compose_canvas(task_id, document())


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser: CANVAS_TEST_BROWSER_CHANNEL")
@pytest.mark.parametrize("selection", ["automatic", "configured"])
async def test_component_browser_interaction_uses_existing_verifier(tmp_path, monkeypatch, selection):
    from config import config

    monkeypatch.setattr(config.system, "browser_auto_install", False)
    monkeypatch.setattr(config.system, "browser_channel", "")
    (tmp_path / "index.html").write_text(render_component_document(document()), encoding="utf-8")
    result = await verify_canvas(tmp_path, {"tests": [
        {"action": "fill", "selector": "#quantity", "value": "3"},
        {"action": "click", "selector": "#calculate"},
        {"action": "expect_text", "selector": "#total", "value": "37.5"},
        {"action": "check", "selector": "#done"},
        {"action": "select", "selector": "#mode", "value": "bus"},
        {"action": "expect_count", "selector": "tbody tr", "value": "2"},
    ]}, tmp_path.parent / "components.png", browser_channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"] if selection == "configured" else "")
    assert result["ok"], result


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser: CANVAS_TEST_BROWSER_CHANNEL")
async def test_component_browser_persistence_conflict_and_safe_text(tmp_path):
    from playwright.async_api import async_playwright, expect

    value = document()
    value["root"]["children"].extend([
        {"type": "text", "id": "note_view", "bind": "note"},
        {"type": "button", "id": "add", "label": "Add", "actions": [{"op": "increment", "field": "quantity", "value": 1}]},
        {"type": "button", "id": "toggle", "label": "Toggle", "actions": [{"op": "toggle", "field": "done"}]},
        {"type": "button", "id": "reset", "label": "Reset", "actions": [{"op": "reset"}]},
        {"type": "button", "id": "zero", "label": "Zero", "actions": [{"op": "set", "field": "quantity", "value": 0}]},
        {"type": "button", "id": "divide", "label": "Divide", "actions": [{"op": "calculate", "field": "total", "operation": "ratio", "inputs": ["price", "quantity"]}]},
    ])
    html = render_canvas_html(render_component_document(value))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await context.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html", headers={"Content-Security-Policy": canvas_csp()}))
            await page.set_content('<style>body{margin:0}iframe{border:0;width:100vw;height:100vh}</style><iframe sandbox="allow-scripts" src="http://canvas.invalid/index.html"></iframe>')
            await page.evaluate("""() => {
              window.saved = {revision:0, value:{}}; window.saves = 0;
              const frame = document.querySelector('iframe');
              const connect = () => {
                const channel = new MessageChannel();
                channel.port1.onmessage = ({data}) => {
                  setTimeout(() => {
                    if (data.method === 'state.set') {
                      window.saves++;
                      if (data.params.expected_revision !== window.saved.revision) {
                        channel.port1.postMessage({id:data.id, error:'state revision conflict'});return;
                      }
                      window.saved = {revision:window.saved.revision+1, value:data.params.value};
                    }
                    channel.port1.postMessage({id:data.id,result:window.saved});
                  }, 50);
                };
                frame.contentWindow.postMessage({type:'promethea:connect'}, '*', [channel.port2]);
              };
              frame.addEventListener('load', connect);connect();
            }""")
            frame = page.frame_locator('iframe')
            await expect(frame.locator('#calculate')).to_be_enabled()
            await frame.locator('#quantity').fill('3')
            await frame.locator('#calculate').click()
            await expect(frame.locator('#total')).to_have_text('37.5')
            attack = '<img src=x onerror="window.injected=true">'
            await frame.locator('#note').fill(attack)
            await page.wait_for_function('(value) => window.saved.value.note === value', arg=attack)
            assert await frame.locator('#note').evaluate('(input) => document.activeElement === input')
            before = await page.evaluate('window.saves')
            await frame.locator('#note').evaluate('''input => {
              for (let i=0; i<50; i++) {
                input.value = String(i);input.dispatchEvent(new Event('input', {bubbles:true}));
              }
            }''')
            await page.wait_for_function("window.saved.value.note === '49'")
            assert await page.evaluate('window.saves') <= before + 2
            await frame.locator('#note').fill(attack)
            await page.wait_for_function('(value) => window.saved.value.note === value', arg=attack)
            await frame.locator('#toggle').click()
            await expect(frame.locator('#done')).to_be_checked()
            await expect(frame.locator('#note_view')).to_have_text(attack)
            assert await frame.locator('img').count() == 0
            assert await frame.locator('body').evaluate('() => window.injected') is None
            assert await frame.locator('body').evaluate("() => {try {return parent.document.body.innerHTML} catch {return 'isolated'}}") == 'isolated'
            await page.evaluate("document.querySelector('iframe').src += '?reload=1'")
            await expect(frame.locator('#total')).to_have_text('37.5')
            await expect(frame.locator('#done')).to_be_checked()
            await expect(frame.locator('#note')).to_have_value(attack)
            output = Path(os.environ.get("CANVAS_TEST_ARTIFACTS", str(tmp_path)))
            output.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output / 'desktop.png'), full_page=True)
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(path=str(output / 'mobile.png'), full_page=True)
            assert await frame.locator('body').evaluate('() => document.documentElement.scrollWidth <= innerWidth')
            await frame.locator('#reset').click()
            await expect(frame.locator('#total')).to_have_text('0')
            await expect(frame.locator('#quantity')).to_have_value('2')
            await frame.locator('#zero').click()
            await expect(frame.locator('#quantity')).to_have_value('0')
            saves = await page.evaluate('window.saves')
            await frame.locator('#divide').click()
            await expect(frame.locator('#canvas_status')).to_have_text('Division by zero')
            assert await page.evaluate('window.saves') == saves
            await frame.locator('#add').click()
            await expect(frame.locator('#quantity')).to_have_value('1')
            saves = await page.evaluate('window.saves')
            await page.evaluate('window.saved.revision++;window.saved.value.quantity=9')
            await frame.locator('#add').click()
            await expect(frame.locator('#canvas_status')).to_have_text('state revision conflict')
            await expect(frame.locator('#add')).to_be_disabled()
            assert await page.evaluate('window.saves') == saves + 1
            await page.evaluate("document.querySelector('iframe').src += '&reload=2'")
            await expect(frame.locator('#quantity')).to_have_value('9')
            await expect(frame.locator('#add')).to_be_enabled()
            assert not errors, errors
        finally:
            await browser.close()
