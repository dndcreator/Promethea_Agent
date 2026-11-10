"""Speech settings and chat interactions with synthetic audio/provider responses."""
import io
import asyncio
import json
import os
import wave
from pathlib import Path

import pytest

from tests.test_frontend_workspace_browser import prepare

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get("CANVAS_TEST_BROWSER_CHANNEL"), reason="opt-in real browser")]


def wav_audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 1600)
    return output.getvalue()


async def test_microphone_waits_for_configuration_without_blocking_text_input():
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ['CANVAS_TEST_BROWSER_CHANNEL'], headless=True, chromium_sandbox=True)
        ready = asyncio.Event()
        try:
            page = await browser.new_page()
            _, _, errors = await prepare(page)

            async def status(route):
                await ready.wait()
                endpoint = {"provider": "openai", "model": "speech", "base_url": "http://localhost:9999/v1", "configured": True, "api_key_configured": False}
                await route.fulfill(json={"stt": endpoint, "tts": endpoint, "speak_replies": False})

            await page.route('**/api/voice/status', status)
            await page.goto(os.environ['PROMETHEA_UI_TEST_URL'])
            await expect(page.get_by_role('button', name='正在读取语音配置', exact=True)).to_be_disabled()
            await page.get_by_placeholder('输入消息').fill('文字对话不受语音配置加载影响')
            await expect(page.get_by_role('button', name='发送', exact=True)).to_be_enabled()
            ready.set()
            await expect(page.get_by_role('button', name='语音输入', exact=True)).to_be_enabled()
            assert not errors
        finally:
            ready.set()
            await browser.close()


@pytest.mark.parametrize("width", [1440, 390])
async def test_voice_settings_save_discovery_synthesis_and_transcription(width):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": width, "height": 900})
            _, _, errors = await prepare(page)
            endpoint = {"provider": "disabled", "base_url": "", "model": "", "voice": "alloy", "format": "wav", "speed": 1, "configured": False, "api_key_configured": False}
            state = {"stt": dict(endpoint), "tts": dict(endpoint), "speak_replies": False}
            calls = []

            async def api(route):
                path = route.request.url.split('/api/', 1)[-1].split('?')[0]
                calls.append((path, route.request.post_data_buffer))
                if path == 'config':
                    await route.fulfill(json={"config": {"api": {}, "memory": {}}})
                elif path == 'voice/status':
                    await route.fulfill(json=state)
                elif path == 'config/secrets':
                    if route.request.method == 'POST':
                        body = route.request.post_data_json
                        values = body.get('values', body.get('secrets', body))
                        for kind in ('stt', 'tts'):
                            for field in ('provider', 'model', 'base_url', 'voice', 'format'):
                                key = f'VOICE__{kind.upper()}_{field.upper()}'
                                if key in values:
                                    state[kind][field] = values[key]
                            state[kind]['configured'] = state[kind]['provider'] != 'disabled'
                        state['speak_replies'] = values.get('VOICE__SPEAK_REPLIES') == 'true'
                    await route.fulfill(json={"status": "success", "secrets": {}})
                elif path == 'voice/models':
                    await route.fulfill(json={"models": ['speech-model']})
                elif path == 'voice/tts':
                    assert route.request.post_data_json['text'] == '你好，测试语音。'
                    await route.fulfill(content_type='audio/wav', body=wav_audio())
                elif path == 'voice/stt':
                    assert 'multipart/form-data; boundary=' in route.request.headers['content-type']
                    assert b'input.wav' in route.request.post_data_buffer
                    await route.fulfill(json={"status": "success", "stt": {"text": "这是识别结果"}})
                else:
                    await route.fallback()

            await page.route('**/api/**', api)
            await page.goto(os.environ['PROMETHEA_UI_TEST_URL'])
            await page.get_by_role('button', name='设置', exact=True).click()
            panel = page.get_by_role('region', name='语音交互', exact=True)
            await expect(panel.get_by_label('提供方', exact=True)).to_be_enabled()
            await panel.get_by_label('提供方', exact=True).select_option('openai')
            await panel.get_by_label('接口地址', exact=True).fill('http://localhost:9999/v1')
            await panel.get_by_label('模型', exact=True).fill('speech-model')
            await panel.get_by_role('button', name='读取模型列表', exact=True).click()
            await expect(panel.locator('datalist option')).to_have_count(1)
            await panel.get_by_label('试听文本', exact=True).fill('你好，测试语音。')
            await panel.get_by_role('button', name='合成试听', exact=True).click()
            await expect(panel.locator('audio')).to_be_visible()
            await expect(panel.get_by_role('link', name='下载音频', exact=True)).to_have_attribute('download', 'speech.wav')
            await panel.get_by_label('音频格式', exact=True).select_option('mp3')
            await expect(panel.get_by_role('link', name='下载音频', exact=True)).to_have_attribute('download', 'speech.wav')
            await panel.get_by_role('tab', name='语音识别', exact=True).click()
            await panel.get_by_label('提供方', exact=True).select_option('openai')
            await panel.get_by_label('接口地址', exact=True).fill('http://localhost:9999/v1')
            await panel.get_by_label('模型', exact=True).fill('transcriber')
            await panel.get_by_label('音频文件', exact=True).set_input_files({"name": "input.wav", "mimeType": "audio/wav", "buffer": wav_audio()})
            await expect(panel.locator('output')).to_have_text('这是识别结果')
            output = Path('.tmp/voice-qa'); output.mkdir(parents=True, exist_ok=True)
            await panel.scroll_into_view_if_needed()
            await page.screenshot(path=str(output / f'settings-{width}.png'))
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert state['stt']['configured'] and state['tts']['configured']
            assert not any(path == 'voice/ptt' for path, _ in calls)
            assert not errors
        finally:
            await browser.close()


@pytest.mark.parametrize('confirmation', [False, True])
async def test_recording_enters_normal_chat_and_releases_microphone(confirmation):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            _, _, errors = await prepare(page)
            await page.add_init_script("""
                window.stoppedTracks = 0;
                Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {value: async () => ({getTracks: () => [{stop: () => window.stoppedTracks++}]})});
                window.MediaRecorder = class {
                    static isTypeSupported(type) { return type === 'audio/mp4'; }
                    constructor(stream, options) { this.stream = stream; this.mimeType = options.mimeType; this.state = 'inactive'; }
                    start() { this.state = 'recording'; }
                    stop() {
                        this.state = 'inactive';
                        const finish = () => { this.ondataavailable?.({data: new Blob(['recording'], {type: this.mimeType})}); this.onstop?.(); };
                        if (window.delayStop) window.finishRecording = finish; else finish();
                    }
                };
            """)
            chat, tts, transcripts = [], [], []
            endpoint = {"provider": "openai", "base_url": "http://localhost:9999/v1", "model": "speech", "voice": "alloy", "format": "wav", "speed": 1, "configured": True, "api_key_configured": False}

            async def api(route):
                path = route.request.url.split('/api/', 1)[-1].split('?')[0]
                if path == 'voice/status':
                    await route.fulfill(json={"stt": endpoint, "tts": endpoint, "speak_replies": True})
                elif path == 'voice/stt':
                    transcripts.append(route.request.post_data_buffer)
                    assert b'voice.m4a' in transcripts[-1] and b'audio/mp4' in transcripts[-1]
                    await route.fulfill(json={"status": "success", "stt": {"text": "你好，来自录音"}})
                elif path == 'chat':
                    chat.append(route.request.post_data_json)
                    final = {"status": "needs_confirmation" if confirmation else "success", "session_id": "speech-chat", "content": "请确认操作" if confirmation else "正常流式回复", "tool_call_id": "confirm-1", "tool_name": "test.sensitive", "args": {}}
                    events = [('session_started', {"session_id": "speech-chat", "conversation_turn_id": "speech-turn"}), ('text', {"content": final['content']}), ('done', final)]
                    await route.fulfill(content_type='text/event-stream', body=''.join(f'event: {name}\ndata: {json.dumps(body)}\n\n' for name, body in events))
                elif path == 'chat/confirm':
                    assert route.request.post_data_json['action'] == 'reject'
                    await route.fulfill(json={"status": "success", "session_id": "speech-chat", "response": "正常流式回复"})
                elif path == 'voice/tts':
                    tts.append(route.request.post_data_json)
                    await route.fulfill(status=502, json={"detail": {"code": "VOICE_PROVIDER_UNAVAILABLE", "message": "VOICE_PROVIDER_UNAVAILABLE"}})
                elif path == 'sessions/speech-chat':
                    await route.fulfill(json={"session_info": {"title": "语音测试"}, "messages": [{"role": "user", "content": "你好，来自录音"}, {"role": "assistant", "content": "正常流式回复"}]})
                else:
                    assert path != 'voice/ptt'
                    await route.fallback()

            await page.route('**/api/**', api)
            await page.goto(os.environ['PROMETHEA_UI_TEST_URL'])
            await page.get_by_role('button', name='语音输入', exact=True).click()
            await page.evaluate('window.delayStop = true')
            await page.get_by_role('button', name='停止录音', exact=True).click()
            await expect(page.get_by_role('button', name='语音输入', exact=True)).to_be_disabled()
            await page.evaluate('window.delayStop = false; window.finishRecording()')
            if confirmation:
                await expect(page.get_by_role('heading', name='敏感操作确认', exact=True)).to_be_visible()
                assert tts == []
                await page.get_by_role('button', name='拒绝', exact=True).click()
            await expect(page.get_by_text('正常流式回复', exact=True)).to_be_visible()
            await expect(page.get_by_role('alert')).to_contain_text('无法连接语音接口')
            assert len(chat) == 1 and chat[0]['stream'] is True and chat[0]['message'] == '你好，来自录音'
            assert tts == [{"text": "正常流式回复"}]
            assert await page.evaluate('window.stoppedTracks') == 1
            await page.get_by_role('button', name='语音输入', exact=True).click()
            await expect(page.get_by_role('button', name='停止录音', exact=True)).to_be_visible()
            await page.get_by_role('button', name='设置', exact=True).click()
            await page.wait_for_function('window.stoppedTracks === 2')
            assert len(transcripts) == 1
            assert not errors
        finally:
            await browser.close()


async def test_disabling_spoken_replies_during_a_run_prevents_late_synthesis():
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel=os.environ["CANVAS_TEST_BROWSER_CHANNEL"], headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            _, _, errors = await prepare(page)
            await page.add_init_script("""
                const original = window.fetch.bind(window);
                window.fetch = async (input, init) => {
                    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                    if (url.pathname !== '/api/chat') return original(input, init);
                    const body = new ReadableStream({start(controller) { window.chatStream = controller; }});
                    window.emitChat = (event, payload) => window.chatStream.enqueue(new TextEncoder().encode(`event: ${event}\\ndata: ${JSON.stringify(payload)}\\n\\n`));
                    return new Response(body, {headers: {'Content-Type': 'text/event-stream'}});
                };
            """)
            state = {"stt": {"provider": "disabled", "model": "", "base_url": "", "configured": False, "api_key_configured": False}, "tts": {"provider": "openai", "model": "speaker", "base_url": "http://localhost:9999/v1", "configured": True, "api_key_configured": False}, "speak_replies": True}
            synthesis = []

            async def api(route):
                if '/voice/status' in route.request.url:
                    await route.fulfill(json=state)
                elif '/voice/tts' in route.request.url:
                    synthesis.append(route.request.post_data_json)
                    await route.fulfill(content_type='audio/wav', body=wav_audio())
                elif '/sessions/voice-control' in route.request.url:
                    await route.fulfill(json={"session_info": {}, "messages": [{"role": "assistant", "content": "保持文字回复"}]})
                else:
                    await route.fallback()

            await page.route('**/api/**', api)
            async with page.expect_response('**/api/voice/status'):
                await page.goto(os.environ['PROMETHEA_UI_TEST_URL'])
            await page.get_by_placeholder('输入消息').fill('你好')
            await page.get_by_role('button', name='发送', exact=True).click()
            await page.wait_for_function('Boolean(window.emitChat)')
            await page.evaluate("window.emitChat('session_started', {session_id:'voice-control',conversation_turn_id:'turn-1'})")
            state['speak_replies'] = False
            async with page.expect_response('**/api/voice/status'):
                await page.evaluate("window.dispatchEvent(new Event('voice-settings-changed'))")
            await page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            await page.evaluate("window.emitChat('done', {status:'success',session_id:'voice-control',content:'保持文字回复'}); window.chatStream.close()")
            await expect(page.get_by_text('保持文字回复', exact=True)).to_be_visible()
            await page.evaluate('new Promise(resolve => requestAnimationFrame(resolve))')
            assert synthesis == [] and not errors
        finally:
            await browser.close()
