import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient } from '../dist/index.js'

test('ambient configuration, feedback and exact consent consume generated contracts over HTTP', async () => {
  const calls = []
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'test', fetch: async (url, init) => {
    calls.push({ url, init })
    return Response.json({ session_id: 'chat / 1', available: true, settings: { enabled: true }, status: 'idle' })
  } })
  const controller = new AbortController()
  await client.ambient.get('chat / 1', controller.signal)
  await client.ambient.configure('chat / 1', { enabled: true, direction: 'Observe progress' })
  await client.ambient.feedback('chat / 1', { annotation_id: 'note', decision: 'dismissed' })
  await client.ambient.confirm('chat / 1', { run_id: 'run', tool_call_id: 'call', action: 'approve' })
  assert.equal(calls[0].init.signal, controller.signal)
  assert.equal(calls[0].url, 'http://localhost:8000/api/ambient/chat%20%2F%201')
  assert.deepEqual(calls.slice(1).map(({ init }) => init.method), ['PUT', 'POST', 'POST'])
  assert.deepEqual(JSON.parse(calls[3].init.body), { run_id: 'run', tool_call_id: 'call', action: 'approve' })
  assert.equal(new Headers(calls[3].init.headers).get('Authorization'), 'Bearer test')
  await client.ambient.get()
  await client.ambient.configure(null, { enabled: false })
  assert.equal(calls[4].url, 'http://localhost:8000/api/ambient')
  assert.equal(calls[5].url, 'http://localhost:8000/api/ambient')
})
