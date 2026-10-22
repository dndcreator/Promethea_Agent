import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { annotationRanges, messageLinks, messageTarget } from '../utils/message-links'
import type { TextAnnotation } from '../utils/message-links'
import { openWorkbenchArtifact } from '../services/artifacts'
import { useLanguage } from '../store/LanguageContext'

export default function MessageContent({ content, followups, onAnnotationClick }: { content: string; followups: TextAnnotation[]; onAnnotationClick?: (id: string) => void }) {
  const { t } = useLanguage()
  const [error, setError] = useState('')
  const links = useMemo(() => messageLinks(content), [content])
  const annotations = useMemo(() => annotationRanges(content, followups), [content, followups])
  const sourceText = (start: number, end: number) => {
    const children: ReactNode[] = []
    let cursor = start
    for (const item of annotations) {
      const left = Math.max(cursor, item.start)
      const right = Math.min(end, item.end)
      if (right <= left) continue
      if (left > cursor) children.push(content.slice(cursor, left))
      children.push(
        <span key={item.id} title={`${item.query}\n\n${item.response}`} role={onAnnotationClick ? 'button' : undefined} tabIndex={onAnnotationClick ? 0 : undefined} onClick={(event) => { if (onAnnotationClick) { event.preventDefault(); event.stopPropagation(); onAnnotationClick(item.id) } }} onKeyDown={(event) => { if (onAnnotationClick && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onAnnotationClick(item.id) } }} className="cursor-help rounded-sm bg-brand-100/80 underline decoration-brand-500 decoration-2 underline-offset-2">
          {content.slice(left, right)}
        </span>,
      )
      cursor = right
    }
    if (cursor < end) children.push(content.slice(cursor, end))
    return <span key={start} data-source-start={start}>{children}</span>
  }
  const parts: ReactNode[] = []
  let cursor = 0
  for (const link of links) {
    const target = messageTarget(link.url, window.location.origin)
    if (!target) continue
    if (link.start > cursor) parts.push(sourceText(cursor, link.start))
    parts.push(
      <a
        key={`link:${link.start}`}
        href={target.kind === 'url' ? target.url : link.url}
        target="_blank"
        rel="noopener noreferrer"
        title={target.kind === 'url' ? target.url : target.path}
        className="text-brand-700 underline decoration-brand-300 underline-offset-2 hover:decoration-brand-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500"
        onClick={target.kind === 'artifact' ? (event) => {
          event.preventDefault()
          setError('')
          void openWorkbenchArtifact(target.workspaceId, target.path).catch(() => {
            setError(t('文件打开失败，请重试。', 'Could not open file. Please retry.'))
          })
        } : undefined}
      >
        {sourceText(link.labelStart, link.labelEnd)}
      </a>,
    )
    cursor = link.end
  }
  if (cursor < content.length) parts.push(sourceText(cursor, content.length))
  return <>{parts.length ? parts : <span className="animate-pulse">...</span>}{error && <span role="alert" className="block text-[12px] text-red-600" contentEditable={false}>{error}</span>}</>
}
