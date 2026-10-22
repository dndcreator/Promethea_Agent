import assert from 'node:assert/strict'
import test from 'node:test'
import { guestTranscript } from '../src/utils/guest-chat.ts'

test('guest history contains complete text pairs only and retains the current user input', () => {
  const history = [
    { role: 'user', content: 'failed request' }, { role: 'status', content: 'error' },
    { role: 'user', content: 'old question' }, { role: 'agent', content: 'old reply' },
    { role: 'tool', content: 'not a chat role' },
    { role: 'user', content: 'recent question' }, { role: 'agent', content: 'recent reply' },
  ]
  const result = guestTranscript(history, 'new question', { max_messages: 3, max_input_chars: 100 })
  assert.deepEqual(result, [
    { role: 'user', content: 'recent question' }, { role: 'assistant', content: 'recent reply' },
    { role: 'user', content: 'new question' },
  ])
  assert.equal(history.length, 7)
  assert.deepEqual(guestTranscript(history, 'new', { max_messages: 21, max_input_chars: 3 }), [{ role: 'user', content: 'new' }])
})
