import { useEffect, useState } from 'react'
import { ArrowUpRight, CheckCircle2, ChevronRight, CircleDot, ListTodo, MessageSquare, Pause, Play, RefreshCw, Square } from 'lucide-react'
import { cancelTask, confirmTask, listSessions, listTasks, pauseTask, resumeTask } from '../services/api'
import type { Session, Task } from '../services/api'
import { useLanguage } from '../store/LanguageContext'
import { taskStatusLabel } from '../utils/task-presentation'
import { useEnvironmentObservation } from '../hooks/useEnvironmentObservation'
import MessageContent from './MessageContent'

type Props = { onObserve: (task: Task, runId?: string) => void; onOpenSession: (id: string) => void }
const TASK_STATUSES = ['open', 'running', 'paused', 'waiting_user', 'completed', 'failed', 'cancelled']

export default function TasksPage({ onObserve, onOpenSession }: Props) {
  const { t, lang } = useLanguage()
  const [tasks, setTasks] = useState<Task[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [controlError, setControlError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [reply, setReply] = useState('')
  const selected = tasks.find((task) => task.task_id === selectedId)
  const pendingRun = selected?.runs?.find((run) => run.pending_confirmation || run.input_request)
  const output = selected?.runs?.slice().reverse().find((run) => run.output)?.output
  const observe = useEnvironmentObservation('tasks', selected ? [{ kind: 'task', id: selected.task_id }] : [])
  const label = (value: string) => taskStatusLabel(value, value, t)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const rows = await listTasks(controller.signal)
        if (!controller.signal.aborted) { setTasks(rows); setError('') }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 15000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [revision])

  useEffect(() => {
    const controller = new AbortController()
    listSessions(controller.signal).then((rows) => {
      if (!controller.signal.aborted) setSessions(rows)
    }).catch(() => { /* Task monitoring stays available without conversation titles. */ })
    return () => controller.abort()
  }, [])

  const update = async (operation: () => Promise<Task>) => {
    if (busy) return
    setBusy(true)
    setControlError('')
    try {
      const task = await operation()
      setTasks((rows) => rows.map((row) => row.task_id === task.task_id && row.revision <= task.revision ? task : row))
      setRevision((value) => value + 1)
    } catch (cause) {
      setControlError(cause instanceof Error ? cause.message : String(cause))
      setRevision((value) => value + 1)
    } finally { setBusy(false) }
  }
  const control = async (action: 'pause' | 'resume' | 'cancel') => {
    if (!selected) return
    if (action === 'cancel' && !window.confirm(t('停止此任务？', 'Stop this task?'))) return
    await update(() => action === 'pause' ? pauseTask(selected.task_id, selected.revision)
      : action === 'resume' ? resumeTask(selected.task_id, selected.revision)
        : cancelTask(selected.task_id, 'user_cancelled', selected.revision))
  }
  const visible = tasks.filter((task) => (status === 'all' || task.status === status)
    && `${task.title} ${task.objective || ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const date = (value?: string | null) => value ? new Date(value).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : ''

  return <section ref={observe} className="tasks-page" aria-label={t('任务', 'Tasks')}>
    <header className="page-heading">
      <div><ListTodo size={19} /><h1>{t('任务', 'Tasks')}</h1><span>{tasks.length}</span></div>
      <button type="button" className="icon-button" title={t('刷新', 'Refresh')} aria-label={t('刷新', 'Refresh')}
        onClick={() => setRevision((value) => value + 1)}><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /></button>
    </header>
    <div className="page-toolbar">
      <input aria-label={t('搜索任务', 'Search tasks')} placeholder={t('搜索任务', 'Search tasks')}
        value={query} onChange={(event) => setQuery(event.target.value)} />
      <select aria-label={t('任务状态', 'Task status')} value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="all">{t('全部状态', 'All statuses')}</option>
        {TASK_STATUSES.map((value) => <option key={value} value={value}>{label(value)}</option>)}
      </select>
    </div>
    {(error || controlError) && <div role="alert" className="page-error">
      <span>{controlError || error}</span>
      <button type="button" onClick={() => { setControlError(''); setRevision((value) => value + 1) }}>{t('刷新状态', 'Refresh state')}</button>
    </div>}
    <div className={`task-columns ${selectedId ? 'has-selection' : ''}`}>
      <div className="task-list">
        {visible.map((task) => <button type="button" key={task.task_id}
          className={`task-row ${selectedId === task.task_id ? 'is-selected' : ''}`}
          onClick={() => { setSelectedId(task.task_id); setControlError(''); setReply('') }}>
          {task.status === 'completed' ? <CheckCircle2 size={17} /> : <CircleDot size={17} />}
          <span><strong>{task.title}</strong><small>{label(task.status)} · {date(task.updated_at)}</small></span>
        </button>)}
        {!visible.length && !error && <div className="empty-state"><ListTodo size={24} />
          <span>{loading ? t('正在加载', 'Loading') : query || status !== 'all' ? t('没有匹配任务', 'No matching tasks') : t('暂无任务', 'No tasks')}</span>
        </div>}
      </div>
      {selectedId && <section className="task-detail">
        <div className="task-detail-heading"><span>{selected ? label(selected.status) : ''}</span>
          <button type="button" className="text-button" onClick={() => setSelectedId('')}>{t('返回列表', 'Back to list')}</button>
        </div>
        {selected ? <>
          <h2>{selected.title}</h2>
          {selected.objective && <p className="task-objective">{selected.objective}</p>}
          {output && !pendingRun && <section>
            <h3>{t('结果', 'Result')}</h3>
            <div className="whitespace-pre-wrap break-words text-sm"><MessageContent content={output} followups={[]} /></div>
          </section>}
          {pendingRun?.pending_confirmation && <section>
            <h3>{t('等待批准', 'Awaiting approval')}</h3>
            <div className="break-words text-sm">{pendingRun.pending_confirmation.tool_name}</div>
            <pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(pendingRun.pending_confirmation.arguments, null, 2)}</pre>
            <div className="task-actions">{(['reject', 'approve'] as const).map((action) => <button type="button" key={action}
              className={action === 'approve' ? 'primary-button' : 'secondary-button'} disabled={busy}
              onClick={() => void update(() => confirmTask(selected.task_id, pendingRun.run_id, pendingRun.pending_confirmation!.tool_call_id, action))}>
              {action === 'approve' ? t('批准', 'Approve') : t('拒绝', 'Reject')}
            </button>)}</div>
          </section>}
          {pendingRun?.input_request && <section>
            <h3>{t('等待回复', 'Awaiting reply')}</h3>
            <p className="break-words text-sm">{pendingRun.input_request.content}</p>
            {pendingRun.input_request.input_kind === 'text' && <textarea value={reply} maxLength={16000}
              aria-label={t('回复任务', 'Reply to task')} onChange={(event) => setReply(event.target.value)} />}
            <button type="button" className="primary-button" disabled={busy || (pendingRun.input_request.input_kind === 'text' && !reply.trim())}
              onClick={() => void update(() => resumeTask(selected.task_id, selected.revision, pendingRun.input_request?.input_kind === 'text'
                ? { request_id: pendingRun.input_request.request_id, content: reply.trim() } : undefined))}>
              {pendingRun.input_request.input_kind === 'text' ? t('发送回复', 'Send reply') : t('继续', 'Resume')}
            </button>
          </section>}
          {selected.goal_progress && <section aria-label={t('目标进度', 'Goal progress')}>
            <h3>{t('目标进度', 'Goal progress')}</h3>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
              <span>{t('已验证', 'Verified')} {selected.goal_progress.checks_passed ?? 0} / {selected.goal_progress.tracked ?? 0}</span>
              <span>{t('待完成', 'Open')} {selected.goal_progress.open ?? 0}</span>
              <span>{t('受阻', 'Blocked')} {selected.goal_progress.blocked ?? 0}</span>
            </div>
            <ul className="mt-2 space-y-2 text-sm">
              {(selected.goal_gaps?.gaps || []).map((gap) => <li key={gap.id} className="flex items-start gap-2">
                {gap.support === 'checked' && gap.state === 'resolved' ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> : <CircleDot size={15} className="mt-0.5 shrink-0" />}
                <span className="min-w-0 break-words">{gap.requirement}<small className="ml-2 text-text-muted">{gap.state === 'blocked' ? t('受阻', 'Blocked') : gap.state === 'resolved' && gap.support === 'checked' ? t('已验证', 'Verified') : t('未验证', 'Unverified')}</small></span>
              </li>)}
            </ul>
          </section>}
          <div className="task-actions">
            <button type="button" className="primary-button" onClick={() => onObserve(selected)}>
              <ArrowUpRight size={14} />{t('在工作台观察', 'Observe in workbench')}
            </button>
            {['running', 'paused'].includes(selected.status) && <button type="button" className="secondary-button" disabled={busy}
              onClick={() => void control(selected.status === 'paused' ? 'resume' : 'pause')}>
              {selected.status === 'paused' ? <Play size={13} /> : <Pause size={13} />}
              {selected.status === 'paused' ? t('继续', 'Resume') : t('暂停', 'Pause')}
            </button>}
            {['running', 'paused', 'waiting_user'].includes(selected.status) && <button type="button" className="secondary-button danger"
              disabled={busy} onClick={() => void control('cancel')}><Square size={12} />{t('停止', 'Stop')}</button>}
          </div>
          {!!selected.session_ids?.length && <section>
            <h3>{t('相关对话', 'Conversations')}</h3>
            {selected.session_ids.map((id) => <button type="button" key={id} className="workbench-reference" onClick={() => onOpenSession(id)}>
              <MessageSquare size={14} /><span>{sessions.find((session) => session.session_id === id)?.title || t('打开对话', 'Open conversation')}</span><ArrowUpRight size={13} />
            </button>)}
          </section>}
          <section>
            <h3>{t('运行记录', 'Runs')}</h3>
            {(selected.runs || []).map((run, index) => <button type="button" key={run.run_id} className="task-run"
              aria-label={t(`查看运行 ${index + 1}`, `View run ${index + 1}`)} onClick={() => onObserve(selected, run.run_id)}>
              <span>{t('运行', 'Run')} {index + 1}</span><span>{label(run.status)}</span><time>{date(run.started_at)}</time><ChevronRight size={13} />
            </button>)}
            {!selected.runs?.length && <p className="text-text-muted text-xs">{t('暂无运行记录', 'No runs')}</p>}
          </section>
        </> : <div className="empty-state">{loading ? t('正在加载', 'Loading') : t('此任务已不在当前列表中', 'This task is no longer in the current list')}</div>}
      </section>}
    </div>
  </section>
}
