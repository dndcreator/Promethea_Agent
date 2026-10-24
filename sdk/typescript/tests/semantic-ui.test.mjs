import test from 'node:test'
import assert from 'node:assert/strict'
import { PrometheaClient, PrometheaError } from '../dist/index.js'

test('semantic expressions use generated contracts and transport without tool dispatch', async () => {
  const calls = []
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'test-token', fetch: async (url, init) => {
    calls.push({ url, init })
    return new Response(JSON.stringify(url.endsWith('/context') ? { ok: true } : url.endsWith('/feedback') ? { expression_id: 'reading', revision: 2, state: 'responded', response: 'compare' } : { revision: 1, expressions: [] }), { headers: { 'Content-Type': 'application/json' } })
  } })
  assert.deepEqual(await client.semanticUI.get(), { revision: 1, expressions: [] })
  const controller = new AbortController()
  await client.semanticUI.observeSurface({ view: 'chat', session_id: 'article' }, controller.signal)
  const feedback = { expected_revision: 1, action: 'respond', choice_id: 'compare' }
  assert.equal((await client.semanticUI.feedback('reading', feedback)).state, 'responded')
  assert.equal(calls[0].url, 'http://localhost:8000/api/semantic-ui')
  assert.equal(calls[1].init.signal, controller.signal)
  assert.equal(new Headers(calls[1].init.headers).get('Authorization'), 'Bearer test-token')
  assert.equal(calls[2].url, 'http://localhost:8000/api/semantic-ui/reading/feedback')
  assert.deepEqual(JSON.parse(calls[2].init.body), feedback)
  assert.ok(calls.every(({ url }) => !url.includes('/tools') && !url.includes('/confirm')))
})

test('stale expression feedback is a normal structured conflict', async () => {
  const client = new PrometheaClient({ baseUrl: '', fetch: async () => new Response(JSON.stringify({ error_detail: { code: 'CONFLICT', message: 'Reload the expression' } }), { status: 409 }) })
  await assert.rejects(client.semanticUI.feedback('old', { expected_revision: 1, action: 'dismiss' }), (error) => error instanceof PrometheaError && error.status === 409)
})
