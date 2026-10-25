import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Brain,
  Database,
  ExternalLink,
  FileText,
  Info,
  MonitorPlay,
  Pause,
  Play,
  Square,
  PanelRightClose,
} from 'lucide-react'
import {
  getActiveReasoning,
  getTask,
  cancelTask,
  getReasoningTree,
  pauseTask,
  resumeTask,
  steerReasoningTree,
  stopReasoningTree,
  readApiResponse,
} from '../services/api'
import type { Task, WorkbenchActivity, WorkbenchReference, WorkbenchSnapshot as RuntimeWorkbenchSnapshot } from '../services/api'
import { useWorkbench } from '../store/WorkbenchContext'
import { useLanguage } from '../store/LanguageContext'
import { openWorkbenchArtifact } from '../services/artifacts'
import { taskStatusLabel } from '../utils/task-presentation'
import AmbientPanel from './AmbientPanel'
import { useEnvironmentObservation } from '../hooks/useEnvironmentObservation'

interface RightSidebarProps {
  sessionId: string | null
  treeId: string | null
  chatRunning?: boolean
  onOpenCanvas?: (workspaceId?: string, environmentId?: string) => void
  onOpenMemoryReview?: (proposalId?: string) => void
  onOpenMemory?: (tab: 'cognition' | 'entries', query?: string) => void
  taskId?: string | null
  runId?: string | null
  view?: 'work' | 'activity'
  onViewChange?: (view: 'work' | 'activity') => void
  onClose?: () => void
  onOpenArtifact?: (reference: WorkbenchReference, workspaceId: string) => void
  onOpenWorkflows?: () => void
  onObserveTask?: (task: Task) => void
  content?: ReactNode
}

type WorkbenchView = {
  scope: Record<string, unknown>
  metrics: any | null
  memoryProposals: any[]
  recallRuns: any[]
  workflowRuns: any[]
  recoveryItems: any[]
  task: Task | null
  run: NonNullable<Task['runs']>[number] | null
  timeline: WorkbenchActivity[]
  waitingActions: any[]
  activeRuntimeRuns: string[]
}

const EMPTY_WORKBENCH: WorkbenchView = {
  scope: {},
  metrics: null,
  memoryProposals: [],
  recallRuns: [],
  workflowRuns: [],
  recoveryItems: [],
  task: null,
  run: null,
  timeline: [],
  waitingActions: [],
  activeRuntimeRuns: [],
}

export default function RightSidebar({ sessionId, treeId, chatRunning = false, onOpenCanvas, onOpenMemoryReview, onOpenMemory, taskId, runId, view = 'activity', onViewChange, onClose, onOpenArtifact, onOpenWorkflows, onObserveTask, content }: RightSidebarProps) {
  const observe = useEnvironmentObservation('workbench', taskId ? [{ kind: 'task', id: taskId }] : [])
  const { lang, t } = useLanguage()
  const { snapshot, error: streamError, retry: retryStream } = useWorkbench()
  const [tree, setTree] = useState<any>(null)
  const [steerNote, setSteerNote] = useState('')
  const [workbench, setWorkbench] = useState<WorkbenchView>(EMPTY_WORKBENCH)
  const [taskControlPending, setTaskControlPending] = useState(false)
  const [referenceError, setReferenceError] = useState('')
  const scopeEpoch = useRef(0)

  useEffect(() => {
    setWorkbench(EMPTY_WORKBENCH)
    setReferenceError('')
    setTree(null)
    setSteerNote('')
    setTaskControlPending(false)
    return () => { scopeEpoch.current += 1 }
  }, [sessionId, taskId, runId])

  useEffect(() => {
    let cancelled = false
    let interval: number | undefined

    const fetchTree = async () => {
      try {
        let activeTreeId = treeId

        if (!activeTreeId && sessionId) {
          const activeRes = await getActiveReasoning(sessionId)
          if (activeRes.ok) {
            const data = await activeRes.json()
            const items = Array.isArray(data.items) ? data.items : []
            activeTreeId = items[0]?.tree_id || null
          }
        }

        if (activeTreeId) {
          const res = await getReasoningTree(activeTreeId)
          if (res.ok) {
            const data = await res.json()
            if (!cancelled) setTree(data)
          }
        } else if (!cancelled) {
          setTree(null)
        }
      } catch (error) {
        if (!cancelled) console.error(error)
      }
    }

    fetchTree()
    if (chatRunning || treeId) {
      interval = window.setInterval(fetchTree, chatRunning ? 2000 : 10000)
    }
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [sessionId, treeId, chatRunning])

  useEffect(() => {
    if (!snapshot || (!sessionId && !taskId)) {
      setWorkbench(EMPTY_WORKBENCH)
      return
    }
    const projection = workbenchView(snapshot)
    setWorkbench(runId ? { ...projection, memoryProposals: [], recoveryItems: [] } : projection)
  }, [sessionId, taskId, runId, snapshot])

  const currentTreeId = tree?.tree_id || tree?.id
  const nodes = normalizeActivities(workbench.timeline, lang, t)
  const taskStatus = String(runId ? workbench.run?.status || '' : workbench.task?.status || '').toLowerCase()
  const isActive = ['running', 'active', 'pending', 'waiting_user'].includes(taskStatus || String(tree?.status || '').toLowerCase())
  const summary = useMemo(
    () => summarizeWorkbench(tree, nodes, workbench, isActive, chatRunning, t, Boolean(runId)),
    [tree, nodes, workbench, isActive, chatRunning, t, runId],
  )
  const showControls = Boolean(
    !runId && (
    (tree && summary.live && !workbench.task)
    || (workbench.task && ['running', 'paused', 'waiting_user'].includes(taskStatus))),
  )

  const handleStop = async () => {
    const epoch = scopeEpoch.current
    setTaskControlPending(true)
    try {
      if (workbench.task?.task_id) {
        const task = await cancelTask(
          String(workbench.task.task_id),
          'user_cancelled',
          workbench.task.revision,
        )
        if (epoch === scopeEpoch.current) setWorkbench((prev) => ({ ...prev, task }))
      } else if (currentTreeId) {
        await stopReasoningTree(currentTreeId, 'User stopped via UI').then(readApiResponse)
        if (epoch === scopeEpoch.current) setTree((prev: any) => ({ ...prev, status: 'stopped' }))
      }
    } catch {
      if (epoch !== scopeEpoch.current) return
      setReferenceError(t('操作未完成，请刷新状态后重试。', 'Could not complete the action. Refresh the state and retry.'))
      retryStream()
    } finally {
      if (epoch === scopeEpoch.current) setTaskControlPending(false)
    }
  }

  const handlePauseResume = async () => {
    const epoch = scopeEpoch.current
    const taskId = String(workbench.task?.task_id || '')
    if (!taskId) return
    setTaskControlPending(true)
    try {
      const task = taskStatus === 'paused'
        ? await resumeTask(taskId, workbench.task?.revision)
        : await pauseTask(taskId, workbench.task?.revision)
      if (epoch === scopeEpoch.current) setWorkbench((prev) => ({ ...prev, task }))
    } catch {
      if (epoch !== scopeEpoch.current) return
      setReferenceError(t('操作未完成，请刷新状态后重试。', 'Could not complete the action. Refresh the state and retry.'))
      retryStream()
    } finally {
      if (epoch === scopeEpoch.current) setTaskControlPending(false)
    }
  }

  const handleSteer = async () => {
    if (currentTreeId && steerNote.trim()) {
      const epoch = scopeEpoch.current
      setTaskControlPending(true)
      try {
        await steerReasoningTree(currentTreeId, steerNote.trim()).then(readApiResponse)
        if (epoch === scopeEpoch.current) setSteerNote('')
      } catch (cause) { if (epoch === scopeEpoch.current) setReferenceError(String(cause)) }
      finally { if (epoch === scopeEpoch.current) setTaskControlPending(false) }
    }
  }

  const handleReference = async (reference: WorkbenchReference) => {
    if (reference.kind === 'task') {
      const epoch = scopeEpoch.current
      setReferenceError('')
      try {
        const task = await getTask(reference.target)
        if (epoch === scopeEpoch.current) onObserveTask?.(task)
      } catch {
        if (epoch === scopeEpoch.current) setReferenceError(t('任务打开失败，请重试。', 'Could not open task. Please retry.'))
      }
      return
    }
    if (reference.kind === 'url') {
      try {
        const url = new URL(reference.target)
        if (!['http:', 'https:'].includes(url.protocol)) return
        window.open(url.toString(), '_blank', 'noopener,noreferrer')
      } catch {
        return
      }
      return
    }
    if (reference.kind === 'canvas') {
      const workspaceId = String(reference.metadata?.workspace_id || workbench.scope.session_id || sessionId || 'default')
      onOpenCanvas?.(workspaceId, reference.target)
      return
    }
    if (reference.kind === 'memory_review') {
      onOpenMemoryReview?.(reference.target)
      return
    }
    if (reference.kind === 'memory' || reference.kind === 'cognition') {
      onOpenMemory?.(reference.kind === 'cognition' ? 'cognition' : 'entries', reference.target)
      return
    }
    if (reference.kind === 'artifact') {
      const workspaceId = String(reference.metadata?.workspace_id || workbench.scope.session_id || sessionId || 'default')
      if (onOpenArtifact) { onOpenArtifact(reference, workspaceId); return }
      setReferenceError('')
      try {
        await openWorkbenchArtifact(workspaceId, reference.target, reference.label)
      } catch {
        setReferenceError(t('文件打开失败，请重试。', 'Could not open file. Please retry.'))
      }
    }
  }

  const references = [...new Map(workbench.timeline.flatMap((activity) => activity.references || []).map((reference) => [`${reference.kind}:${reference.metadata?.workspace_id || ''}:${reference.target}`, reference])).values()]
  const outputs = references.filter((reference) => ['canvas', 'artifact'].includes(reference.kind))
  const sources = references.filter((reference) => ['url', 'memory', 'cognition'].includes(reference.kind))
  const referenceButton = (reference: WorkbenchReference) => <button key={`${reference.kind}:${reference.target}`} type="button" className="workbench-reference" onClick={() => void handleReference(reference)}>{reference.kind === 'canvas' ? <MonitorPlay size={16} /> : reference.kind === 'url' ? <ExternalLink size={15} /> : reference.kind === 'memory' || reference.kind === 'cognition' ? <Brain size={15} /> : <FileText size={16} />}<span>{reference.label || reference.target}</span><ChevronRight size={13} /></button>

  return (
    <aside ref={observe} className="runtime-workbench relative flex h-full w-full shrink-0 flex-col overflow-hidden">
      {streamError && <div role="alert" className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800"><span>{t('工作台连接中断', 'Workbench disconnected')}</span><button type="button" onClick={retryStream} className="ml-auto underline">{t('重试', 'Retry')}</button></div>}
      {referenceError && <p role="alert" className="px-4 py-2 text-xs text-red-600">{referenceError}</p>}
      <div className="workbench-heading z-10 flex shrink-0 items-center justify-between border-b border-black/5 px-4">
        <h2 className="flex items-baseline gap-2 font-display text-[17px] font-semibold text-text-strong">
          {t('任务工作台', 'Workbench')}
        </h2>
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-text-muted">
          <span className={`h-1.5 w-1.5 rounded-full bg-brand-600 ${summary.live ? 'animate-pulse' : ''}`} />
          {summary.statusLabel}
          {onClose && <button type="button" className="icon-button" title={t('收起工作台', 'Close workbench')} aria-label={t('收起工作台', 'Close workbench')} onClick={onClose}><PanelRightClose size={16} /></button>}
        </div>
      </div>

      {onViewChange && <div className="workbench-tabs" role="tablist" aria-label={t('工作台视图', 'Workbench views')}><button type="button" role="tab" aria-selected={view === 'work'} onClick={() => onViewChange('work')}>{t('工作', 'Work')}</button><button type="button" role="tab" aria-selected={view === 'activity'} onClick={() => onViewChange('activity')}>{t('活动', 'Activity')}<span>{nodes.length}</span></button></div>}

      <div className="z-10 border-b border-black/5 bg-bg-card/50 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-text-strong">{summary.title}</h3>
            {summary.currentStep && <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{summary.currentStep}</p>}
          </div>
        </div>
        <div className="mt-2 flex items-center gap-2 text-[10px] text-text-muted">
          <span>{summary.phaseLabel}</span>
          {workbench.memoryProposals.length > 0 && (
            <>
              <span>·</span>
              <button
                type="button"
                onClick={() => onOpenMemoryReview?.()}
                className="font-medium text-amber-700 underline decoration-amber-300 underline-offset-2 hover:text-amber-800"
              >
                {workbench.memoryProposals.length} {t('项记忆待确认', 'memory reviews')}
              </button>
            </>
          )}
          {workbench.recoveryItems.length > 0 && <button type="button" className="text-amber-700 underline" onClick={onOpenWorkflows}>{workbench.recoveryItems.length} {t('项待恢复', 'recoverable runs')}</button>}
        </div>
      </div>

      {(view === 'work' || content) && <div hidden={view !== 'work'} className={`workbench-content ${content ? 'has-preview' : ''}`}>
        {!runId && <AmbientPanel sessionId={sessionId} snapshot={snapshot?.ambient} onObserve={(id) => void handleReference({ reference_id: `task:${id}`, kind: 'task', target: id, label: t('主动行动', 'Ambient actions') })} />}
        {content || <>
          {workbench.task?.objective && <section className="workbench-section"><h3>{t('目标', 'Objective')}</h3><p>{workbench.task.objective}</p></section>}
          {workbench.memoryProposals.length > 0 && <section className="workbench-section"><h3>{t('需要确认', 'Needs review')}</h3><button type="button" className="workbench-reference" onClick={() => onOpenMemoryReview?.()}><Database size={15} /><span>{t('记忆更新', 'Memory updates')}</span><span>{workbench.memoryProposals.length}</span><ChevronRight size={13} /></button></section>}
          {outputs.length > 0 && <section className="workbench-section"><h3>{t('产物与画布', 'Artifacts & canvases')}</h3>{outputs.map(referenceButton)}</section>}
          {sources.length > 0 && <section className="workbench-section"><h3>{t('本次参考', 'References')}</h3>{sources.map(referenceButton)}</section>}
          {!workbench.task && outputs.length === 0 && sources.length === 0 && workbench.memoryProposals.length === 0 && <div className="workbench-empty"><Info size={20} /><span>{chatRunning ? t('正在处理', 'Working') : t('暂无进行中的工作', 'No active work')}</span></div>}
        </>}
      </div>}
      {view === 'activity' && <div className="relative z-10 flex-1 overflow-y-auto px-4 py-3 workbench-timeline">
        <div className="flex min-h-full flex-col">
          {!tree && nodes.length === 0 && (
            <div className="m-auto py-8 text-center">
              <Info size={22} className="mx-auto mb-2 text-text-muted" />
              <p className="text-sm font-medium text-text-normal">
                {chatRunning ? t('等待运行态', 'Waiting for state') : t('空闲', 'Idle')}
              </p>
            </div>
          )}

          {nodes.length > 0 && (
            <div className="relative flex-1">
                <div className="absolute bottom-3 left-[9px] top-3 w-px bg-black/10" />
                <div className="flex flex-col">
                  {nodes.map((node, index) => (
                  <TraceItem
                    id={node.id}
                    key={node.id}
                    time={node.time}
                    title={node.title}
                    desc={node.desc}
                    kind={node.kindLabel}
                    detail={node.detail}
                    statusLabel={node.nodeStatus}
                    occurrenceCount={node.occurrenceCount}
                    diagnostic={node.diagnostic}
                    icon={
                      node.nodeStatus === 'succeeded'
                        ? <CheckCircle2 size={12} />
                        : ['failed', 'error'].includes(node.nodeStatus)
                          ? <AlertCircle size={12} />
                          : <CircleDot size={12} className={index === nodes.length - 1 && summary.live ? 'animate-pulse' : ''} />
                    }
                    status={node.nodeStatus === 'running' || (index === nodes.length - 1 && summary.live) ? 'active' : 'done'}
                    references={node.references}
                    onOpenReference={handleReference}
                  />
                  ))}
                </div>
            </div>
          )}

          {(tree || workbench.task) && nodes.length === 0 && (
            <TraceItem
              id="initializing"
              time={new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              title={t('初始化', 'Initializing')}
              desc=""
              icon={<div className="h-2 w-2 animate-pulse rounded-full bg-brand-600" />}
              status="active"
            />
          )}
        </div>
      </div>}

      {showControls && (
        <div className="z-10 shrink-0 border-t border-black/5 bg-bg-card/80 p-3">
        {tree && summary.live && !workbench.task && (
          <div className="mb-3 flex flex-col gap-2">
            <div className="flex gap-2">
              <input
                type="text"
                value={steerNote}
                onChange={(e) => setSteerNote(e.target.value)}
                placeholder={t('给当前任务一个方向...', 'Steer the current task...')}
                className="min-w-0 flex-1 rounded-md border border-black/10 bg-bg-card px-3 py-2 text-xs outline-none focus:ring-1 focus:ring-brand-500"
              />
              <button
                type="button"
                onClick={handleSteer}
                disabled={taskControlPending || !steerNote.trim()}
                className="rounded-md bg-brand-100 px-3 py-2 text-xs font-semibold text-brand-700 hover:bg-brand-200 disabled:opacity-50"
              >
                {t('引导', 'Steer')}
              </button>
            </div>
          </div>
        )}

        <div className="flex gap-2">
        {workbench.task && ['running', 'paused'].includes(taskStatus) && (
          <button
            type="button"
            onClick={handlePauseResume}
            disabled={taskControlPending}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-black/10 bg-bg-card px-3 py-2 text-xs font-medium text-text-normal transition-colors hover:bg-black/[0.03] disabled:opacity-50"
          >
            {taskStatus === 'paused' ? <Play size={14} /> : <Pause size={14} />}
            {taskStatus === 'paused' ? t('继续', 'Resume') : t('暂停', 'Pause')}
          </button>
        )}

        <button
          type="button"
          onClick={handleStop}
          disabled={taskControlPending || (!workbench.task && (!tree || !summary.live)) || ['completed', 'failed', 'cancelled'].includes(taskStatus)}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-red-100 bg-red-50 px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-100 disabled:opacity-50"
        >
          <Square size={14} />
          {t('停止任务', 'Stop task')}
        </button>
        </div>
      </div>
      )}
    </aside>
  )
}

type NormalizedTraceNode = {
  id: string
  title: string
  desc: string
  time: string
  nodeStatus: string
  kind: string
  kindLabel: string
  sortTime: number
  detail: Array<{ label: string; value: string }>
  references: WorkbenchReference[]
  occurrenceCount: number
  diagnostic: Record<string, unknown>
}

function summarizeWorkbench(
  tree: any,
  nodes: NormalizedTraceNode[],
  snapshot: WorkbenchView,
  isActive: boolean,
  chatRunning: boolean,
  t: (zh: string, en: string) => string,
  runView = false,
) {
  const latest = nodes[nodes.length - 1]
  const rootGoal = String(snapshot.task?.title || snapshot.task?.objective || tree?.root_goal || tree?.goal || '').trim()
  const title = rootGoal || (chatRunning ? t('正在处理当前请求', 'Handling current request') : nodes.length ? t('本次活动', 'Session activity') : t('尚未开始', 'Not started'))
  const live = isActive || chatRunning
  const statusLabel = live ? t('进行中', 'Live') : tree || nodes.length ? t('最近记录', 'Recent activity') : t('待命', 'Idle')
  const currentStep = latest?.title
    ? [latest.title, latest.desc].filter(Boolean).join(' · ')
    : chatRunning
      ? t('正在准备', 'Preparing')
      : ''
  const runningNode = [...nodes].reverse().find((node) => ['running', 'active', 'pending', 'waiting_tool', 'waiting_human'].includes(node.nodeStatus))
  const activeNode = runningNode || latest

  return {
    title: compactText(title, 120),
    currentStep: compactText(currentStep, 180),
    phaseLabel: activityKindLabel(activeNode?.kind, live, t),
    live: live || ['running', 'waiting_user'].includes(String(runView ? snapshot.run?.status : snapshot.task?.status || '').toLowerCase()),
    statusLabel: taskStatusLabel(runView ? snapshot.run?.status : snapshot.task?.status, statusLabel, t),
  }
}

function workbenchView(snapshot: RuntimeWorkbenchSnapshot): WorkbenchView {
  const scope = (snapshot.scope || {}) as unknown as Record<string, unknown>
  return {
    scope,
    metrics: null,
    memoryProposals: Array.isArray(snapshot.memory_proposals) ? snapshot.memory_proposals : [],
    recallRuns: Array.isArray(snapshot.recall_runs) ? snapshot.recall_runs : [],
    workflowRuns: Array.isArray(snapshot.workflow_runs) ? snapshot.workflow_runs : [],
    recoveryItems: Array.isArray(snapshot.recovery_items) ? snapshot.recovery_items : [],
    task: snapshot.task || null,
    run: (snapshot.runs || []).find((run) => run.run_id === snapshot.scope.run_id) || null,
    timeline: snapshot.timeline || [],
    waitingActions: Array.isArray(snapshot.waiting_actions) ? snapshot.waiting_actions : [],
    activeRuntimeRuns: Array.isArray(snapshot.active_runtime_runs) ? snapshot.active_runtime_runs : [],
  }
}

function normalizeActivities(activities: WorkbenchActivity[], lang: 'zh' | 'en', t: (zh: string, en: string) => string): NormalizedTraceNode[] {
  return activities.map((activity, index: number) => {
    const kind = String(activity?.kind || 'runtime').toLowerCase()
    const status = String(activity?.status || 'observed').toLowerCase()
    const subject = compactText(localizedActivityText(activity?.subject_i18n, lang, activity?.subject), 100)
    const summary = compactText(localizedActivityText(activity?.summary_i18n, lang, activity?.summary), 220)
    const timestampValue = activity?.updated_at || activity?.occurred_at
    const timestamp = timestampValue ? new Date(timestampValue) : new Date()
    const detail = activityDetail(activity?.detail, t)
    return {
      id: String(activity?.activity_id || activity?.event_id || activity?.seq || index),
      title: activityTitle(kind, status, subject, t),
      desc: summary,
      nodeStatus: status,
      kind,
      kindLabel: `${activityKindLabel(kind, false, t)} · ${activityStatusLabel(status, t)}`,
      time: timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      sortTime: timestamp.getTime(),
      detail,
      references: Array.isArray(activity.references) ? activity.references : [],
      occurrenceCount: Number(activity.occurrence_count || 1),
      diagnostic: { event_type: activity.event_type, event_id: activity.event_id, trace_id: activity.trace_id, run_id: activity.run_id, conversation_turn_id: activity.conversation_turn_id, ...activity.detail },
    }
  })
}

function localizedActivityText(values: Record<string, string> | undefined, lang: 'zh' | 'en', fallback: unknown): string {
  return String(values?.[lang] || fallback || '')
}

function activityTitle(
  kind: string,
  status: string,
  subject: string,
  t: (zh: string, en: string) => string,
): string {
  if (subject && ['tool', 'memory', 'reasoning', 'artifact', 'environment', 'workflow'].includes(kind)) {
    return subject
  }
  return activityStateLabel(kind, status, t)
}

function activityStatusLabel(status: string, t: (zh: string, en: string) => string): string {
  if (['completed', 'complete', 'finished', 'succeeded', 'success'].includes(status)) return t('完成', 'Completed')
  if (['failed', 'error', 'interrupted'].includes(status)) return t('失败', 'Failed')
  if (['waiting', 'waiting_user', 'waiting_human', 'paused'].includes(status)) return t('等待', 'Waiting')
  return t('进行中', 'Running')
}

function activityDetail(detail: unknown, t: (zh: string, en: string) => string): Array<{ label: string; value: string }> {
  if (!detail || typeof detail !== 'object') return []
  const row = detail as Record<string, unknown>
  const out: Array<{ label: string; value: string }> = []
  const description = compactText(String(row.description || ''), 220)
  if (description) out.push({ label: t('用途', 'Purpose'), value: description })
  const argumentsText = formatKeyValues(row.arguments)
  if (argumentsText) out.push({ label: t('输入', 'Input'), value: argumentsText })
  const resultText = formatResultSummary(row.result_summary)
  if (resultText) out.push({ label: t('结果', 'Result'), value: resultText })
  return out
}

function formatKeyValues(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  return Object.entries(value as Record<string, unknown>)
    .slice(0, 4)
    .map(([key, item]) => `${key}: ${formatScalar(item)}`)
    .filter(Boolean)
    .join(' · ')
}

function formatResultSummary(value: unknown): string {
  if (typeof value === 'string') return compactText(value, 220)
  if (!value || typeof value !== 'object' || Array.isArray(value)) return formatScalar(value)
  const row = value as Record<string, unknown>
  if (row.value !== undefined) return formatScalar(row.value)
  if (Array.isArray(row.keys)) return row.keys.slice(0, 6).map(String).join(', ')
  if (row.size !== undefined) return String(row.size)
  return ''
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (['string', 'number', 'boolean'].includes(typeof value)) return compactText(String(value), 100)
  if (Array.isArray(value)) return value.slice(0, 3).map(formatScalar).filter(Boolean).join(', ')
  return ''
}

function activityStateLabel(kind: string, status: string, t: (zh: string, en: string) => string): string {
  const settled = ['completed', 'complete', 'finished', 'succeeded', 'success'].includes(status)
  const failed = ['failed', 'error', 'interrupted'].includes(status)
  const waiting = ['waiting', 'waiting_user', 'waiting_human', 'paused'].includes(status)
  const labels: Record<string, [[string, string], [string, string], [string, string], [string, string]]> = {
    task: [['正在处理任务', 'Working on task'], ['任务已完成', 'Task completed'], ['任务需要处理', 'Task needs attention'], ['任务正在等待', 'Task is waiting']],
    workflow: [['正在推进工作流', 'Advancing workflow'], ['工作流步骤已完成', 'Workflow step completed'], ['工作流遇到问题', 'Workflow needs attention'], ['工作流正在等待', 'Workflow is waiting']],
    tool: [['正在调用工具', 'Using a tool'], ['工具调用已完成', 'Tool call completed'], ['工具调用失败', 'Tool call failed'], ['工具调用正在等待', 'Tool call is waiting']],
    memory: [['正在读取记忆', 'Reading memory'], ['记忆处理已完成', 'Memory operation completed'], ['记忆处理失败', 'Memory operation failed'], ['记忆处理正在等待', 'Memory operation is waiting']],
    reasoning: [['正在分析', 'Reasoning'], ['分析已完成', 'Reasoning completed'], ['分析遇到问题', 'Reasoning needs attention'], ['分析正在等待', 'Reasoning is waiting']],
    artifact: [['正在生成成果', 'Producing artifact'], ['成果已生成', 'Artifact produced'], ['成果生成失败', 'Artifact failed'], ['成果正在等待', 'Artifact is waiting']],
    environment: [['正在准备环境', 'Preparing environment'], ['环境已就绪', 'Environment ready'], ['环境需要处理', 'Environment needs attention'], ['环境正在等待', 'Environment is waiting']],
  }
  const variants = labels[kind] || [['正在处理', 'Working'], ['已完成', 'Completed'], ['需要处理', 'Needs attention'], ['正在等待', 'Waiting']]
  const label = failed ? variants[2] : waiting ? variants[3] : settled ? variants[1] : variants[0]
  return t(label[0], label[1])
}

function activityKindLabel(kind: string | undefined, live: boolean, t: (zh: string, en: string) => string): string {
  const labels: Record<string, [string, string]> = {
    task: ['任务', 'Task'],
    workflow: ['工作流', 'Workflow'],
    tool: ['工具', 'Tool'],
    memory: ['记忆', 'Memory'],
    reasoning: ['分析', 'Reasoning'],
    artifact: ['成果', 'Artifact'],
    environment: ['环境', 'Environment'],
  }
  const label = labels[String(kind || '')]
  return label ? t(label[0], label[1]) : live ? t('准备', 'Preparing') : t('待命', 'Idle')
}

function compactText(value: string, maxLength: number) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(1, maxLength - 1))}...`
}

type TraceItemProps = {
  id: string
  time: string
  title: string
  desc: string
  icon: ReactNode
  status: 'active' | 'done'
  statusLabel?: string
  kind?: string
  detail?: Array<{ label: string; value: string }>
  references?: WorkbenchReference[]
  occurrenceCount?: number
  onOpenReference?: (reference: WorkbenchReference) => void
  diagnostic?: Record<string, unknown>
}

function TraceItem({ time, title, desc, icon, status, statusLabel, kind = '', detail = [], references = [], occurrenceCount = 1, onOpenReference, diagnostic }: TraceItemProps) {
  const { t } = useLanguage()
  const failed = ['failed', 'error', 'interrupted'].includes(String(statusLabel || '').toLowerCase())
  const active = status === 'active'
  const [open, setOpen] = useState(false)
  const hasDisclosure = Boolean(desc || detail.length || references.length)

  return (
    <div className={`activity-card ${open ? 'is-expanded' : ''} relative mb-2 rounded-md border border-black/5 bg-white/55 px-3 py-3 pl-10 last:mb-0`}>
      <div className={`absolute left-3 top-[15px] z-10 flex h-[19px] w-[19px] items-center justify-center rounded-full border bg-bg-card ${
        failed
          ? 'border-red-200 text-red-600'
          : status === 'active'
            ? 'border-brand-500 text-brand-700'
            : 'border-black/10 text-text-muted'
      }`}>
        {icon}
      </div>
      <button
        type="button"
        aria-expanded={hasDisclosure ? open : undefined}
        onClick={() => hasDisclosure && setOpen((value) => !value)}
        className={`flex w-full items-start gap-2 text-left ${hasDisclosure ? 'cursor-pointer' : 'cursor-default'}`}
      >
        <span className="min-w-0 flex-1">
          <span className={`block text-[13px] font-semibold leading-snug ${failed ? 'text-red-700' : active ? 'text-brand-700' : 'text-text-strong'}`}>
            {title}
          </span>
          {desc && <span className="mt-1 line-clamp-2 break-words text-xs leading-5 text-text-muted">{desc}</span>}
          <span className="mt-1 block text-[10px] text-text-muted">{kind}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5 pt-0.5 font-mono text-[10px] text-text-muted">
          {occurrenceCount > 1 && <span>x{occurrenceCount}</span>}
          {time}
          {hasDisclosure && (open ? <ChevronDown size={13} /> : <ChevronRight size={13} />)}
        </span>
      </button>
      {open && (
        <div className="pt-1">
          {(detail.length > 0 || diagnostic) && (
            <details className="mt-2 text-[11px] leading-4 text-text-muted">
              <summary className="cursor-pointer">{t('技术详情', 'Technical details')}</summary>
              <div className="mt-2 max-h-72 space-y-1.5 overflow-auto border-l border-black/10 pl-2.5">
              {detail.map((item) => (
                <div key={`${item.label}:${item.value}`}>
                  <span className="font-medium text-text-normal">{item.label}</span>
                  <span className="ml-1.5 break-words">{item.value}</span>
                </div>
              ))}
              {diagnostic && <pre className="whitespace-pre-wrap break-words py-2">{JSON.stringify(diagnostic, null, 2)}</pre>}
              </div>
            </details>
          )}
          {references.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              {references.map((reference) => (
                <button
                  key={reference.reference_id}
                  type="button"
                  onClick={() => void onOpenReference?.(reference)}
                  title={reference.kind === 'artifact' ? reference.target : reference.label}
                  className="flex min-w-0 items-center gap-2 py-1 text-left text-[11px] text-brand-700 hover:text-brand-800"
                >
                  {reference.kind === 'url'
                    ? <ExternalLink size={12} className="shrink-0" />
                    : reference.kind === 'canvas'
                      ? <MonitorPlay size={12} className="shrink-0" />
                      : reference.kind === 'memory'
                        ? <Database size={12} className="shrink-0" />
                        : reference.kind === 'cognition'
                          ? <Brain size={12} className="shrink-0" />
                      : <FileText size={12} className="shrink-0" />}
                  <span className="truncate underline decoration-brand-300 underline-offset-2">{reference.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
