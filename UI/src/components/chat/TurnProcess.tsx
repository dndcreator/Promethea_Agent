import { useEffect, useState } from 'react'
import { BrainCircuit, ChevronDown, ChevronRight, CircleDot } from 'lucide-react'
import { getReasoningTree } from '../../services/api'
import type { WorkbenchActivity } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import type { ReasoningStep } from './types'

type ReasoningNodeView = {
  id: string
  title: string
  summary: string
  status: string
}

export default function TurnProcess({
  treeId,
  reasoningSteps,
  activities,
  running,
  onOpenWorkbench,
}: {
  treeId?: string
  reasoningSteps: ReasoningStep[]
  activities: WorkbenchActivity[]
  running: boolean
  onOpenWorkbench: () => void
}) {
  const { lang, t } = useLanguage()
  const [tree, setTree] = useState<any>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    let interval: number | undefined
    const refresh = async () => {
      if (!treeId) {
        if (!cancelled) setTree(null)
        return
      }
      try {
        const response = await getReasoningTree(treeId)
        if (response.ok && !cancelled) setTree(await response.json())
      } catch {
        // The final answer remains usable when process projection is unavailable.
      }
    }
    void refresh()
    if (running && treeId) interval = window.setInterval(refresh, 1500)
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [treeId, running])

  const nodes: ReasoningNodeView[] = Array.isArray(tree?.nodes)
    ? tree.nodes
        .filter((node: any) => {
          const kind = String(node?.kind || '').toLowerCase()
          const status = String(node?.status || '').toLowerCase()
          return kind !== 'root' && status !== 'pruned'
        })
        .sort((left: any, right: any) => Number(left.updated_at || 0) - Number(right.updated_at || 0))
        .map((node: any, index: number) => ({
          id: String(node?.node_id || index),
          title: reasoningNodeTitle(node, t),
          summary: readableProcessSummary(node?.summary || node?.observation),
          status: String(node?.status || '').toLowerCase(),
        }))
    : []
  const latest = nodes[nodes.length - 1]
  const live = running
  const visibleActivities = activities.filter((activity) => !(treeId && activity.kind === 'reasoning'))
  const activityCount = visibleActivities.reduce((total, activity) => total + Number(activity.occurrence_count || 1), 0)
  const counts = [
    reasoningSteps.length > 0 ? t(`${reasoningSteps.length} 段思考`, `${reasoningSteps.length} thoughts`) : '',
    nodes.length > 0 ? t(`${nodes.length} 个推理步骤`, `${nodes.length} reasoning steps`) : '',
    activityCount > 0 ? t(`${activityCount} 次操作`, `${activityCount} actions`) : '',
  ].filter(Boolean)
  const label = live
    ? t('正在思考', 'Thinking')
    : counts.length > 0
      ? counts.join(' · ')
      : t('已思考', 'Thought for a while')
  const latestLabel = visibleActivities.length > 0
    ? localizedProcessActivity(visibleActivities[visibleActivities.length - 1], lang)
    : latest?.title || compactProcessText(reasoningSteps[reasoningSteps.length - 1]?.content || '', 90)

  return (
    <div className="turn-process mb-2 mt-1 overflow-hidden border-l border-brand-200 pl-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-1 text-left text-[12px] text-text-muted transition-colors hover:text-text-strong"
      >
        <BrainCircuit size={13} className={live ? 'text-brand-600' : ''} />
        <span className="font-medium">{label}</span>
        {!open && latestLabel && <span className="min-w-0 flex-1 truncate">{latestLabel}</span>}
        <span className="ml-auto shrink-0">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto pb-2 pt-1 pr-2">
          {reasoningSteps.length === 0 && nodes.length === 0 && visibleActivities.length === 0 ? (
            <div className="flex items-center gap-2 py-1 text-[12px] text-text-muted">
              <CircleDot size={11} className={live ? 'animate-pulse text-brand-600' : ''} />
              <span>{label}</span>
            </div>
          ) : (
            <>
              {reasoningSteps.map((step, index) => (
                <div key={`${step.step_id}:${index}`} className="relative py-1.5 pl-5 text-[12px] leading-5">
                  <CircleDot size={10} className={`absolute left-0 top-3 ${live && index === reasoningSteps.length - 1 ? 'animate-pulse text-brand-600' : 'text-text-muted'}`} />
                  <ProcessText title={`${t('模型思考', 'Model reasoning')} ${index + 1}`} content={step.content} />
                </div>
              ))}
              {nodes.map((node, index) => {
              const active = live && (
                ['running', 'active', 'pending', 'waiting_tool', 'waiting_human'].includes(node.status)
                || index === nodes.length - 1
              )
              return (
                <div key={node.id} className="relative py-1.5 pl-5 text-[12px] leading-5">
                  <CircleDot size={10} className={`absolute left-0 top-3 ${active ? 'animate-pulse text-brand-600' : 'text-text-muted'}`} />
                  <ProcessText title={node.title} content={node.summary} />
                </div>
              )
              })}
              {visibleActivities.map((activity) => {
                const title = localizedProcessActivity(activity, lang)
                const count = Number(activity.occurrence_count || 1)
                return (
                  <button
                    key={activity.activity_id}
                    type="button"
                    onClick={onOpenWorkbench}
                    className="flex w-full items-center gap-2 py-1.5 pl-5 text-left text-[12px] leading-5 text-text-normal hover:text-brand-700"
                  >
                    <CircleDot size={10} className="shrink-0 text-text-muted" />
                    <span className="min-w-0 flex-1 truncate">{title}</span>
                    {count > 1 && <span className="shrink-0 font-mono text-[10px] text-text-muted">x{count}</span>}
                    <ChevronRight size={12} className="shrink-0 text-text-muted" />
                  </button>
                )
              })}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function ProcessText({ title, content }: { title: string; content: string }) {
  return (
    <details className="min-w-0 py-1 text-[12px] leading-5">
      <summary className="cursor-pointer text-text-normal">
        <span className="font-medium">{title}</span>
        {content && <span className="mt-1 line-clamp-2 break-words text-text-muted">{content.slice(0, 200)}</span>}
      </summary>
      {content && <div className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words border-l border-black/10 pl-2 text-text-muted">{content}</div>}
    </details>
  )
}

function readableProcessSummary(value: unknown): string {
  if (typeof value !== 'string') return ''
  try {
    const parsed = JSON.parse(value)
    return typeof parsed === 'string' ? parsed : String(parsed?.summary || parsed?.message || parsed?.text || '')
  } catch { return value }
}

export function normalizeReasoningSteps(value: unknown): ReasoningStep[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map((item, index) => ({
      step_id: String(item.step_id || `reasoning-${index}`),
      source: String(item.source || 'provider'),
      content: String(item.content || ''),
    }))
    .filter((item) => item.content.trim().length > 0)
}

function localizedProcessActivity(activity: WorkbenchActivity, lang: 'zh' | 'en'): string {
  return String(activity.subject_i18n?.[lang] || activity.subject || activity.summary_i18n?.[lang] || activity.summary || '')
}

function compactProcessText(value: string, maxLength: number): string {
  const text = value.replace(/\s+/g, ' ').trim()
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text
}

function reasoningNodeTitle(node: any, t: (zh: string, en: string) => string): string {
  const kind = String(node?.kind || '').toLowerCase()
  const metadata = node?.metadata && typeof node.metadata === 'object' ? node.metadata : {}
  if (kind === 'memory') {
    const query = compactProcessText(String(metadata.query || ''), 90)
    return query ? `${t('召回记忆', 'Recall memory')} · ${query}` : compactProcessText(String(node.title || t('召回记忆', 'Recall memory')), 120)
  }
  if (kind === 'tool') {
    const identity = [metadata.service_name, metadata.tool_name].filter(Boolean).join('.')
    return identity ? `${t('调用工具', 'Use tool')} · ${identity}` : compactProcessText(String(node.title || t('调用工具', 'Use tool')), 120)
  }
  if (kind === 'think') return t('分析当前步骤', 'Analyze current step')
  return compactProcessText(String(node?.title || t('分析', 'Reasoning')), 120)
}
