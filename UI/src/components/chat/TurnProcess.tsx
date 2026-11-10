import { useEffect, useMemo, useState } from 'react'
import { BrainCircuit, ChevronDown, ChevronRight, CircleDot } from 'lucide-react'
import { getReasoningTree } from '../../services/api'
import type { WorkbenchActivity } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import { presentActivity, processPages, readableProcessText } from '../../utils/process-presentation'
import type { ReasoningStep } from './types'

type ReasoningNode = {
  node_id: string
  kind: string
  summary?: string
  status: string
  updated_at?: number
}

export default function TurnProcess({ treeId, reasoningSteps, activities, running, onOpenWorkbench }: {
  treeId?: string
  reasoningSteps: ReasoningStep[]
  activities: WorkbenchActivity[]
  running: boolean
  onOpenWorkbench: () => void
}) {
  const { lang, t } = useLanguage()
  const [nodes, setNodes] = useState<ReasoningNode[]>([])
  const [open, setOpen] = useState(false)
  const [thoughtsOpen, setThoughtsOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    setNodes([])
    if (!treeId || !open || !thoughtsOpen) return
    const refresh = async () => {
      try {
        const response = await getReasoningTree(treeId)
        const tree = response.ok ? await response.json() : null
        if (!cancelled) setNodes(Array.isArray(tree?.nodes) ? tree.nodes : [])
      } catch {
        // The final answer remains usable when the reasoning view is unavailable.
      } finally {
        if (!cancelled && running) timer = window.setTimeout(refresh, 1500)
      }
    }
    void refresh()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [treeId, running, open, thoughtsOpen])

  const thoughts = useMemo(() => !open || !thoughtsOpen ? [] : [
    ...reasoningSteps.map((step) => ({ id: step.step_id, source: step.source, content: readableProcessText(step.content, lang) })),
    ...nodes.filter((node) => ['think', 'thought'].includes(node.kind) && node.status !== 'pruned')
      .sort((a, b) => Number(a.updated_at || 0) - Number(b.updated_at || 0))
      .map((node) => ({ id: node.node_id, source: 'reasoning', content: readableProcessText(node.summary, lang) })),
  ].filter((step) => step.content), [reasoningSteps, nodes, lang, open, thoughtsOpen])
  const visibleActivities = activities.filter((activity) => activity.kind !== 'reasoning')
  const latest = visibleActivities[visibleActivities.length - 1]
  const latestView = latest ? presentActivity(latest, lang) : null
  const label = running ? t('正在处理', 'Working') : t('工作过程', 'Work process')
  const hasThoughts = reasoningSteps.length > 0 || Boolean(treeId)
  if (!running && !activities.length && !hasThoughts) return null

  return (
    <div className="turn-process mb-2 mt-1 min-w-0 border-l border-brand-200 pl-3">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full min-w-0 items-center gap-2 py-1 text-left text-xs text-text-muted hover:text-text-strong">
        <CircleDot size={13} className={`shrink-0 ${running ? 'animate-pulse text-brand-600' : ''}`} />
        <span className="shrink-0 font-medium">{label}</span>
        {!open && latestView && <span className="min-w-0 flex-1 truncate"><span>{latestView.title}</span><span> · {latestView.statusLabel}</span></span>}
        <span className="ml-auto shrink-0">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
      </button>
      {open && <div className="space-y-1 py-2">
        {visibleActivities.length > 0 && <div className="max-h-48 overflow-y-auto pr-1">
          {visibleActivities.map((activity) => {
            const view = presentActivity(activity, lang)
            return <button key={activity.activity_id} type="button" onClick={onOpenWorkbench}
              className="flex w-full items-start gap-2 py-1.5 text-left text-xs leading-5 text-text-normal hover:text-brand-700">
              <CircleDot size={10} className="mt-1.5 shrink-0 text-text-muted" />
              <span className="min-w-0 flex-1"><span className="flex flex-wrap items-baseline gap-x-2"><span className="break-words [overflow-wrap:anywhere]">{view.title}</span><span className="text-[10px] text-text-muted">{view.statusLabel}</span></span>
                {view.summary && <span className="line-clamp-2 break-words text-text-muted">{view.summary}</span>}
              </span>
              {Number(activity.occurrence_count || 1) > 1 && <span className="shrink-0 text-text-muted">x{activity.occurrence_count}</span>}
              <ChevronRight size={12} className="mt-1 shrink-0" />
            </button>
          })}
        </div>}
        {hasThoughts && <div className="border-t border-black/5 pt-1">
          <button type="button" aria-expanded={thoughtsOpen} onClick={() => setThoughtsOpen(!thoughtsOpen)}
            className="flex w-full items-center gap-2 py-1 text-left text-xs text-text-muted hover:text-text-strong">
            <BrainCircuit size={13} /><span>{t('推理过程', 'Reasoning')}</span>
            <span className="ml-auto">{thoughtsOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
          </button>
          {thoughtsOpen && <div className="max-h-64 overflow-y-auto pr-1">
            {thoughts.map((step, index) => <ProcessText key={`${step.source}:${step.id}`} title={`${step.source === 'provider' ? t('模型推理', 'Model reasoning') : t('推理步骤', 'Reasoning step')} ${index + 1}`} content={step.content} />)}
            {!thoughts.length && <p className="py-1 text-xs text-text-muted">{running ? t('正在分析', 'Analyzing') : t('暂无可展示的推理内容', 'No reasoning available')}</p>}
          </div>}
        </div>}
      </div>}
    </div>
  )
}

export function ProcessText({ title, content }: { title: string; content: string }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(0)
  const pages = useMemo(() => processPages(content), [content])
  const current = Math.min(page, Math.max(0, pages.length - 1))
  return <div className="min-w-0 py-1 text-xs leading-5">
    <button type="button" aria-expanded={open} onClick={() => { setOpen(!open); setPage(0) }}
      className="flex w-full items-center gap-2 py-1 text-left text-text-normal">
      {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}<span>{title}</span>
    </button>
    {open && <div className="border-l border-black/10 pl-3 text-text-muted">
      <div className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{pages[current]}</div>
      {pages.length > 1 && <div className="mt-2 flex items-center justify-between gap-2">
        <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} className="text-brand-700 disabled:text-text-muted disabled:opacity-40">{t('上一段', 'Previous')}</button>
        <span className="font-mono text-[10px]">{current + 1} / {pages.length}</span>
        <button type="button" disabled={current === pages.length - 1} onClick={() => setPage(current + 1)} className="text-brand-700 disabled:text-text-muted disabled:opacity-40">{t('下一段', 'Next')}</button>
      </div>}
    </div>}
  </div>
}

export function normalizeReasoningSteps(value: unknown): ReasoningStep[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map((item, index) => ({ step_id: String(item.step_id || `reasoning-${index}`), source: String(item.source || 'provider'), content: String(item.content || '') }))
    .filter((item) => item.content.trim())
}
