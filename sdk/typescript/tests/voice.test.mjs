import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient, PrometheaError } from '../dist/index.js'

test('voice shares authenticated transport, JSON contracts and binary audio', async () => {
  const calls = []
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'speech-token', fetch: async (url, init) => {
    calls.push({ url, init })
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer speech-token')
    if (url.endsWith('/tts')) return new Response('audio', { headers: { 'Content-Type': 'audio/mpeg' } })
    return Response.json(url.endsWith('/models') ? { models: ['speaker'] } : { stt: { configured: false }, tts: { configured: false }, speak_replies: false })
  } })
  assert.equal((await client.voice.status()).speak_replies, false)
  assert.deepEqual((await client.voice.models({ kind: 'tts' })).models, ['speaker'])
  const audio = await client.voice.synthesize({ text: 'Hello' })
  assert.equal(audio.type, 'audio/mpeg')
  assert.equal(await audio.text(), 'audio')
  assert.deepEqual(JSON.parse(calls[1].init.body), { kind: 'tts' })
  assert.deepEqual(JSON.parse(calls[2].init.body), { text: 'Hello' })
})

test('transcription preserves multipart boundary, filename, MIME and abort signal', async () => {
  const controller = new AbortController()
  const client = new PrometheaClient({ baseUrl: '', fetch: async (url, init) => {
    assert.equal(url, '/api/voice/stt')
    assert.equal(init.signal, controller.signal)
    assert.equal(new Headers(init.headers).has('Content-Type'), false)
    assert.ok(init.body instanceof FormData)
    const audio = init.body.get('audio')
    assert.equal(audio.name, 'recording.m4a')
    assert.equal(audio.type, 'audio/mp4')
    assert.equal(await audio.text(), 'recording')
    return Response.json({ status: 'success', stt: { text: 'hello' } })
  } })
  assert.equal((await client.voice.transcribe(new Blob(['recording'], { type: 'audio/mp4' }), 'recording.m4a', controller.signal)).stt.text, 'hello')
})

test('speech maps structured provider errors without swallowing cancellation', async () => {
  const client = new PrometheaClient({ baseUrl: '', fetch: async () => Response.json({ detail: { code: 'VOICE_PROVIDER_AUTH_FAILED', message: 'VOICE_PROVIDER_AUTH_FAILED' } }, { status: 502 }) })
  await assert.rejects(client.voice.synthesize({ text: 'Hi' }), error => error instanceof PrometheaError && error.code === 'VOICE_PROVIDER_AUTH_FAILED' && error.status === 502)
  const controller = new AbortController()
  const cancellable = new PrometheaClient({ baseUrl: '', fetch: async (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true })
  }) })
  const pending = cancellable.voice.status(controller.signal)
  await new Promise(resolve => setTimeout(resolve, 0))
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
})
