import assert from 'node:assert/strict'
import test from 'node:test'
import { taskStatusLabel } from '../src/utils/task-presentation.ts'

test('task and run labels use the existing Runtime states, including open and retry_wait', () => {
  const zh = (zh) => zh
  const en = (_, en) => en
  assert.equal(taskStatusLabel('open', '', zh), '待开始')
  assert.equal(taskStatusLabel('completed', '', en), 'Completed')
  assert.equal(taskStatusLabel('retry_wait', '', zh), '等待重试')
  assert.equal(taskStatusLabel('waiting_human', '', en), 'Waiting for review')
  assert.equal(taskStatusLabel('future_state', 'unknown', en), 'unknown')
})
