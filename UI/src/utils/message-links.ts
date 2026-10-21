import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmAutolinkLiteralFromMarkdown } from 'mdast-util-gfm-autolink-literal'
import { gfmAutolinkLiteral } from 'micromark-extension-gfm-autolink-literal'
import type { Nodes } from 'mdast'

export type MessageLink = {
  start: number
  end: number
  labelStart: number
  labelEnd: number
  url: string
}

export type MessageTarget =
  | { kind: 'url'; url: string }
  | { kind: 'artifact'; workspaceId: string; path: string }

export function messageTarget(value: string, origin?: string): MessageTarget | null {
  if (Array.from(value).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return null
  const absolute = /^https?:\/\//i.test(value)
  if (!absolute && (!origin || !value.startsWith('/') || value.startsWith('//'))) return null
  try {
    const url = new URL(value, origin)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    if (origin && url.origin === origin && url.pathname.startsWith('/api/')) {
      if (url.pathname !== '/api/workbench/artifact') return null
      const workspaceId = url.searchParams.get('workspace_id')
      const path = url.searchParams.get('path')
      return workspaceId && path ? { kind: 'artifact', workspaceId, path } : null
    }
    return absolute ? { kind: 'url', url: url.href } : null
  } catch {
    return null
  }
}

// Use parser offsets, not URL regexes: code, escapes and reference links retain
// their Markdown semantics while the rest of the message stays unchanged.
export function messageLinks(content: string): MessageLink[] {
  const root = fromMarkdown(content, {
    extensions: [gfmAutolinkLiteral()],
    mdastExtensions: [gfmAutolinkLiteralFromMarkdown()],
  })
  const definitions = new Map<string, string>()
  const collect = (node: Nodes) => {
    if (node.type === 'definition' && !definitions.has(node.identifier)) {
      definitions.set(node.identifier, node.url)
    }
    if ('children' in node) node.children.forEach(collect)
  }
  collect(root)
  const links: MessageLink[] = []
  const visit = (node: Nodes) => {
    if (['code', 'inlineCode', 'html', 'image', 'imageReference', 'definition'].includes(node.type)) return
    if (node.type === 'link' || node.type === 'linkReference') {
      const url = node.type === 'link' ? node.url : definitions.get(node.identifier)
      const start = node.position?.start.offset
      const end = node.position?.end.offset
      const labelStart = node.children[0]?.position?.start.offset
      const labelEnd = node.children[node.children.length - 1]?.position?.end.offset
      if (url && start !== undefined && end !== undefined && labelStart !== undefined && labelEnd !== undefined) {
        links.push({ start, end, labelStart, labelEnd, url })
      }
      return
    }
    if ('children' in node) node.children.forEach(visit)
  }
  visit(root)
  return links
}

export type TextAnnotation = {
  id: string
  start_offset: number
  end_offset: number
  selected_text: string
  query: string
  response: string
}

export function annotationRanges(content: string, annotations: TextAnnotation[]) {
  const offsets = [0]
  for (const char of content) offsets.push(offsets[offsets.length - 1] + char.length)
  return annotations.flatMap((item) => {
    if (!Number.isInteger(item.start_offset) || !Number.isInteger(item.end_offset)
      || item.start_offset < 0 || item.end_offset <= item.start_offset) return []
    let start = offsets[item.start_offset]
    let end = offsets[item.end_offset]
    if (start === undefined || end === undefined || content.slice(start, end) !== item.selected_text) {
      // Previously persisted UI annotations used UTF-16 offsets.
      start = item.start_offset
      end = item.end_offset
      if (end > content.length || content.slice(start, end) !== item.selected_text) return []
    }
    return [{ ...item, start, end }]
  }).sort((a, b) => a.start - b.start)
}

export function sourceSelection(root: HTMLElement, content: string, range: Range) {
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  const selected = range.toString()
  if (!selected.trim()) return null
  const before = range.cloneRange()
  before.selectNodeContents(root)
  before.setEnd(range.startContainer, range.startOffset)
  const leading = selected.length - selected.trimStart().length
  const visibleStart = before.toString().length + leading
  const visibleEnd = visibleStart + selected.trim().length
  const spans = Array.from(root.querySelectorAll<HTMLElement>('[data-source-start]'))
  const sourceOffset = (offset: number, end: boolean) => {
    let cursor = 0
    for (const span of spans) {
      const length = span.textContent?.length || 0
      if (offset < cursor + length || (end && offset === cursor + length)) {
        return Number(span.dataset.sourceStart) + offset - cursor
      }
      cursor += length
    }
    return content.length
  }
  const start = sourceOffset(visibleStart, false)
  const end = sourceOffset(visibleEnd, true)
  if (end <= start) return null
  return {
    selectedText: content.slice(start, end),
    startOffset: Array.from(content.slice(0, start)).length,
    endOffset: Array.from(content.slice(0, end)).length,
  }
}
