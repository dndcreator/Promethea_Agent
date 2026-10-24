import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient } from '../dist/index.js'

test('channel accounts use generated contracts and the authenticated transport', async () => {
  const calls = []
  const controller = new AbortController()
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'private', fetch: async (url, init) => {
    calls.push({ url, init })
    return Response.json(url.endsWith('/pairings') ? { channel: 'qq', command: '/bind opaque', expires_at: 100 } : [])
  } })
  await client.channels.list(controller.signal)
  assert.equal((await client.channels.pair({ channel: 'qq' })).command, '/bind opaque')
  await client.channels.deliveries()
  await client.channels.retry('receipt 1')
  await client.channels.unbind('qq')
  assert.equal(calls[0].url, 'http://localhost:8000/api/channels')
  assert.equal(calls[0].init.signal, controller.signal)
  assert.equal(new Headers(calls[0].init.headers).get('Authorization'), 'Bearer private')
  assert.deepEqual(JSON.parse(calls[1].init.body), { channel: 'qq' })
  assert.equal(calls[2].url, 'http://localhost:8000/api/channels/deliveries')
  assert.equal(calls[3].url, 'http://localhost:8000/api/channels/deliveries/receipt%201/retry')
  assert.equal(calls[4].init.method, 'DELETE')
})
