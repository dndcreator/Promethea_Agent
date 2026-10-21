import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient, connectCanvasFrame } from '../dist/index.js'

const environment = { workspace_id: 'session 1', environment_id: 'env1', name: 'Counter', preview_url: '/preview/' }

test('canvas state and lifecycle requests use owner-scoped existing HTTP transport', async () => {
  const calls = []
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'private', fetch: async (url, init) => {
    calls.push({ url, init })
    return new Response(JSON.stringify({ revision: 1, value: { count: 1 } }), { status: 200 })
  } })
  await client.canvas.getState(environment)
  const state = await client.canvas.setState(environment, { expected_revision: 0, value: { count: 1 } })
  await client.canvas.retain(environment)
  await client.canvas.remove(environment)
  assert.equal(state.value.count, 1)
  assert.equal(calls[0].url, 'http://localhost:8000/api/canvas/session%201/env1/state')
  assert.equal(calls[1].init.method, 'PUT')
  assert.deepEqual(JSON.parse(calls[1].init.body), { expected_revision: 0, value: { count: 1 } })
  assert.equal(new Headers(calls[1].init.headers).get('Authorization'), 'Bearer private')
  assert.equal(calls[2].init.method, 'POST')
  assert.equal(calls[3].init.method, 'DELETE')
})

test('opaque canvas bridge exposes app state, not arbitrary Runtime execution', async () => {
  let peer
  const calls = []
  const client = {
    getState: async (target) => { calls.push(target); return { revision: 0, value: {} } },
    setState: async (_target, params) => ({ revision: 1, value: params.value }),
  }
  const frame = { contentWindow: { postMessage: (message, _origin, ports) => {
    assert.equal(message.type, 'promethea:connect')
    assert.equal(JSON.stringify(message).includes('token'), false)
    peer = ports[0]
  } } }
  const disconnect = connectCanvasFrame(frame, client, environment)
  const request = (method, params = {}) => new Promise((resolve) => {
    peer.onmessage = (event) => resolve(event.data)
    peer.postMessage({ id: '1', method, params })
  })
  try {
    assert.deepEqual((await request('state.get')).result, { revision: 0, value: {} })
    assert.equal(calls[0], environment)
    assert.equal((await request('state.set', { expected_revision: 0, value: { count: 1 } })).result.revision, 1)
    assert.match((await request('runtime.execute', { tool: 'command' })).error, /Unsupported/)
    assert.match((await request('state.set', { expected_revision: 0, value: [] })).error, /Invalid/)
  } finally {
    disconnect()
    peer.close()
  }
})
