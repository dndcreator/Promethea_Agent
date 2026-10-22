import os

import pytest


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser: CANVAS_TEST_BROWSER_CHANNEL"),
]


async def test_chat_links_selection_annotations_and_mobile(tmp_path):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    source = '\U0001f600 See [paper](https://example.org/p?q=1&x=2) and selected text.\n`https://example.org/code`\n[bad](javascript:alert(1))\n<script>window.injected=true</script>\n' + 'https://example.org/' + 'x' * 220
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1200, "height": 850})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base + "/tests/message-content.html")
            await page.wait_for_function("typeof window.renderMessage === 'function'")
            await page.evaluate("source => window.renderMessage(source)", source)
            await expect(page.locator("#message a")).to_have_count(2)
            link = page.get_by_role("link", name="paper", exact=True)
            await expect(link).to_have_attribute("href", "https://example.org/p?q=1&x=2")
            await expect(link).to_have_attribute("rel", "noopener noreferrer")
            assert not await page.evaluate("Boolean(window.injected)")

            async def select(text):
                return await page.evaluate("""text => {
                  const root = document.getElementById('message');
                  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                  let node;
                  while ((node = walker.nextNode())) {
                    const start = node.textContent.indexOf(text);
                    if (start < 0) continue;
                    const range = document.createRange();
                    range.setStart(node, start); range.setEnd(node, start + text.length);
                    window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
                    return window.selectedSource();
                  }
                  throw new Error('Text not found');
                }""", text)

            selected = await select("selected text")
            start = source.index("selected text")
            assert selected == {"selectedText": "selected text", "startOffset": start, "endOffset": start + len("selected text")}
            label = await select("paper")
            assert label["startOffset"] == source.index("paper")
            annotation = {"id": "followup-1", "start_offset": start, "end_offset": start + 13, "selected_text": "selected text", "query": "Why?", "response": "Stored reply"}
            await page.evaluate("([source, annotation]) => window.renderMessage(source, [annotation])", [source, annotation])
            await expect(page.get_by_title("Why?\n\nStored reply", exact=True)).to_have_text("selected text")
            assert (await select("selected text"))["startOffset"] == start

            # Selecting across a shortened link maps to one exact original slice.
            await page.evaluate("""() => {
              const range = document.createRange(); range.selectNodeContents(document.getElementById('message'));
              window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
            }""")
            assert (await page.evaluate("window.selectedSource()"))["selectedText"] == source
            for width in (1200, 390):
                await page.set_viewport_size({"width": width, "height": 850})
                assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                await page.screenshot(path=str(tmp_path / f"message-links-{width}.png"))
            assert errors == []
        finally:
            await browser.close()


async def test_artifact_links_use_authenticated_sdk_and_download_active_content():
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.goto(base + "/tests/message-content.html")
            await page.wait_for_function("typeof window.renderMessage === 'function'")
            await page.evaluate("""() => {
              localStorage.setItem('auth_token', 'test-only-token');
              window.previews = []; window.downloads = [];
              window.open = () => {
                const preview = {closed:false, location:{replace:url => {preview.url=url}}, close:() => {preview.closed=true}};
                window.previews.push(preview); return preview;
              };
              HTMLAnchorElement.prototype.click = function() { window.downloads.push(this.download); };
            }""")
            requests = []

            async def artifact(route):
                requests.append(route.request)
                await route.fulfill(body="<script>window.injected=true</script>", content_type="text/html")

            await page.route("**/api/workbench/artifact?**", artifact)
            await page.evaluate("window.renderMessage('[Report](/api/workbench/artifact?workspace_id=s1&path=report.html)')")
            await page.get_by_role("link", name="Report", exact=True).click()
            await page.wait_for_function("window.downloads.length === 1")
            assert len(requests) == 1
            assert requests[0].headers["authorization"] == "Bearer test-only-token"
            assert "workspace_id=s1" in requests[0].url and "path=report.html" in requests[0].url
            assert await page.evaluate("window.previews[0].closed && !window.previews[0].url && !window.injected")
            assert await page.evaluate("window.downloads[0]") == "report.html"

            await page.unroute("**/api/workbench/artifact?**", artifact)
            await page.route("**/api/workbench/artifact?**", lambda route: route.fulfill(body="%PDF-test", content_type="application/pdf"))
            await page.get_by_role("link", name="Report", exact=True).click()
            await page.wait_for_function("window.previews[1]?.url?.startsWith('blob:')")
            assert await page.evaluate("!window.previews[1].closed && window.downloads.length === 1")
            await page.unroute("**/api/workbench/artifact?**")
            await page.route("**/api/workbench/artifact?**", lambda route: route.fulfill(status=404, json={"detail": "Artifact not found"}))
            await page.get_by_role("link", name="Report", exact=True).click()
            await expect(page.get_by_role("alert")).to_be_visible()
            assert await page.evaluate("window.previews[2].closed")
        finally:
            await browser.close()


async def test_real_chat_followup_bubble_save_and_reload(tmp_path):
    from playwright.async_api import async_playwright, expect

    base = os.environ.get("PROMETHEA_UI_TEST_URL", "http://127.0.0.1:5177").rstrip("/")
    source = '\U0001f600 See [paper](https://example.org/paper). Select this sentence.\nhttps://example.org/' + 'x' * 220
    saved = []

    async def api(route):
        path = route.request.url.split("/api/", 1)[-1].split("?", 1)[0]
        if path == "user/profile":
            data = {"user_id": "test-user", "username": "Test", "agent_name": "Promethea"}
        elif path == "sessions/test-session":
            data = {"messages": [{"id": "message-1", "role": "assistant", "content": source,
                    "reasoning_tree_id": "test-tree", "reasoning_steps": [{"step_id": "model-1", "source": "provider", "content": "Check the selected source before answering."}]}],
                    "session_info": {"followups": saved}}
        elif path == "reasoning/tree/test-tree":
            data = {"nodes": [{"node_id": "node-1", "kind": "think", "status": "succeeded", "title": "Inspect source", "summary": "The source has been checked."}]}
        elif path == "followup":
            payload = route.request.post_data_json
            assert source[payload["start_offset"]:payload["end_offset"]] == payload["selected_text"] == "Select this sentence."
            annotation = {**payload, "id": "saved-1", "query": "Why?", "response": "Persisted answer", "created_at": 1}
            saved.append(annotation)
            data = {"followup": annotation}
        elif path == "workbench/stream":
            await route.fulfill(body='event: snapshot\ndata: {"timeline":[],"cursor":0}\n\n', content_type="text/event-stream")
            return
        else:
            data = {}
        await route.fulfill(json=data)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1200, "height": 850})
            await page.add_init_script("localStorage.setItem('auth_token', 'test-only-token')")
            await page.route("**/api/**", api)
            await page.goto(base + "/tests/message-content.html?chat")
            await expect(page.get_by_role("link", name="paper", exact=True)).to_be_visible()
            await expect(page.get_by_text("检测到记忆冲突，等待确认。", exact=True)).to_be_visible()
            process = page.get_by_role("button").filter(has_text="1 段思考").first
            await expect(process).to_contain_text("1 个推理步骤")
            await expect(process).to_have_attribute("aria-expanded", "false")
            await expect(page.get_by_text("模型思考 1", exact=True)).to_have_count(0)
            await process.click()
            await expect(page.get_by_text("模型思考 1", exact=True)).to_be_visible()
            await expect(page.get_by_text("分析当前步骤", exact=True)).to_be_visible()
            await page.get_by_text("模型思考 1", exact=True).click()
            await expect(page.locator("details[open]")).to_have_count(1)
            await process.click()
            await expect(process).to_have_attribute("aria-expanded", "false")
            await page.evaluate("""() => {
              for (const span of document.querySelectorAll('main [data-source-start]')) {
                const walker = document.createTreeWalker(span, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                  const start = node.textContent.indexOf('Select this sentence.');
                  if (start < 0) continue;
                  const range = document.createRange(); range.setStart(node, start); range.setEnd(node, start+21);
                  window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
                  span.dispatchEvent(new MouseEvent('mouseup', {bubbles:true})); return;
                }
              }
              throw new Error('Missing selection target');
            }""")
            await page.get_by_role("button", name="追问", exact=True).click()
            await expect(page.locator("blockquote")).to_have_text("Select this sentence.")
            await page.get_by_role("button", name="开始追问", exact=True).click()
            await expect(page.get_by_title("Why?\n\nPersisted answer", exact=True)).to_be_visible()
            assert len(saved) == 1
            await page.reload()
            await expect(page.get_by_title("Why?\n\nPersisted answer", exact=True)).to_be_visible()
            for width in (1200, 390):
                await page.set_viewport_size({"width": width, "height": 850})
                assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                await page.screenshot(path=str(tmp_path / f"chat-links-{width}.png"))
        finally:
            await browser.close()
