import assert from 'node:assert/strict'
import test from 'node:test'
import { PrometheaClient } from '../dist/index.js'

test('embedding control uses generated contracts and existing authenticated transport', async () => {
  const calls = []
  const signal = new AbortController().signal
  const client = new PrometheaClient({ baseUrl: 'http://localhost:8000', token: 'private', fetch: async (url, init) => {
    calls.push({ url, init })
    return Response.json({ provider: 'local', model: 'BAAI/bge-small-zh-v1.5', model_state: 'downloading', index_state: 'idle', supported: true })
  } })
  assert.equal((await client.memory.embeddingStatus(signal)).provider, 'local')
  await client.memory.controlEmbedding({ action: 'download' }, signal)
  assert.equal(calls[0].url, 'http://localhost:8000/api/memory/embedding')
  assert.equal(calls[1].init.signal, signal)
  assert.equal(new Headers(calls[1].init.headers).get('Authorization'), 'Bearer private')
  assert.deepEqual(JSON.parse(calls[1].init.body), { action: 'download' })
})
