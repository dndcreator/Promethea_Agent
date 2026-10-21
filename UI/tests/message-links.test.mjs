import assert from 'node:assert/strict'
import test from 'node:test'
import { messageLinks, messageTarget, annotationRanges } from '../src/utils/message-links.ts'

test('Markdown, autolinks, bare URLs and balanced parentheses have exact source labels', () => {
  const source = 'See [Paper](https://example.org/a_(b)?q=1&x=2), <https://example.org/doc> and https://example.org/raw.'
  const links = messageLinks(source)
  assert.deepEqual(links.map((link) => source.slice(link.labelStart, link.labelEnd)), [
    'Paper', 'https://example.org/doc', 'https://example.org/raw',
  ])
  assert.equal(links[0].url, 'https://example.org/a_(b)?q=1&x=2')
  assert.equal(source.slice(links[0].start, links[0].end), '[Paper](https://example.org/a_(b)?q=1&x=2)')
})

test('code, images and raw HTML are not executable links', () => {
  const source = '`https://example.org/code`\n\n```txt\nhttps://example.org/fence\n```\n\n![image](https://example.org/image)\n\n<a href="https://example.org/html">raw</a>'
  assert.equal(messageLinks(source).length, 0)
})

test('escaped brackets are not treated as a Markdown link label', () => {
  const source = '\\[escaped](https://example.org/escape)'
  const links = messageLinks(source)
  assert.equal(links.length, 1)
  assert.equal(source.slice(links[0].labelStart, links[0].labelEnd), 'https://example.org/escape')
})

test('reference links use their registered definition and preserve original offsets', () => {
  const source = '[Docs][guide]\n\n[guide]: https://example.org/docs "Documentation"'
  const [link] = messageLinks(source)
  assert.equal(link.url, 'https://example.org/docs')
  assert.equal(source.slice(link.labelStart, link.labelEnd), 'Docs')
})

test('partial streamed Markdown remains parseable at every prefix', () => {
  const source = 'Reference [paper](https://example.org/a_(b)) and more text.'
  for (let end = 0; end <= source.length; end++) {
    for (const link of messageLinks(source.slice(0, end))) {
      assert.ok(link.start >= 0 && link.end <= end)
      assert.ok(link.labelStart >= link.start && link.labelEnd <= link.end)
    }
  }
})

for (const value of ['javascript:alert(1)', 'data:text/html,bad', 'file:///C:/secret', 'blob:https://example.org/id', '//evil.example/a', 'https://user:pass@example.org', 'https://ex\nample.org', '/api/config', '/relative']) {
  test(`untrusted URL is not clickable: ${JSON.stringify(value)}`, () => {
    assert.equal(messageTarget(value, 'https://promethea.example'), null)
  })
}

test('web links retain query and fragment without authentication decoration', () => {
  assert.deepEqual(messageTarget('https://example.org/p?q=1#part'), { kind: 'url', url: 'https://example.org/p?q=1#part' })
  assert.equal(messageTarget('https://promethea.example/api/config', 'https://promethea.example'), null)
})

test('workspace URLs reuse the existing API shape and are not external navigations', () => {
  assert.deepEqual(messageTarget('/api/workbench/artifact?workspace_id=session-1&path=reports%2Ffinal.pdf', 'https://promethea.example'), {
    kind: 'artifact', workspaceId: 'session-1', path: 'reports/final.pdf',
  })
  assert.equal(messageTarget('/api/workbench/artifact?path=a', 'https://promethea.example'), null)
})

test('Unicode protocol offsets and legacy UTF-16 annotations both resolve correctly', () => {
  const source = '\u{1f600} before target after'
  const item = { id: '1', selected_text: 'target', query: 'why', response: 'answer' }
  assert.equal(annotationRanges(source, [{ ...item, start_offset: 9, end_offset: 15 }])[0].start, 10)
  assert.equal(annotationRanges(source, [{ ...item, start_offset: 10, end_offset: 16 }])[0].start, 10)
  assert.deepEqual(annotationRanges(source, [{ ...item, start_offset: 0, end_offset: 5 }]), [])
})
