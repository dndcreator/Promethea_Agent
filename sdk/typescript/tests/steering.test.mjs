import assert from 'node:assert/strict'
import test from 'node:test'
import { applyAnswerUpdate, PrometheaClient, PrometheaError } from '../dist/index.js'

test('stream answer updates replace discarded drafts and support legacy deltas', () => {
  let text = applyAnswerUpdate('', { content: 'draft' })
  text = applyAnswerUpdate(text, { operation: 'replace', content: '' })
  text = applyAnswerUpdate(text, { operation: 'delta', content: 'final' })
  assert.equal(text, 'final')
  assert.equal(applyAnswerUpdate(text, { operation: 'replace', content: 'canonical' }), 'canonical')
})

test('steer uses the owned chat endpoint, generated request and abortable transport', async () => {
  const controller = new AbortController()
  const request = { conversation_turn_id: 'turn-1', message_id: 'command-1', message: 'Use the new scope' }
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'token', fetch: async (url, init) => {
    assert.equal(url, 'http://localhost:8000/api/chat/session%2F1/steer')
    assert.equal(init.method, 'POST')
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer token')
    assert.equal(init.signal, controller.signal)
    assert.deepEqual(JSON.parse(init.body), request)
    return Response.json({ session_id: 'session/1', ...request, status: 'queued', action_loop_id: 'act-1' })
  } })
  assert.equal((await client.runs.steer('session/1', request, controller.signal)).status, 'queued')
})

test('steer preserves structured conflict and cancellation rather than retrying side effects', async () => {
  let calls = 0
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', fetch: async (_url, init) => {
    init.signal?.throwIfAborted()
    calls++
    return Response.json({ error_detail: { code: 'TURN_NOT_STEERABLE', message: 'Turn settled' } }, { status: 409 })
  } })
  await assert.rejects(client.runs.steer('s1', { conversation_turn_id: 't1', message_id: 'm1', message: 'new' }), error => error instanceof PrometheaError && error.code === 'TURN_NOT_STEERABLE')
  assert.equal(calls, 1)
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(client.runs.steer('s1', { conversation_turn_id: 't1', message_id: 'm1', message: 'new' }, controller.signal), error => error.name === 'AbortError')
  assert.equal(calls, 1)
})
