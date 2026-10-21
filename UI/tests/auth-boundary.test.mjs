import assert from 'node:assert/strict'
import test from 'node:test'
import { authFetch, getAuthToken, setAuthToken, streamChat, watchWorkbenchSnapshots, getCognitionBundle } from '../src/services/api.ts'

test('old unauthorized requests cannot expire a newer sign-in', async () => {
  const saved = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage }
  const storage = () => {
    const values = new Map()
    return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  }
  globalThis.window = new EventTarget()
  globalThis.document = { documentElement: { lang: 'zh' } }
  globalThis.localStorage = storage()
  globalThis.sessionStorage = storage()
  let expired = 0
  window.addEventListener('auth-expired', () => { expired += 1 })
  try {
    const operations = [
      () => authFetch('/api/user/profile'),
      () => getCognitionBundle().catch(() => {}),
      async () => { try { for await (const _ of watchWorkbenchSnapshots('session')) { /* no snapshots on rejection */ } } catch { /* expected rejection */ } },
      () => streamChat('hello', 'session', [], () => {}, () => {}),
    ]
    for (const operation of operations) {
      setAuthToken('old-token')
      let finish
      let began
      const started = new Promise(resolve => { began = resolve })
      globalThis.fetch = (_url, init) => {
        assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer old-token')
        began()
        return new Promise(resolve => { finish = resolve })
      }
      const pending = operation()
      await started
      setAuthToken('new-token')
      finish(new Response('{"error":"unauthorized"}', { status: 401, headers: { 'Content-Type': 'application/json' } }))
      await pending
      assert.equal(getAuthToken(), 'new-token')
      assert.equal(expired, 0)
    }
    globalThis.fetch = async () => new Response('{}', { status: 401 })
    await authFetch('/api/user/profile')
    assert.equal(getAuthToken(), '')
    assert.equal(expired, 1)
  } finally { Object.assign(globalThis, saved) }
})
