import assert from 'node:assert/strict'
import test from 'node:test'
import { streamChat } from '../src/services/api.ts'

test('stream terminal outcomes and selected UI language are preserved', async () => {
  const saved = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document, localStorage: globalThis.localStorage, sessionStorage: globalThis.sessionStorage }
  const storage = { getItem: () => null, removeItem: () => {} }
  globalThis.window = new EventTarget()
  globalThis.document = { documentElement: { lang: 'zh' } }
  globalThis.localStorage = storage
  globalThis.sessionStorage = storage
  try {
    for (const outcome of ['failure', 'interrupted', 'success']) {
      let request
      const events = []
      const errors = []
      globalThis.fetch = async (_url, init) => {
        request = JSON.parse(init.body)
        const body = outcome === 'failure'
          ? 'event: error\ndata: {"error_detail":{"code":"MODEL_OUTPUT_LIMIT","message":"Output limit"}}\n\n'
          : outcome === 'success'
            ? 'event: done\ndata: {"session_id":"s1"}\n\n'
            : 'event: reasoning\ndata: {"delta":"unfinished"}\n\n'
        return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
      }
      await streamChat('build', 's1', [], (event, data) => events.push([event, data]), (error) => errors.push(error))
      assert.equal(request.metadata.ui_language, 'zh')
      assert.equal(events.some(([name]) => name === 'done'), outcome === 'success')
      assert.equal(errors.length, outcome === 'success' ? 0 : 1)
      if (outcome === 'failure') assert.equal(errors[0].code, 'MODEL_OUTPUT_LIMIT')
    }
  } finally { Object.assign(globalThis, saved) }
})
