"""Full App/production launcher/native provider wire/approval/process restart.

Default upstream is scripted HTTP. The separately opted-in live case is metered.
Neither run treats model self-report as proof of a file or a side effect.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import threading

import pytest

from tests.support.production import prepare_deployment, production_server, production_ui, free_port

pytestmark = [pytest.mark.browser, pytest.mark.asyncio,
              pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in browser acceptance")]

REQUEST = ("按顺序完成隔离验收，每一步分别调用工具，不要批量：先用 workspace.write_file 写 native-live.txt，"
           "内容严格为 NATIVE-LIVE-29；再调用 fixture.publish，text 为 NATIVE-LIVE-29，等待用户批准；"
           "批准后用 workspace.read_file 读取 native-live.txt 验证内容；最后回复 NATIVE-DONE-29。"
           "fixture.publish 只是本地验收收据，没有真实发送行为，仍必须由 Runtime 审批。")


@contextmanager
def scripted_provider():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request)
            if request.get("tools"):
                prior = [call for row in request["messages"] for call in row.get("tool_calls", [])]
                names = [json.loads(call["function"]["arguments"]).get("tool_name") for call in prior]
                if "workspace.write_file" not in names:
                    name, args = "workspace.write_file", {"path": "native-live.txt", "content": "NATIVE-LIVE-29"}
                elif "fixture.publish" not in names:
                    name, args = "fixture.publish", {"text": "NATIVE-LIVE-29"}
                elif "workspace.read_file" not in names:
                    name, args = "workspace.read_file", {"path": "native-live.txt"}
                else:
                    name = None
                message = {"role": "assistant", "content": "NATIVE-DONE-29"}
                if name:
                    message = {"role": "assistant", "content": None, "tool_calls": [{"id": "native_" + str(len(prior)), "type": "function",
                               "function": {"name": "tool_call", "arguments": json.dumps({"tool_name": name, "args": args})}}]}
            else:
                message = {"role": "assistant", "content": json.dumps({"greeting": "你好。", "context_hint": "", "suggested_actions": ["开始"]})}
            usage = {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50}
            base = {"id": "fixture", "created": 0, "model": "fixture"}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
            self.end_headers()
            if request.get("stream"):
                delta = {key: value for key, value in message.items() if key != "role"}
                if delta.get("tool_calls"):
                    delta["tool_calls"][0]["index"] = 0
                packets = [{**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]},
                           {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage}]
                for packet in packets:
                    self.wfile.write(b"data: " + json.dumps(packet).encode() + b"\n\n")
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(json.dumps({**base, "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}], "usage": usage}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


async def production_journey(root, endpoint, model, output):
    from playwright.async_api import async_playwright, expect

    prepare_deployment(root)
    path = root / "config/default.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(memory={"enabled": False}, ambient={"enabled": False},
               action={"max_steps": 6, "gaps": {"enabled": False}})
    cfg["api"].update(base_url=endpoint, api_key="test-proxy-only", model=model, tool_protocol="native", timeout=120,
                      max_tokens=8192, output_token_limit=8192)
    path.write_text(json.dumps(cfg), encoding="utf-8")
    manifest = root / "extensions/community/native-acceptance/agent-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": "native-acceptance", "version": "1.0.0", "serviceType": "tool",
                                   "entryPoint": {"module": "tests.support.native_fixture", "factory": "create_tools"}}), encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    port = free_port()
    host = production_server(root, port=port)
    gateway, log = host.__enter__()
    try:
        with production_ui(root, gateway) as base:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
                try:
                    page = await browser.new_page(viewport={"width": 1440, "height": 960})
                    await page.add_init_script("localStorage.setItem('promethea_ui_lang','zh')")
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(base)
                    await page.locator(".rail-account").click()
                    await page.get_by_role("button", name="还没有账号？注册", exact=True).click()
                    dialog = page.get_by_role("dialog", name="注册", exact=True)
                    await dialog.get_by_label("用户名", exact=True).fill("native-acceptance")
                    await dialog.get_by_label("密码", exact=True).fill("disposable-password")
                    await dialog.get_by_role("button", name="注册", exact=True).click()
                    await expect(page.get_by_text("注册成功，请登录。", exact=True)).to_be_visible()
                    await page.get_by_role("dialog").get_by_label("密码", exact=True).fill("disposable-password")
                    await page.get_by_role("dialog").get_by_role("button", name="登录", exact=True).click()
                    await expect(page.locator(".rail-account")).to_have_attribute("title", "native-acceptance")
                    await page.get_by_placeholder("输入消息", exact=True).fill(REQUEST)
                    await page.get_by_title("发送", exact=True).click()
                    modal = page.get_by_role("dialog", name="敏感操作确认", exact=True)
                    await expect(modal).to_be_visible(timeout=300000)
                    await expect(modal).to_contain_text("fixture.publish")
                    receipt = root / "fixture-receipts.jsonl"
                    assert not receipt.exists(), "tool ran before approval"
                    files = list(root.rglob("native-live.txt"))
                    assert len(files) == 1 and files[0].read_text(encoding="utf-8") == "NATIVE-LIVE-29"
                    await page.screenshot(path=str(output / "waiting-before-restart.png"))
                    host.__exit__(None, None, None)
                    host = production_server(root, port=port)
                    host.__enter__()
                    await page.reload()
                    await page.locator(".session-select").first.click(timeout=30000)
                    await expect(modal).to_be_visible(timeout=30000)
                    assert not receipt.exists()
                    await page.screenshot(path=str(output / "restored-confirmation.png"))
                    await modal.get_by_role("button", name="批准", exact=True).click()
                    await expect(modal).not_to_be_visible(timeout=300000)
                    await expect(page.locator(".conversation-surface")).to_contain_text("NATIVE-DONE-29", timeout=30000)
                    assert [json.loads(row) for row in receipt.read_text().splitlines()] == [{"text": "NATIVE-LIVE-29"}]
                    host.__exit__(None, None, None)
                    host = production_server(root, port=port)
                    host.__enter__()
                    await page.reload()
                    await page.locator(".session-select").first.click(timeout=30000)
                    await expect(page.locator(".conversation-surface")).to_contain_text("NATIVE-DONE-29", timeout=30000)
                    assert len(receipt.read_text().splitlines()) == 1
                    assert files[0].read_text(encoding="utf-8") == "NATIVE-LIVE-29"
                    assert not await modal.count()
                    assert not errors, errors
                    event_path = root / "gateway/runtime_events.jsonl"
                    events = [json.loads(row) for row in event_path.read_text(encoding="utf-8").splitlines()]
                    observations = [row["payload"] for row in events if row["event_type"] == "action.observation.committed"]
                    assert any(row.get("tool_name") == "workspace.read_file" and row.get("ok") for row in observations)
                    shutil.copyfile(event_path, output / "runtime-events.jsonl")
                    await page.screenshot(path=str(output / "completed-after-restart.png"))
                    return {"completed": True, "read_observation_verified": True, "approval_restored": True, "side_effect_count": 1, "restarts": 2, "browser_errors": errors}
                finally:
                    if browser.contexts and browser.contexts[0].pages:
                        await page.screenshot(path=str(output / "last-state.png"))
                    await browser.close()
    finally:
        host.__exit__(None, None, None)
        shutil.copyfile(log, output / "launcher.log")


async def test_native_production_approval_restored_after_process_restart(tmp_path):
    from tests.support.metered_proxy import MeteredProxy
    with scripted_provider() as (endpoint, calls):
        output = Path(".tmp/native-production-offline")
        proxy = MeteredProxy({"PROMETHEA_EVAL_AGENT_BASE_URL": endpoint, "PROMETHEA_EVAL_AGENT_API_KEY": "fixture-only",
                              "PROMETHEA_EVAL_AGENT_MODEL": "fixture"}, (0, 0), output, ceiling=.10)
        with proxy.serve() as metered:
            result = await production_journey(tmp_path / "deployment", metered, "fixture", output)
    assert result["completed"]
    assert proxy.budget.usage_known and proxy.budget.calls == len(proxy.receipts)
    assert any(row.get("stream") and row.get("tools") for row in calls)
    assert any(row["role"] == "tool" for call in calls for row in call["messages"])


@pytest.mark.skipif(os.environ.get("PROMETHEA_NATIVE_LIVE_USD") != "0.10", reason="requires explicit separate live authorization")
async def test_native_production_live_authorized_ten_cents(tmp_path):
    from tests.support.metered_proxy import MeteredProxy
    from tests.support.runtime_efficiency import eval_settings
    values, _, rates = eval_settings(Path(".env.eval"))
    output = Path(".tmp/native-production-live")
    carry = None
    if (output / "requests.jsonl").exists():
        assert os.environ.get("PROMETHEA_NATIVE_LIVE_RESUME") == "1", "do not silently reuse a paid run ledger"
        report = output / "report.json"
        carry = json.loads(report.read_text(encoding="utf-8"))
        shutil.copyfile(report, output / ("report-before-" + str(carry["calls"]) + ".json"))
    proxy = MeteredProxy(values, rates, output, ceiling=.10, carry=carry)
    result = {"completed": False}
    try:
        with proxy.serve() as endpoint:
            result = await production_journey(tmp_path / "deployment", endpoint, proxy.model, output)
        assert proxy.budget.usage_known
        assert proxy.budget.calls == len(proxy.receipts), "every admitted request needs a settled receipt"
        assert any(row["native"] and row["stream"] and row["chunks"] > 1 for row in proxy.receipts)
    finally:
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps({**result, "calls": proxy.budget.calls,
            "conservative_cost_usd": proxy.budget.cost_usd, "usage_known": proxy.budget.usage_known,
            "stop_reason": proxy.stop_reason, "rates": rates, "receipts": proxy.receipts}, indent=2), encoding="utf-8")
