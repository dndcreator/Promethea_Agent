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
  await client.canvas.semantics(environment)
  await client.canvas.interact(environment, { component_id: 'count', operation: 'set', value: 3, expected_revision: 1, definition_revision: '0'.repeat(64) })
  assert.equal(state.value.count, 1)
  assert.equal(calls[0].url, 'http://localhost:8000/api/canvas/session%201/env1/state')
  assert.equal(calls[1].init.method, 'PUT')
  assert.deepEqual(JSON.parse(calls[1].init.body), { expected_revision: 0, value: { count: 1 } })
  assert.equal(new Headers(calls[1].init.headers).get('Authorization'), 'Bearer private')
  assert.equal(calls[2].init.method, 'POST')
  assert.equal(calls[3].init.method, 'DELETE')
  assert.equal(calls[4].url, 'http://localhost:8000/api/canvas/session%201/env1/semantics')
  assert.equal(calls[5].url, 'http://localhost:8000/api/canvas/session%201/env1/interact')
  assert.deepEqual(JSON.parse(calls[5].init.body), { component_id: 'count', operation: 'set', value: 3, expected_revision: 1, definition_revision: '0'.repeat(64) })
})

test('canvas state watch delivers newer Runtime state and stops on disconnect', async () => {
  let peer, tick
  let revision = 0
  let calls = 0
  const originalDocument = globalThis.document
  const originalInterval = globalThis.setInterval
  const originalClear = globalThis.clearInterval
  globalThis.document = { visibilityState: 'visible' }
  globalThis.setInterval = (callback) => { tick = callback; return 123 }
  let cleared = false
  globalThis.clearInterval = (id) => { assert.equal(id, 123); cleared = true }
  const client = { getState: async () => { calls++; return { revision, value: { count: revision } } } }
  const disconnect = connectCanvasFrame({ contentWindow: { postMessage: (_data, _origin, ports) => { peer = ports[0] } } }, client, environment)
  const receive = () => new Promise((resolve) => { peer.onmessage = ({data}) => resolve(data) })
  try {
    let response = receive()
    peer.postMessage({ id: 'watch', method: 'state.watch' })
    assert.equal((await response).result.revision, 0)
    revision = 2
    response = receive()
    tick()
    assert.deepEqual(await response, { event: 'state.changed', state: { revision: 2, value: { count: 2 } } })
    globalThis.document.visibilityState = 'hidden'
    const before = calls
    tick()
    assert.equal(calls, before)
    disconnect()
    assert.equal(cleared, true)
    tick()
    assert.equal(calls, before)
  } finally {
    disconnect()
    peer.close()
    globalThis.document = originalDocument
    globalThis.setInterval = originalInterval
    globalThis.clearInterval = originalClear
  }
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

test('Canvas expressions are definition-scoped and feedback cannot target another app', async () => {
  const originalDocument = globalThis.document
  let peer
  const frame = { contentWindow: { postMessage: (_data, _origin, ports) => { peer = ports[0] } } }
  globalThis.document = { visibilityState: 'visible', activeElement: frame }
  const attention = []
  const feedback = []
  let definition = 'a'.repeat(64)
  const anchor = { resource: { kind: 'canvas', id: environment.environment_id, workspace_id: environment.workspace_id }, component_id: 'count', definition_revision: definition }
  const item = { expression_id: 'tip', revision: 1, kind: 'choice', content: 'Check this value?', state: 'open', choices: [{ id: 'later', label: 'Later' }], canvas_anchor: anchor }
  const messages = []
  const waitFor = async (match) => {
    for (let i = 0; i < 100; i++) {
      const found = messages.find(match)
      if (found) return found
      await new Promise(resolve => setTimeout(resolve, 10))
    }
    assert.fail('bridge message timed out')
  }
  const disconnect = connectCanvasFrame(frame, { semantics: async () => ({ definition_revision: definition, components: [{ component_id: 'count' }] }) }, environment, {
    semanticUI: {
      get: async () => ({ expressions: [item, { ...item, expression_id: 'other', canvas_anchor: { ...anchor, resource: { ...anchor.resource, id: 'another-app' } } }] }),
      feedback: async (id, command) => { feedback.push({ id, command }); return { ...item, state: 'responded', response: command.choice_id, revision: 2 } },
    },
    onAttention: value => attention.push(value),
  })
  peer.onmessage = ({ data }) => messages.push(data)
  try {
    const presented = await waitFor(data => data.event === 'semantic.changed')
    assert.deepEqual(presented.expressions.map(row => row.expression_id), ['tip'])
    peer.postMessage({ id: 'focus', method: 'attention.report', params: { component_id: 'count' } })
    assert.deepEqual((await waitFor(data => data.id === 'focus')).result, { ok: true })
    assert.deepEqual(attention, [{ component_id: 'count', definition_revision: definition }])
    peer.postMessage({ id: 'forged', method: 'semantic.feedback', params: { expression_id: 'other', command: { expected_revision: 1, action: 'respond', choice_id: 'later' } } })
    assert.match((await waitFor(data => data.id === 'forged')).error, /does not belong/)
    assert.equal(feedback.length, 0)
    peer.postMessage({ id: 'valid', method: 'semantic.feedback', params: { expression_id: 'tip', command: { expected_revision: 1, action: 'respond', choice_id: 'later' } } })
    assert.equal((await waitFor(data => data.id === 'valid')).result.state, 'responded')
    assert.equal(feedback.length, 1)
    globalThis.document.activeElement = null
    peer.postMessage({ id: 'blurred', method: 'attention.report', params: { component_id: 'count' } })
    assert.match((await waitFor(data => data.id === 'blurred')).error, /not focused/)
    definition = 'b'.repeat(64)
    const changed = await waitFor(data => data.event === 'semantic.changed' && data.semantics.definition_revision === definition)
    assert.deepEqual(changed.expressions, [])
  } finally {
    disconnect();peer.close();globalThis.document = originalDocument
  }
})
