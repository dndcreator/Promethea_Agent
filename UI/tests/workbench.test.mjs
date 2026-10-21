import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeWorkbenchSnapshot } from '../src/utils/workbench.ts'

const snapshot = (scope, timeline) => ({ scope, timeline, cursor: 4 })
test('Workbench deltas retain previous cards and update the same activity', () => {
  const scope = { user_id: 'u', session_id: 's', run_id: 'r' }
  const previous = snapshot(scope, [{ activity_id: 'first', seq: 1, detail: { url: 'https://example.org' }, status: 'running' }, { activity_id: 'second', seq: 3 }])
  const merged = mergeWorkbenchSnapshot(previous, snapshot(scope, [{ activity_id: 'first', seq: 1, status: 'succeeded', detail: { result: 'ok' } }, { activity_id: 'middle', seq: 2 }]))
  assert.deepEqual(merged.timeline.map(row => row.activity_id), ['first', 'middle', 'second'])
  assert.deepEqual(merged.timeline[0].detail, { url: 'https://example.org', result: 'ok' })
  assert.equal(merged.timeline[0].status, 'succeeded')
})
test('Switching any execution scope discards unrelated history', () => {
  const scope = { user_id: 'u', session_id: 's', task_id: 't', run_id: 'r' }
  for (const key of Object.keys(scope)) {
    const incoming = snapshot({ ...scope, [key]: 'other' }, [])
    assert.equal(mergeWorkbenchSnapshot(snapshot(scope, [{ activity_id: 'private' }]), incoming), incoming)
  }
})
test('Reconnect history is bounded and ordered without duplicate cards', () => {
  const scope = { user_id: 'u', session_id: 's' }
  const rows = Array.from({ length: 200 }, (_, seq) => ({ activity_id: String(seq), seq }))
  const merged = mergeWorkbenchSnapshot(snapshot(scope, rows), snapshot(scope, rows.slice(100)))
  assert.equal(merged.timeline.length, 160)
  assert.equal(merged.timeline[0].seq, 40)
  assert.equal(new Set(merged.timeline.map(row => row.activity_id)).size, 160)
})
