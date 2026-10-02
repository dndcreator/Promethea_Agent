import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  Info,
  ListChecks,
  Pause,
  Play,
  Square,
} from 'lucide-react'
import {
  getActiveReasoning,
  cancelTask,
  getReasoningHistory,
  getReasoningTree,
  pauseTask,
  resumeTask,
  steerReasoningTree,
  stopReasoningTree,
  watchWorkbenchSnapshots,
} from '../services/api'
import type { Task, WorkbenchSnapshot as RuntimeWorkbenchSnapshot } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

interface RightSidebarProps {
  sessionId: string | null
  treeId: string | null
  chatRunning?: boolean
  onMemoryReviewChange?: (proposalId: string | null) => void
}

type WorkbenchView = {
  metrics: any | null
  memoryProposals: any[]
  recallRuns: any[]
  workflowRuns: any[]
  recoveryItems: any[]
  task: Task | null
  timeline: any[]
  waitingActions: any[]
  activeRuntimeRuns: string[]
}

type ActivityFilter = 'all' | 'tool' | 'memory' | 'decision' | 'error'

const EMPTY_WORKBENCH: WorkbenchView = {
  metrics: null,
  memoryProposals: [],
  recallRuns: [],
  workflowRuns: [],
  recoveryItems: [],
  task: null,
  timeline: [],
  waitingActions: [],
  activeRuntimeRuns: [],
}

export default function RightSidebar({ sessionId, treeId, chatRunning = false, onMemoryReviewChange }: RightSidebarProps) {
  const { t } = useLanguage()
  const { user } = useAuth()
  const [tree, setTree] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null)
  const [steerNote, setSteerNote] = useState('')
  const [workbench, setWorkbench] = useState<WorkbenchView>(EMPTY_WORKBENCH)
  const [taskControlPending, setTaskControlPending] = useState(false)
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>('all')

  useEffect(() => {
    if (treeId) setSelectedTreeId(null)
  }, [treeId])

  useEffect(() => {
    let cancelled = false

    const fetchHistory = async () => {
      try {
        const res = await getReasoningHistory(sessionId, 30)
        if (!res.ok || cancelled) return
        const data = await res.json()
        const items = Array.isArray(data.items) ? data.items : []
        setHistory(dedupeTraceItems(items))
      } catch (error) {
        if (!cancelled) console.error(error)
      }
    }

    fetchHistory()
    const interval = window.setInterval(fetchHistory, 20000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [sessionId, chatRunning])

  useEffect(() => {
    let cancelled = false
    let interval: number | undefined

    const fetchTree = async () => {
      try {
        let activeTreeId = selectedTreeId || treeId

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
          if (res.ok && !cancelled) setTree(await res.json())
        } else if (!cancelled) {
          setTree(null)
        }
      } catch (error) {
        if (!cancelled) console.error(error)
      }
    }

    fetchTree()
    if (chatRunning || treeId || selectedTreeId) {
      interval = window.setInterval(fetchTree, chatRunning ? 2000 : 10000)
    }
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [sessionId, treeId, selectedTreeId, chatRunning])

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    if (!user) {
      setWorkbench(EMPTY_WORKBENCH)
      return () => {
        cancelled = true
        controller.abort()
      }
    }

    const consumeWorkbench = async () => {
      try {
        for await (const data of watchWorkbenchSnapshots(sessionId, null, null, controller.signal)) {
          if (cancelled) return
          const memoryProposals = Array.isArray(data.memory_proposals) ? data.memory_proposals : []
          setWorkbench((previous) => workbenchView(data, previous))
          const relevantProposals = sessionId
            ? memoryProposals.filter((proposal: any) => String(proposal?.session_id || '') === sessionId)
            : memoryProposals
          const latestProposal = relevantProposals[relevantProposals.length - 1]
          onMemoryReviewChange?.(latestProposal ? String(latestProposal.proposal_id || '') || null : null)
        }
      } catch (error) {
        if (!cancelled && !controller.signal.aborted) console.error(error)
      }
    }

    consumeWorkbench()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [sessionId, user, onMemoryReviewChange])

  const currentTreeId = tree?.tree_id || tree?.id
  const reasoningNodes = normalizeNodes(tree, t)
  const projectedNodes = normalizeActivities(workbench.timeline, t)
  const nodes = projectedNodes.length > 0 ? projectedNodes : reasoningNodes
  const taskStatus = String(workbench.task?.status || '').toLowerCase()
  const isActive = ['running', 'active', 'pending', 'waiting_user'].includes(taskStatus || String(tree?.status || '').toLowerCase())
  const activeHistoryId = selectedTreeId || currentTreeId
  const summary = useMemo(
    () => summarizeWorkbench(tree, nodes, workbench, isActive, chatRunning, t),
    [tree, nodes, workbench, isActive, chatRunning, t],
  )
  const filteredNodes = useMemo(
    () => nodes.filter((node) => activityFilter === 'all' || activityCategory(node) === activityFilter),
    [activityFilter, nodes],
  )
  const showControls = Boolean(
    (tree && summary.live && !workbench.task)
    || (workbench.task && ['running', 'paused', 'waiting_user'].includes(taskStatus)),
  )

  const handleStop = async () => {
    setTaskControlPending(true)
    try {
      if (workbench.task?.task_id) {
        const task = await cancelTask(
          String(workbench.task.task_id),
          'user_cancelled',
          workbench.task.revision,
        )
        setWorkbench((prev) => ({ ...prev, task }))
      } else if (currentTreeId) {
        await stopReasoningTree(currentTreeId, 'User stopped via UI')
        setTree((prev: any) => ({ ...prev, status: 'stopped' }))
      }
    } finally {
      setTaskControlPending(false)
    }
  }

  const handlePauseResume = async () => {
    const taskId = String(workbench.task?.task_id || '')
    if (!taskId) return
    setTaskControlPending(true)
    try {
      const task = taskStatus === 'paused'
        ? await resumeTask(taskId, workbench.task?.revision)
        : await pauseTask(taskId, workbench.task?.revision)
      setWorkbench((prev) => ({ ...prev, task }))
    } finally {
      setTaskControlPending(false)
    }
  }

  const handleSteer = async () => {
    if (currentTreeId && steerNote.trim()) {
      await steerReasoningTree(currentTreeId, steerNote.trim())
      setSteerNote('')
    }
  }

  return (
    <aside className="relative flex h-full w-full shrink-0 flex-col overflow-hidden rounded-lg glass-panel">
      <div className="z-10 flex shrink-0 items-center justify-between border-b border-black/5 bg-bg-card/70 px-4 py-3">
        <h2 className="flex items-baseline gap-2 font-display text-[17px] font-semibold text-text-strong">
          {t('任务工作台', 'Workbench')}
        </h2>
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-text-muted">
          <span className={`h-1.5 w-1.5 rounded-full bg-brand-600 ${summary.live ? 'animate-pulse' : ''}`} />
          {summary.statusLabel}
        </div>
      </div>

      <div className="z-10 border-b border-black/5 bg-bg-card/50 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-text-strong">{summary.title}</h3>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{summary.currentStep}</p>
          </div>
          {(workbench.task?.task_id || currentTreeId) && (
            <span className="shrink-0 font-mono text-[10px] text-text-muted">
              {String(workbench.task?.task_id || currentTreeId).slice(0, 8)}
            </span>
          )}
        </div>
        <div className="mt-2 flex items-center gap-2 text-[10px] text-text-muted">
          <span>{summary.phaseLabel}</span>
          <span>·</span>
          <span>{nodes.length} {t('条活动', 'events')}</span>
          {summary.reviewCount > 0 && (
            <>
              <span>·</span>
              <span className="font-medium text-amber-700">{summary.reviewCount} {t('项待处理', 'need review')}</span>
            </>
          )}
        </div>
        <button
          type="button"
          onClick={() => setHistoryOpen((value) => !value)}
          className="mt-3 flex w-full items-center justify-between border-t border-black/5 pt-2 text-left text-xs font-medium text-text-normal transition-colors hover:text-brand-700"
        >
          <span className="flex items-center gap-2"><ListChecks size={13} />{t('运行记录', 'Run history')}</span>
          <span className="font-mono text-[10px] text-text-muted">{history.length}</span>
        </button>
        {historyOpen && (
          <div className="mt-2 max-h-44 overflow-y-auto border-l border-black/10 pl-2">
            {history.length === 0 ? (
              <div className="px-2 py-3 text-center text-[11px] text-text-muted">
                {t('暂无运行记录', 'No runs yet')}
              </div>
            ) : (
              history.map((item) => {
                const itemId = String(item.tree_id || item.id || '')
                const selected = itemId && itemId === activeHistoryId
                return (
                  <button
                    key={itemId}
                    type="button"
                    onClick={() => {
                      if (!itemId) return
                      setSelectedTreeId(itemId)
                      setTree(null)
                      setHistoryOpen(false)
                    }}
                    className={`mb-1 w-full px-2 py-1.5 text-left text-[11px] transition-colors last:mb-0 ${
                      selected ? 'bg-brand-50 text-brand-800' : 'text-text-normal hover:bg-black/[0.03]'
                    }`}
                  >
                    <div className="truncate font-semibold">{item.root_goal || t('未命名任务', 'Untitled run')}</div>
                    <div className="mt-1 flex items-center gap-1.5 text-[10px] text-text-muted">
                      <span>{item.status || 'unknown'}</span>
                      <span>·</span>
                      <span>{formatTraceDuration(item)}</span>
                      <span>·</span>
                      <span className="font-mono">{itemId.slice(0, 6)}</span>
                    </div>
                  </button>
                )
              })
            )}
          </div>
        )}
      </div>

      <div className="relative z-10 flex-1 overflow-y-auto px-4 py-3">
        <div className="flex min-h-full flex-col">
          <div className="mb-3 flex shrink-0 rounded-md bg-black/[0.035] p-0.5">
            {activityFilters(t).map((filter) => (
              <button
                key={filter.id}
                type="button"
                onClick={() => setActivityFilter(filter.id)}
                className={`min-w-0 flex-1 px-1 py-1.5 text-[10px] font-medium transition-colors ${
                  activityFilter === filter.id ? 'rounded bg-bg-card text-text-strong shadow-sm' : 'text-text-muted hover:text-text-normal'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>

          {!tree && nodes.length === 0 && (
            <div className="m-auto py-8 text-center">
              <Info size={22} className="mx-auto mb-2 text-text-muted" />
              <p className="text-sm font-medium text-text-normal">
                {chatRunning ? t('等待运行态', 'Waiting for state') : t('空闲', 'Idle')}
              </p>
            </div>
          )}

          {filteredNodes.length > 0 && (
            <div className="relative flex-1">
              <div className="absolute bottom-3 left-[9px] top-3 w-px bg-black/10" />
              <div className="flex flex-col">
                {filteredNodes.map((node, index) => (
                  <TraceItem
                    id={node.id}
                    key={node.id}
                    time={node.time}
                    title={node.title}
                    desc={node.desc}
                    kind={node.kind}
                    statusLabel={node.nodeStatus}
                    icon={
                      node.nodeStatus === 'succeeded'
                        ? <CheckCircle2 size={12} />
                        : ['failed', 'error'].includes(node.nodeStatus)
                          ? <AlertCircle size={12} />
                          : <CircleDot size={12} className={index === filteredNodes.length - 1 && summary.live ? 'animate-pulse' : ''} />
                    }
                    status={node.nodeStatus === 'running' || (index === filteredNodes.length - 1 && summary.live) ? 'active' : 'done'}
                  />
                ))}
              </div>
            </div>
          )}

          {nodes.length > 0 && filteredNodes.length === 0 && (
            <div className="m-auto py-8 text-center text-xs text-text-muted">
              {t('当前筛选下没有活动', 'No activity in this filter')}
            </div>
          )}

          {(tree || workbench.task) && nodes.length === 0 && (
            <TraceItem
              id="initializing"
              time={new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              title={t('初始化', 'Initializing')}
              desc={t('Agent 正在建立可检查的任务运行过程。', 'Agent is setting up an inspectable task run.')}
              icon={<div className="h-2 w-2 animate-pulse rounded-full bg-brand-600" />}
              status="active"
            />
          )}
        </div>
      </div>

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
                disabled={!steerNote.trim()}
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
}

function summarizeWorkbench(
  tree: any,
  nodes: NormalizedTraceNode[],
  snapshot: WorkbenchView,
  isActive: boolean,
  chatRunning: boolean,
  t: (zh: string, en: string) => string,
) {
  const latest = nodes[nodes.length - 1]
  const rootGoal = String(snapshot.task?.title || snapshot.task?.objective || tree?.root_goal || tree?.goal || '').trim()
  const title = rootGoal || (chatRunning ? t('正在处理当前请求', 'Handling current request') : t('等待用户目标', 'Waiting for a user goal'))
  const completedSteps = nodes.filter((node) => ['succeeded', 'done', 'completed'].includes(node.nodeStatus)).length
  const live = isActive || chatRunning
  const taskState = live ? t('运行', 'Live') : tree ? t('结束', 'Done') : t('空闲', 'Idle')
  const statusLabel = live ? t('进行中', 'Live') : tree ? t('已沉淀', 'Settled') : t('待命', 'Idle')
  const currentStep = latest?.title
    ? `${latest.title}: ${latest.desc}`
    : chatRunning
      ? t('等待可观察步骤', 'Waiting for observable steps')
      : t('无活跃任务', 'No active task')
  const runningNode = [...nodes].reverse().find((node) => ['running', 'active', 'pending', 'waiting_tool', 'waiting_human'].includes(node.nodeStatus))
  const activeNode = runningNode || latest
  const phaseLabel = inferPhaseLabel(activeNode, live, t)

  const toolNodes = nodes.filter(isToolLikeNode)
  const latestToolNode = toolNodes[toolNodes.length - 1]
  const toolSummary = latestToolNode
    ? compactText(`${latestToolNode.title}: ${latestToolNode.desc}`, 150)
    : t('无工具调用', 'No tool calls')
  const latestTool = latestToolNode
    ? `${latestToolNode.kind} · ${latestToolNode.nodeStatus}`
    : readMetricHint(snapshot.metrics, ['tools', 'tool_calls', 'runtime_tools']) || t('无工具活动', 'No tool activity')

  const memoryPending = snapshot.memoryProposals.length
  const recallRuns = snapshot.recallRuns.length
  const memorySummary = memoryPending > 0
    ? t(`有 ${memoryPending} 条记忆写入需要确认。`, `${memoryPending} memory writes need review.`)
    : recallRuns > 0
      ? t(`最近有 ${recallRuns} 次记忆召回记录。`, `${recallRuns} recent memory recall runs.`)
      : t('无待确认记忆', 'No pending memory')
  const memoryMeta = memoryPending > 0
    ? t('需要用户确认', 'Needs review')
    : recallRuns > 0
      ? t('召回可追踪', 'Recall tracked')
      : t('安静', 'Quiet')

  const activeWorkflowRuns = snapshot.workflowRuns.filter((run) => isOpenRunStatus(run?.status)).length
  const recoveryCount = snapshot.recoveryItems.length
  const latestWorkflow = snapshot.workflowRuns[0]
  const workflowSummary = activeWorkflowRuns > 0
    ? t(`有 ${activeWorkflowRuns} 个工作流仍在运行或等待。`, `${activeWorkflowRuns} workflow runs are active or waiting.`)
    : recoveryCount > 0
      ? t(`有 ${recoveryCount} 个工作流恢复项需要关注。`, `${recoveryCount} workflow recovery items need attention.`)
      : latestWorkflow
        ? compactText(String(latestWorkflow.name || latestWorkflow.workflow_name || latestWorkflow.run_id || t('最近工作流已结束', 'Latest workflow settled')), 150)
        : t('未接管', 'Not engaged')
  const workflowMeta = activeWorkflowRuns > 0
    ? t('执行中', 'Running')
    : recoveryCount > 0
      ? t('待恢复', 'Recovery')
      : latestWorkflow?.status || t('无工作流', 'No workflow')

  return {
    title: compactText(title, 120),
    currentStep: compactText(currentStep, 180),
    phaseLabel,
    completedSteps,
    live: live || ['running', 'waiting_user'].includes(String(snapshot.task?.status || '').toLowerCase()),
    taskState: String(snapshot.task?.status || taskState),
    statusLabel: taskStatusLabel(snapshot.task?.status, statusLabel, t),
    toolNodes,
    toolSummary,
    latestTool,
    memorySummary,
    memoryMeta,
    workflowSummary,
    workflowMeta,
    reviewCount: memoryPending + recoveryCount,
  }
}

function workbenchView(snapshot: RuntimeWorkbenchSnapshot, previous: WorkbenchView): WorkbenchView {
  const incoming = Array.isArray(snapshot.timeline) ? snapshot.timeline : []
  const merged = new Map<number | string, any>()
  for (const activity of [...previous.timeline, ...incoming]) {
    const key = String(activity?.activity_id || activity?.event_id || activity?.seq || '')
    const existing = merged.get(key)
    merged.set(key, {
      ...existing,
      ...activity,
      occurred_at: existing?.occurred_at || activity?.occurred_at,
      subject: activity?.subject || existing?.subject || '',
      summary: activity?.summary || existing?.summary || '',
      detail: { ...(existing?.detail || {}), ...(activity?.detail || {}) },
    })
  }
  const timeline = [...merged.values()]
    .sort((left, right) => Number(left?.seq || 0) - Number(right?.seq || 0))
    .slice(-160)
  return {
    metrics: null,
    memoryProposals: Array.isArray(snapshot.memory_proposals) ? snapshot.memory_proposals : [],
    recallRuns: Array.isArray(snapshot.recall_runs) ? snapshot.recall_runs : [],
    workflowRuns: Array.isArray(snapshot.workflow_runs) ? snapshot.workflow_runs : [],
    recoveryItems: Array.isArray(snapshot.recovery_items) ? snapshot.recovery_items : [],
    task: snapshot.task || null,
    timeline,
    waitingActions: Array.isArray(snapshot.waiting_actions) ? snapshot.waiting_actions : [],
    activeRuntimeRuns: Array.isArray(snapshot.active_runtime_runs) ? snapshot.active_runtime_runs : [],
  }
}

function taskStatusLabel(status: unknown, fallback: string, t: (zh: string, en: string) => string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'running') return t('进行中', 'Live')
  if (value === 'waiting_user') return t('等待确认', 'Waiting')
  if (value === 'paused') return t('已暂停', 'Paused')
  if (value === 'completed') return t('已完成', 'Completed')
  if (value === 'failed') return t('失败', 'Failed')
  if (value === 'cancelled') return t('已取消', 'Cancelled')
  return fallback
}

function activityFilters(t: (zh: string, en: string) => string): Array<{ id: ActivityFilter; label: string }> {
  return [
    { id: 'all', label: t('全部', 'All') },
    { id: 'tool', label: t('工具', 'Tools') },
    { id: 'memory', label: t('记忆', 'Memory') },
    { id: 'decision', label: t('决策', 'Decisions') },
    { id: 'error', label: t('异常', 'Errors') },
  ]
}

function activityCategory(node: NormalizedTraceNode): Exclude<ActivityFilter, 'all'> {
  const status = node.nodeStatus.toLowerCase()
  if (['failed', 'error', 'cancelled', 'canceled'].includes(status)) return 'error'

  const kind = node.kind.toLowerCase()
  if (['tool', 'search', 'action', 'mcp', 'browser', 'shell'].some((value) => kind.includes(value))) return 'tool'
  if (['memory', 'recall'].some((value) => kind.includes(value))) return 'memory'
  return 'decision'
}

function normalizeActivities(activities: any[], t: (zh: string, en: string) => string): NormalizedTraceNode[] {
  return activities.map((activity: any, index: number) => {
    const kind = String(activity?.kind || 'runtime').toLowerCase()
    const status = String(activity?.status || 'observed').toLowerCase()
    const subject = readableText(activity?.subject)
    const summary = readableText(activity?.summary)
    const detail = asRecord(activity?.detail)
    const resultMetadata = asRecord(detail.result_metadata)
    const presentationKind = String(resultMetadata.kind || '').toLowerCase()
    const completed = ['completed', 'complete', 'finished', 'succeeded', 'success'].includes(status)
    const failed = ['failed', 'error'].includes(status)
    const labels: Record<string, [string, string]> = {
      task: [completed ? '任务已完成' : failed ? '任务遇到问题' : '任务状态已更新', completed ? 'Task completed' : failed ? 'Task needs attention' : 'Task state updated'],
      workflow: [completed ? '工作流步骤已完成' : failed ? '工作流步骤失败' : '正在推进工作流', completed ? 'Workflow step completed' : failed ? 'Workflow step failed' : 'Advancing workflow'],
      tool: [completed ? '工具调用完成' : failed ? '工具调用失败' : '正在调用工具', completed ? 'Tool call completed' : failed ? 'Tool call failed' : 'Calling tool'],
      memory: [completed ? '记忆处理完成' : failed ? '记忆处理失败' : '正在处理记忆', completed ? 'Memory operation completed' : failed ? 'Memory operation failed' : 'Processing memory'],
      reasoning: [completed ? '分析完成' : failed ? '分析遇到问题' : '正在分析下一步', completed ? 'Reasoning completed' : failed ? 'Reasoning needs attention' : 'Reasoning about next step'],
      artifact: [completed ? '工作成果已生成' : failed ? '工作成果生成失败' : '正在更新工作成果', completed ? 'Artifact produced' : failed ? 'Artifact failed' : 'Updating artifact'],
      runtime: ['状态已更新', 'State updated'],
    }
    const label = presentationKind === 'web_search'
      ? [completed ? '网页搜索完成' : failed ? '网页搜索失败' : '正在搜索网页', completed ? 'Web search completed' : failed ? 'Web search failed' : 'Searching the web']
      : labels[kind] || labels.runtime
    const timestamp = activity?.occurred_at ? new Date(activity.occurred_at) : new Date()
    const sourceNames = Array.isArray(resultMetadata.sources)
      ? resultMetadata.sources.map((source: any) => readableText(source?.title || source?.url)).filter(Boolean).slice(0, 2)
      : []
    const searchDescription = presentationKind === 'web_search'
      ? compactText([
          readableText(resultMetadata.query),
          resultMetadata.count !== undefined ? t(`${resultMetadata.count} 个来源`, `${resultMetadata.count} sources`) : '',
          resultMetadata.provider ? t(`经由 ${resultMetadata.provider}`, `via ${resultMetadata.provider}`) : '',
          ...sourceNames,
        ].filter(Boolean).join(' · '), 200)
      : ''
    return {
      id: String(activity?.activity_id || activity?.event_id || activity?.seq || index),
      title: t(label[0], label[1]),
      desc: searchDescription || compactText([subject, summary].filter(Boolean).join(' · ') || t('状态已更新', 'State updated'), 200),
      nodeStatus: status,
      kind: presentationKind === 'web_search' ? 'search' : kind,
      time: timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    }
  })
}

function normalizeNodes(tree: any, t: (zh: string, en: string) => string): NormalizedTraceNode[] {
  const rawNodes = Array.isArray(tree?.nodes) ? tree.nodes : Object.values(tree?.nodes || {})
  return rawNodes
    .map((node: any, index: number): NormalizedTraceNode => {
      const semantic = describeTraceNode(node, index, t)
      const timestamp = node.created_at || node.updated_at
      return {
        id: node.node_id || node.id || `${index}`,
        title: semantic.title,
        desc: semantic.desc,
        nodeStatus: String(node.status || 'pending').toLowerCase(),
        kind: semantic.kind,
        time: timestamp
          ? new Date(Number(timestamp) * (Number(timestamp) < 10000000000 ? 1000 : 1)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          : new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      }
    })
    .sort((a: any, b: any) => {
      const aRaw = rawNodes.find((node: any) => (node.node_id || node.id) === a.id)
      const bRaw = rawNodes.find((node: any) => (node.node_id || node.id) === b.id)
      const aTime = Number(aRaw?.created_at || aRaw?.updated_at || 0)
      const bTime = Number(bRaw?.created_at || bRaw?.updated_at || 0)
      return aTime - bTime
    })
}

function describeTraceNode(
  node: any,
  index: number,
  t: (zh: string, en: string) => string,
): { title: string; desc: string; kind: string } {
  const metadata = asRecord(node?.metadata)
  const result = asRecord(node?.result)
  const status = String(node?.status || '').toLowerCase()
  const kindRaw = String(node?.kind || '').toLowerCase()
  const titleRaw = readableText(node?.title || node?.action || '')
  const goal = readableText(metadata.goal)
  const notes = readableText(metadata.notes)
  const memoryQuery = readableText(metadata.memory_query || metadata.query)
  const toolIntent = readableText(metadata.tool_intent || metadata.action_intent || result.action_intent)
  const toolName = readableText(
    metadata.tool_name ||
    metadata.name ||
    result.tool_name ||
    joinToolName(metadata.service_name, metadata.tool_name) ||
    joinToolName(result.service_name, result.tool_name),
  )
  const summary = firstReadable([
    node?.summary,
    node?.observation,
    node?.decision,
    node?.thought,
    result.summary,
    result.message,
    result.content,
    result.text,
    result.error,
  ])
  const evidence = Array.isArray(node?.evidence)
    ? node.evidence.map(readableText).filter(Boolean).slice(0, 2).join(' · ')
    : ''

  if (kindRaw === 'root') {
    return {
      title: t('接收任务目标', 'Received task goal'),
      desc: compactText(goal || titleRaw || summary || t('等待 Agent 拆解任务。', 'Waiting for the agent to break down the task.'), 180),
      kind: t('目标', 'Goal'),
    }
  }

  if (status === 'waiting_human') {
    return {
      title: t('等待用户确认', 'Waiting for user input'),
      desc: compactText(summary || notes || goal || t('这个步骤需要用户确认或补充信息。', 'This step needs confirmation or more input.'), 180),
      kind: t('确认', 'Review'),
    }
  }

  if (status === 'waiting_tool') {
    return {
      title: t('等待工具结果', 'Waiting for tool result'),
      desc: compactText(toolName || toolIntent || summary || t('Agent 已发起工具调用，正在等待返回。', 'The agent has requested a tool result.'), 180),
      kind: t('工具', 'Tool'),
    }
  }

  if (metadata.requires_memory === true || memoryQuery || looksLikeMemory(kindRaw, titleRaw, summary)) {
    const details = [
      memoryQuery ? `${t('查询', 'Query')}: ${memoryQuery}` : '',
      summary && !looksLikeJson(summary) ? summary : '',
      evidence ? `${t('线索', 'Evidence')}: ${evidence}` : '',
    ].filter(Boolean)
    return {
      title: t('召回相关记忆', 'Recalling relevant memory'),
      desc: compactText(details.join(' · ') || goal || notes || t('Agent 正在查找与当前任务相关的长期记忆。', 'The agent is looking up relevant long-term memory.'), 200),
      kind: t('记忆', 'Memory'),
    }
  }

  if (metadata.requires_tools === true || toolIntent || toolName || Array.isArray(node?.tool_calls) || isToolKind(kindRaw)) {
    const details = [
      toolName ? `${t('工具', 'Tool')}: ${toolName}` : '',
      toolIntent ? `${t('意图', 'Intent')}: ${toolIntent}` : '',
      summary && !looksLikeJson(summary) ? summary : '',
    ].filter(Boolean)
    return {
      title: status === 'succeeded' ? t('工具调用完成', 'Tool call completed') : t('准备调用工具', 'Preparing tool use'),
      desc: compactText(details.join(' · ') || goal || notes || t('Agent 正在把当前目标转换成可执行工具动作。', 'The agent is turning the goal into an executable tool action.'), 200),
      kind: t('工具', 'Tool'),
    }
  }

  if (looksLikeWorkflow(kindRaw, titleRaw, summary)) {
    return {
      title: t('推进工作流', 'Advancing workflow'),
      desc: compactText(summary || goal || notes || t('Agent 正在检查工作流状态、步骤或恢复点。', 'The agent is checking workflow state, steps, or recovery points.'), 180),
      kind: t('工作流', 'Workflow'),
    }
  }

  if (looksLikeSynthesis(kindRaw, titleRaw, summary)) {
    return {
      title: t('整理最终回应', 'Synthesizing response'),
      desc: compactText(summary || goal || notes || t('Agent 正在把已有观察整理成可交付回答。', 'The agent is turning observations into a final response.'), 180),
      kind: t('综合', 'Synthesis'),
    }
  }

  if (goal || notes || titleRaw) {
    return {
      title: titleRaw || t('规划下一步', 'Planning next step'),
      desc: compactText([goal, notes, summary].filter(Boolean).join(' · ') || t('Agent 正在评估下一步行动。', 'The agent is evaluating the next step.'), 200),
      kind: t('思考', 'Reasoning'),
    }
  }

  return {
    title: t(`步骤 ${index + 1}`, `Step ${index + 1}`),
    desc: compactText(summary || t('Agent 正在处理这个运行步骤。', 'The agent is processing this run step.'), 180),
    kind: t('步骤', 'Step'),
  }
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function readableText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') {
    const trimmed = value.replace(/\s+/g, ' ').trim()
    if (!trimmed) return ''
    const parsed = parseJsonish(trimmed)
    if (parsed !== trimmed) return parsed
    return trimmed
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.map(readableText).filter(Boolean).slice(0, 3).join(' · ')
  }
  if (typeof value === 'object') {
    const record = value as Record<string, any>
    const preferred = [
      'summary',
      'message',
      'content',
      'text',
      'answer',
      'observation',
      'result',
      'error',
      'reason',
      'goal',
      'notes',
      'memory_query',
      'tool_intent',
      'action_intent',
      'query',
    ]
    for (const key of preferred) {
      const text = readableText(record[key])
      if (text) return text
    }
    const pairs = Object.entries(record)
      .filter(([, item]) => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')
      .slice(0, 3)
      .map(([key, item]) => `${humanizeKey(key)}: ${String(item).trim()}`)
    return pairs.join(' · ')
  }
  return ''
}

function parseJsonish(value: string): string {
  const first = value[0]
  if (first !== '{' && first !== '[') return value
  try {
    const parsed = JSON.parse(value)
    return readableText(parsed) || value
  } catch {
    return value
  }
}

function firstReadable(values: unknown[]): string {
  for (const value of values) {
    const text = readableText(value)
    if (text) return text
  }
  return ''
}

function joinToolName(serviceName: unknown, toolName: unknown): string {
  const service = readableText(serviceName)
  const tool = readableText(toolName)
  if (service && tool) return `${service}.${tool}`
  return service || tool
}

function looksLikeJson(value: string): boolean {
  const text = value.trim()
  return (text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))
}

function humanizeKey(key: string): string {
  return key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function looksLikeMemory(kind: string, title: string, summary: string): boolean {
  const text = `${kind} ${title} ${summary}`.toLowerCase()
  return ['memory', 'recall', 'remember', 'retriev'].some((term) => text.includes(term)) || text.includes('记忆') || text.includes('召回')
}

function isToolKind(kind: string): boolean {
  return ['tool', 'action', 'mcp_call', 'browser', 'shell', 'workflow_tool'].some((term) => kind.includes(term))
}

function looksLikeWorkflow(kind: string, title: string, summary: string): boolean {
  const text = `${kind} ${title} ${summary}`.toLowerCase()
  return ['workflow', 'checkpoint', 'recovery'].some((term) => text.includes(term)) || text.includes('工作流') || text.includes('恢复点')
}

function looksLikeSynthesis(kind: string, title: string, summary: string): boolean {
  const text = `${kind} ${title} ${summary}`.toLowerCase()
  return ['summary', 'synth', 'answer', 'final'].some((term) => text.includes(term)) || text.includes('总结') || text.includes('答案')
}

function isToolLikeNode(node: NormalizedTraceNode): boolean {
  const text = `${node.kind} ${node.title} ${node.desc}`.toLowerCase()
  return ['tool', 'action', 'mcp', 'browser', 'shell', 'workflow', 'call'].some((term) => text.includes(term))
}

function inferPhaseLabel(
  node: NormalizedTraceNode | undefined,
  live: boolean,
  t: (zh: string, en: string) => string,
): string {
  if (!node) return live ? t('准备', 'Preparing') : t('待命', 'Idle')
  const text = `${node.kind} ${node.title} ${node.desc}`.toLowerCase()
  if (text.includes('tool') || text.includes('call') || text.includes('browser') || text.includes('shell') || text.includes('mcp')) {
    return t('调用工具', 'Using tools')
  }
  if (text.includes('memory') || text.includes('recall') || text.includes('记忆') || text.includes('召回')) {
    return t('读取记忆', 'Reading memory')
  }
  if (text.includes('workflow') || text.includes('checkpoint') || text.includes('工作流')) {
    return t('推进工作流', 'Workflow')
  }
  if (text.includes('plan') || text.includes('goal') || text.includes('strategy') || text.includes('计划')) {
    return t('规划', 'Planning')
  }
  if (text.includes('summary') || text.includes('synth') || text.includes('answer') || text.includes('总结')) {
    return t('整理答案', 'Synthesizing')
  }
  return live ? t('思考中', 'Thinking') : t('已结束', 'Settled')
}

function isOpenRunStatus(status: unknown): boolean {
  const value = String(status || '').toLowerCase()
  if (!value) return false
  return !['completed', 'succeeded', 'success', 'failed', 'cancelled', 'canceled', 'stopped', 'done'].includes(value)
}

function readMetricHint(metrics: any, keys: string[]): string {
  if (!metrics || typeof metrics !== 'object') return ''
  for (const key of keys) {
    const value = metrics[key]
    if (typeof value === 'number') return String(value)
    if (value && typeof value === 'object') {
      const total = value.total || value.count || value.calls
      if (typeof total === 'number') return String(total)
    }
  }
  return ''
}

function compactText(value: string, maxLength: number) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(1, maxLength - 1))}...`
}

function dedupeTraceItems(items: any[]): any[] {
  const seen = new Set<string>()
  const out: any[] = []
  for (const item of items) {
    const id = String(item?.tree_id || item?.id || '')
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push(item)
  }
  return out
}

function formatTraceDuration(item: any): string {
  const start = Number(item?.created_at || 0)
  const end = Number(item?.updated_at || 0)
  if (!start || !end || end < start) return '-'
  const seconds = Math.max(0, Math.round(end - start))
  if (seconds < 60) return `${seconds}s`
  return `${Math.round(seconds / 60)}m`
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
}

function TraceItem({ time, title, desc, icon, status, statusLabel, kind = 'thought' }: TraceItemProps) {
  const failed = ['failed', 'error'].includes(String(statusLabel || '').toLowerCase())
  return (
    <div className="relative border-b border-black/5 py-3 pl-8 last:border-b-0">
      <div className={`absolute left-0 top-[15px] z-10 flex h-[19px] w-[19px] items-center justify-center rounded-full border bg-bg-card ${
        failed
          ? 'border-red-200 text-red-600'
          : status === 'active'
            ? 'border-brand-500 text-brand-700'
            : 'border-black/10 text-text-muted'
      }`}>
        {icon}
      </div>
      <div className="flex items-start justify-between gap-2">
        <h4 className={`min-w-0 flex-1 text-[13px] font-semibold leading-snug ${failed ? 'text-red-700' : status === 'active' ? 'text-brand-700' : 'text-text-strong'}`}>
          {title}
        </h4>
        <span className="shrink-0 font-mono text-[10px] text-text-muted">{time}</span>
      </div>
      <p className="mt-1 text-xs leading-5 text-text-muted">{desc}</p>
      <div className="mt-1.5 text-[10px] text-text-muted">
        {kind}{(status === 'active' || failed) ? ` · ${statusLabel || status}` : ''}
      </div>
    </div>
  )
}
