import { fromMarkdown } from 'mdast-util-from-markdown'
import type { WorkbenchActivity } from '../services/api'

type Language = 'zh' | 'en'
type MarkdownNode = { type: string; value?: string; children?: MarkdownNode[] }

export function readableProcessText(value: unknown, lang: Language): string {
  if (typeof value !== 'string') return ''
  const text = value.trim()
  if (!text) return ''
  try {
    const parsed: unknown = JSON.parse(text)
    if (typeof parsed === 'string') return readableProcessText(parsed, lang)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const row = parsed as Record<string, unknown>
      const localized = row.summary_i18n as Record<string, unknown> | undefined
      return readableProcessText(localized?.[lang] || row.summary || row.reasoning_summary || row.explanation, lang)
    }
    return ''
  } catch {
    // Keep prose only; code, HTML and protocol bodies belong to diagnostics.
    const root = fromMarkdown(text) as MarkdownNode
    const prose = (node: MarkdownNode): string => {
      if (['code', 'html', 'image', 'imageReference'].includes(node.type)) return ''
      if (node.type === 'text' || node.type === 'inlineCode') return node.value || ''
      const separator = ['root', 'list', 'listItem', 'blockquote'].includes(node.type) ? '\n\n' : ''
      return (node.children || []).map(prose).filter(Boolean).join(separator)
    }
    if (text.startsWith('{') || text.startsWith('[{')) return ''
    return prose(root).trim()
  }
}

const activityLabels: Record<string, [string, string]> = {
  task: ['任务', 'Task'], workflow: ['工作流', 'Workflow'], tool: ['工具', 'Tool'],
  memory: ['记忆', 'Memory'], reasoning: ['分析', 'Analysis'],
  artifact: ['成果', 'Artifact'], environment: ['环境', 'Environment'],
}

export function processStatus(status: string, lang: Language): string {
  const index = lang === 'zh' ? 0 : 1
  if (['complete', 'completed', 'finished', 'success', 'succeeded'].includes(status)) return ['已完成', 'Completed'][index]
  if (['failed', 'error', 'interrupted'].includes(status)) return ['遇到障碍', 'Blocked'][index]
  if (['waiting', 'waiting_confirmation', 'waiting_input', 'needs_input', 'waiting_user', 'waiting_human', 'paused'].includes(status)) return ['等待处理', 'Waiting'][index]
  if (['cancelled', 'canceled', 'stopped', 'skipped'].includes(status)) return ['已停止', 'Stopped'][index]
  if (['observed', 'recorded'].includes(status)) return ['已记录', 'Recorded'][index]
  return ['进行中', 'In progress'][index]
}

export function presentActivity(activity: WorkbenchActivity, lang: Language) {
  const kind = (activity.kind || 'runtime').toLowerCase()
  const status = (activity.status || 'observed').toLowerCase()
  const kindLabel = (activityLabels[kind] || ['活动', 'Activity'])[lang === 'zh' ? 0 : 1]
  const statusLabel = processStatus(status, lang)
  const title = readableProcessText(activity.subject_i18n?.[lang], lang)
  const summary = readableProcessText(activity.summary_i18n?.[lang], lang)
  const subject = (activity.references || []).find((reference) => ['url', 'artifact', 'canvas', 'memory', 'cognition'].includes(reference.kind))?.label
  return { title: title || [kindLabel, subject].filter(Boolean).join(' · '), summary, kindLabel, statusLabel }
}

export function processPages(text: string, pageSize = 600): string[] {
  if (!Number.isInteger(pageSize) || pageSize < 1) throw new RangeError('Positive page size required')
  const characters = Array.from(text)
  const pages: string[] = []
  for (let offset = 0; offset < characters.length; offset += pageSize) pages.push(characters.slice(offset, offset + pageSize).join(''))
  return pages
}

export function splitLegacyThinking(content: string) {
  let cursor = 0
  let answer = ''
  const thoughts: string[] = []
  while (cursor < content.length) {
    const start = content.indexOf('<thinking>', cursor)
    if (start < 0) { answer += content.slice(cursor); break }
    answer += content.slice(cursor, start)
    const end = content.indexOf('</thinking>', start + 10)
    thoughts.push(content.slice(start + 10, end < 0 ? undefined : end))
    if (end < 0) break
    cursor = end + 11
  }
  return { answer, thoughts }
}
