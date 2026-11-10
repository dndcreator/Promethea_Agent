import assert from 'node:assert/strict'
import test from 'node:test'
import { presentActivity, processPages, processStatus, readableProcessText, splitLegacyThinking } from '../src/utils/process-presentation.ts'

test('process prose excludes protocol envelopes and fenced diagnostics, not ordinary reasoning', () => {
  assert.equal(readableProcessText('{"action":"tool_call","args":{}}', 'zh'), '')
  assert.equal(readableProcessText('{"action":', 'zh'), '')
  assert.equal(readableProcessText('先核对文件。\n\n```json\n{"error":"PRIVATE_CODE"}\n```\n\n再验证结果。', 'zh'), '先核对文件。\n\n再验证结果。')
  assert.equal(readableProcessText(JSON.stringify({ summary_i18n: { zh: '检查结果', en: 'Check result' }, summary: 'Fallback', secret: 'not prose' }), 'zh'), '检查结果')
  assert.equal(readableProcessText('[依据](https://example.org)需要核对。', 'zh'), '依据需要核对。')
})

test('chat and workbench share explicit localized activity text without exposing raw backend fallback', () => {
  const activity = { kind: 'tool', status: 'completed', subject: 'capability_request', summary: '{"state":"INTERNAL"}', subject_i18n: { zh: '写入文件', en: 'Write file' }, references: [{ kind: 'artifact', label: 'result.txt' }] }
  assert.equal(presentActivity(activity, 'zh').title, '写入文件')
  assert.equal(presentActivity(activity, 'en').title, 'Write file')
  assert.equal(presentActivity(activity, 'zh').summary, '')
  delete activity.subject_i18n
  assert.equal(presentActivity(activity, 'zh').title, '工具 · result.txt')
  assert.equal(presentActivity(activity, 'zh').statusLabel, '已完成')
  assert.equal(processStatus('waiting_confirmation', 'zh'), '等待处理')
  assert.equal(processStatus('observed', 'en'), 'Recorded')
  assert.equal(processStatus('cancelled', 'zh'), '已停止')
})

test('long reasoning is paged losslessly at Unicode boundaries rather than injected as a full dump', () => {
  const text = '核对🙂'.repeat(1000)
  const pages = processPages(text)
  assert.equal(pages.join(''), text)
  assert.ok(pages.every((page) => Array.from(page).length <= 600))
  assert.throws(() => processPages(text, 0), RangeError)
})

test('legacy thinking uses one process path and preserves all surrounding answer fragments', () => {
  assert.deepEqual(splitLegacyThinking('A<thinking>first</thinking>B<thinking>second</thinking>C'), { answer: 'ABC', thoughts: ['first', 'second'] })
  assert.deepEqual(splitLegacyThinking('回答<thinking>partial'), { answer: '回答', thoughts: ['partial'] })
  assert.deepEqual(splitLegacyThinking('ordinary answer'), { answer: 'ordinary answer', thoughts: [] })
})
