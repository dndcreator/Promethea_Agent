import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  Database,
  GitBranch,
  Info,
  ListChecks,
  Square,
  Target,
  Wrench,
} from 'lucide-react'
import {
  getActiveReasoning,
  getMemoryRecallRuns,
  getMemoryWriteProposals,
  getReasoningHistory,
  getReasoningTree,
  listPersonalWorkflowRuns,
  listWorkflowRecovery,
  steerReasoningTree,
  stopReasoningTree,
} from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

interface RightSidebarProps {
  sessionId: string | null
  treeId: string | null
  chatRunning?: boolean
}

type WorkbenchSnapshot = {
  metrics: any | null
  memoryProposals: any[]
  recallRuns: any[]
  workflowRuns: any[]
  recoveryItems: any[]
}

const EMPTY_WORKBENCH: WorkbenchSnapshot = {
  metrics: null,
  memoryProposals: [],
  recallRuns: [],
  workflowRuns: [],
  recoveryItems: [],
}

export default function RightSidebar({ sessionId, treeId, chatRunning = false }: RightSidebarProps) {
  const { t } = useLanguage()
  const { user } = useAuth()
  const [tree, setTree] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [selectedTreeId, setSelectedTreeId] = useState<string | null>(null)
  const [steerNote, setSteerNote] = useState('')
  const [workbench, setWorkbench] = useState<WorkbenchSnapshot>(EMPTY_WORKBENCH)

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

    if (!user) {
      setWorkbench(EMPTY_WORKBENCH)
      return () => {
        cancelled = true
      }
    }

    const fetchWorkbench = async () => {
      try {
        const [proposals, recalls, workflowRuns, recovery] = await Promise.all([
          readJson(getMemoryWriteProposals('pending')),
          readJson(getMemoryRecallRuns()),
          readJson(listPersonalWorkflowRuns(8)),
          readJson(listWorkflowRecovery(8)),
        ])
        if (cancelled) return
        setWorkbench({
          metrics: null,
          memoryProposals: extractItems(proposals, ['proposals', 'items', 'decisions']),
          recallRuns: extractItems(recalls, ['runs', 'items']),
          workflowRuns: extractItems(workflowRuns, ['runs', 'items']),
          recoveryItems: extractItems(recovery, ['items', 'runs', 'recoveries']),
        })
      } catch (error) {
        if (!cancelled) console.error(error)
      }
    }

    fetchWorkbench()
    const interval = window.setInterval(fetchWorkbench, chatRunning ? 15000 : 60000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [chatRunning, user])

  const currentTreeId = tree?.tree_id || tree?.id
  const nodes = normalizeNodes(tree, t)
  const isActive = ['running', 'active', 'pending'].includes(String(tree?.status || '').toLowerCase())
  const activeHistoryId = selectedTreeId || currentTreeId
  const summary = useMemo(
    () => summarizeWorkbench(tree, nodes, workbench, isActive, chatRunning, t),
    [tree, nodes, workbench, isActive, chatRunning, t],
  )

  const handleStop = async () => {
    if (currentTreeId) {
      await stopReasoningTree(currentTreeId, 'User stopped via UI')
      setTree((prev: any) => ({ ...prev, status: 'stopped' }))
    }
  }

  const handleSteer = async () => {
    if (currentTreeId && steerNote.trim()) {
      await steerReasoningTree(currentTreeId, steerNote.trim())
      setSteerNote('')
    }
  }

  return (
    <aside className="relative flex h-full w-[322px] shrink-0 flex-col overflow-hidden rounded-[1.35rem] glass-panel">
      <div className="z-10 flex shrink-0 items-center justify-between border-b border-white/55 bg-bg-card/58 px-5 py-4 backdrop-blur-md">
        <h2 className="flex items-baseline gap-2 font-display text-[19px] font-semibold tracking-[-0.035em] text-text-strong">
          {t('任务工作台', 'Workbench')}
          <span className="font-sans text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">Agent</span>
        </h2>
        <div className="flex items-center gap-1 rounded-full bg-brand-100 px-2.5 py-1 text-[11px] font-semibold text-brand-700">
          <span className={`h-1.5 w-1.5 rounded-full bg-brand-600 ${summary.live ? 'animate-pulse' : ''}`} />
          {summary.statusLabel}
        </div>
      </div>

      <div className="z-10 border-b border-white/45 bg-bg-card/44 px-4 py-3">
        <div className="mb-3 grid grid-cols-3 gap-2">
          <WorkbenchMetric icon={<Target size={13} />} label={t('任务', 'Task')} value={summary.taskState} active={summary.live} />
          <WorkbenchMetric icon={<Wrench size={13} />} label={t('工具', 'Tools')} value={String(summary.toolNodes.length)} />
          <WorkbenchMetric icon={<AlertCircle size={13} />} label={t('待处理', 'Review')} value={String(summary.reviewCount)} active={summary.reviewCount > 0} />
        </div>
        <button
          type="button"
          onClick={() => setHistoryOpen((value) => !value)}
          className="flex w-full items-center justify-between rounded-xl border border-white/60 bg-bg-card/70 px-3 py-2 text-left text-xs font-semibold text-text-strong shadow-sm transition-colors hover:bg-white/70"
        >
          <span>{t('本轮运行记录', 'Run history')}</span>
          <span className="font-mono text-[10px] text-text-muted">{history.length}</span>
        </button>
        {historyOpen && (
          <div className="mt-2 max-h-44 overflow-y-auto rounded-xl border border-white/55 bg-bg-card/78 p-1.5 shadow-sm">
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
                    className={`mb-1 w-full rounded-lg px-2.5 py-2 text-left text-[11px] transition-colors last:mb-0 ${
                      selected ? 'bg-brand-100 text-brand-800' : 'text-text-normal hover:bg-white/65'
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

      <div className="pointer-events-none absolute left-0 top-20 bottom-20 w-32 opacity-25" style={{
        backgroundImage: 'radial-gradient(circle at 0 50%, rgba(112,111,104,0.55) 0%, transparent 70%)',
        filter: 'blur(22px)',
      }} />

      <div className="relative z-10 flex-1 overflow-y-auto p-5">
        <div className="flex flex-col gap-4">
          <section className="rounded-[1.15rem] border border-white/65 bg-bg-card/74 p-4 shadow-sm">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                <ListChecks size={14} className="text-brand-600" />
                {t('当前任务', 'Current work')}
              </div>
              {currentTreeId && <span className="rounded bg-brand-100 px-1.5 py-0.5 font-mono text-[10px] text-brand-700">{String(currentTreeId).slice(0, 6)}</span>}
            </div>
            <h3 className="text-[15px] font-semibold leading-snug text-text-strong">{summary.title}</h3>
            <p className="mt-2 text-xs leading-6 text-text-muted">{summary.currentStep}</p>
            <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] font-medium">
              <span className="rounded-full bg-brand-100 px-2 py-0.5 text-brand-700">{summary.phaseLabel}</span>
              <span className={`rounded-full px-2 py-0.5 ${summary.live ? 'bg-brand-100 text-brand-700' : 'bg-bg-page text-text-muted'}`}>{summary.statusLabel}</span>
              <span className="rounded-full bg-bg-page px-2 py-0.5 text-text-muted">{nodes.length} {t('步骤', 'steps')}</span>
              <span className="rounded-full bg-bg-page px-2 py-0.5 text-text-muted">{summary.completedSteps} {t('完成', 'done')}</span>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-3">
            <WorkbenchCard
              icon={<Wrench size={15} />}
              label={t('工具活动', 'Tool activity')}
              value={summary.toolSummary}
              meta={summary.latestTool}
            />
            <WorkbenchCard
              icon={<Database size={15} />}
              label={t('记忆活动', 'Memory activity')}
              value={summary.memorySummary}
              meta={summary.memoryMeta}
            />
            <WorkbenchCard
              icon={<GitBranch size={15} />}
              label={t('工作流活动', 'Workflow activity')}
              value={summary.workflowSummary}
              meta={summary.workflowMeta}
            />
          </div>

          {!tree && (
            <div className="rounded-[1.15rem] border border-dashed border-white/70 bg-bg-card/52 p-5 text-center">
              <Info size={30} className="mx-auto mb-2 text-brand-300" />
              <p className="text-sm font-semibold text-brand-700">
                {chatRunning ? t('等待运行态', 'Waiting for state') : t('空闲', 'Idle')}
              </p>
              <p className="mt-1 text-xs leading-6 text-text-muted">
                {chatRunning ? t('等待可观察步骤。', 'Waiting for observable steps.') : t('任务开始后显示进展。', 'Progress appears when work starts.')}
              </p>
            </div>
          )}

          {nodes.length > 0 && (
            <div className="relative pt-2">
              <div className="absolute left-[12px] top-4 bottom-2 w-px bg-brand-100" />
              <div className="mb-3 ml-10 text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                {t('执行时间线', 'Execution timeline')}
              </div>
              <div className="flex flex-col gap-5">
                {nodes.map((node, index) => (
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
                        ? <CheckCircle2 size={13} />
                        : <CircleDot size={13} className={index === nodes.length - 1 && summary.live ? 'animate-pulse' : ''} />
                    }
                    status={node.nodeStatus === 'running' || (index === nodes.length - 1 && summary.live) ? 'active' : 'done'}
                  />
                ))}
              </div>
            </div>
          )}

          {tree && nodes.length === 0 && (
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

      <div className="z-10 shrink-0 border-t border-white/55 bg-bg-card/78 p-4 backdrop-blur-xl">
        <h3 className="mb-3 flex items-center justify-between text-xs font-semibold text-text-strong">
          <span className="flex items-center gap-2">
            {t('任务干预', 'Task intervention')}
            <span className="text-[10px] font-normal text-text-muted">Control</span>
          </span>
          {currentTreeId && <span className="rounded bg-brand-100 px-1.5 py-0.5 font-mono text-[10px] text-brand-700">{String(currentTreeId).slice(0, 6)}</span>}
        </h3>

        {tree && summary.live && (
          <div className="mb-3 flex flex-col gap-2">
            <div className="flex gap-2">
              <input
                type="text"
                value={steerNote}
                onChange={(e) => setSteerNote(e.target.value)}
                placeholder={t('给当前任务一个方向...', 'Steer the current task...')}
                className="flex-1 rounded-lg border border-white/70 bg-bg-card px-3 py-1.5 text-xs outline-none focus:ring-1 focus:ring-brand-500"
              />
              <button
                type="button"
                onClick={handleSteer}
                disabled={!steerNote.trim()}
                className="rounded-lg bg-brand-100 px-3 py-1.5 text-xs font-semibold text-brand-700 hover:bg-brand-200 disabled:opacity-50"
              >
                {t('引导', 'Steer')}
              </button>
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={handleStop}
          disabled={!tree || !summary.live}
          className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs font-medium text-red-600 shadow-sm transition-colors hover:bg-red-100 disabled:grayscale disabled:opacity-50"
        >
          <Square size={14} />
          {t('停止任务', 'Stop task')}
        </button>
      </div>
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
  snapshot: WorkbenchSnapshot,
  isActive: boolean,
  chatRunning: boolean,
  t: (zh: string, en: string) => string,
) {
  const latest = nodes[nodes.length - 1]
  const rootGoal = String(tree?.root_goal || tree?.goal || '').trim()
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
    live,
    taskState,
    statusLabel,
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

function WorkbenchMetric({
  icon,
  label,
  value,
  active = false,
}: {
  icon: ReactNode
  label: string
  value: string
  active?: boolean
}) {
  return (
    <div className={`rounded-xl border px-2.5 py-2 shadow-sm ${active ? 'border-brand-100 bg-brand-50 text-brand-700' : 'border-white/60 bg-bg-card/70 text-text-normal'}`}>
      <div className="mb-1 flex items-center gap-1.5 text-[10px] text-text-muted">
        {icon}
        <span>{label}</span>
      </div>
      <div className="truncate text-xs font-semibold" title={value}>{value}</div>
    </div>
  )
}

function WorkbenchCard({
  icon,
  label,
  value,
  meta,
}: {
  icon: ReactNode
  label: string
  value: string
  meta: string
}) {
  return (
    <section className="rounded-[1.15rem] border border-white/62 bg-bg-card/64 p-3 shadow-sm">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">
          <span className="text-brand-600">{icon}</span>
          <span className="truncate">{label}</span>
        </div>
        <span className="shrink-0 rounded-full bg-bg-page px-2 py-0.5 text-[10px] font-medium text-text-muted">{meta}</span>
      </div>
      <p className="line-clamp-4 text-xs leading-6 text-text-normal">{value}</p>
    </section>
  )
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

async function readJson(responsePromise: Promise<Response>): Promise<any | null> {
  try {
    const response = await responsePromise
    if (!response.ok) return null
    return await response.json().catch(() => null)
  } catch {
    return null
  }
}

function extractItems(data: any, keys: string[]): any[] {
  if (Array.isArray(data)) return data
  if (!data || typeof data !== 'object') return []
  for (const key of keys) {
    const value = data[key]
    if (Array.isArray(value)) return value
  }
  return []
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
  return (
    <div className="relative pl-10 opacity-100">
      <div className={`absolute left-0 top-1 z-10 flex h-6 w-6 items-center justify-center rounded-full border bg-bg-card shadow-sm ${
        status === 'active' ? 'border-brand-500 shadow-[0_0_12px_rgba(94,90,83,0.28)]' : 'border-brand-100 text-xs font-bold text-brand-600'
      }`}>
        {icon}
      </div>
      <div className="rounded-2xl border border-white/55 bg-bg-card/70 p-3 shadow-sm">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h4 className={`min-w-0 flex-1 text-[13px] font-semibold leading-snug ${status === 'active' ? 'text-brand-700' : 'text-text-strong'}`}>
            {title}
          </h4>
          <span className="shrink-0 font-mono text-[10px] text-text-muted">{time}</span>
        </div>
        <div className="mb-2 flex gap-1.5 text-[10px] font-medium text-text-muted">
          <span className="rounded-full bg-bg-page px-2 py-0.5">{kind}</span>
          <span className="rounded-full bg-bg-page px-2 py-0.5">{statusLabel || status}</span>
        </div>
        <p className="line-clamp-4 text-xs leading-relaxed text-text-muted">{desc}</p>
      </div>
    </div>
  )
}
