import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, RefreshCw, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { getWorkflowCheckpoints, getWorkflowRun, listPersonalWorkflowRuns, listWorkflowRecovery, listWorkflows, pauseWorkflowRun, resumeWorkflowRun } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import FeatureSurface from '../FeatureSurface'
import { readApiResponse } from '../../services/api'

type Tab = 'definitions' | 'runs' | 'recovery'

type WorkflowRow = {
  id?: string
  workflow_id?: string
  workflow_run_id?: string
  run_id?: string
  name?: string
  status?: string
  workflow_type?: string
  description?: string
  checkpoints?: unknown
  steps?: unknown
  [key: string]: unknown
}

export default function WorkflowsModal({ onClose, embedded = false }: { onClose: () => void; embedded?: boolean }) {
  const { t } = useLanguage()
  const [tab, setTab] = useState<Tab>('runs')
  const [definitions, setDefinitions] = useState<WorkflowRow[]>([])
  const [runs, setRuns] = useState<WorkflowRow[]>([])
  const [recovery, setRecovery] = useState<WorkflowRow[]>([])
  const [detail, setDetail] = useState<WorkflowRow | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const epoch = useRef(0)
  const detailEpoch = useRef(0)

  const refresh = async (nextTab = tab) => {
    const current = ++epoch.current
    setLoading(true)
    setError('')
    try {
      if (nextTab === 'definitions') {
        const data = await listWorkflows().then(readApiResponse)
        if (current !== epoch.current) return
        setDefinitions(data.workflows || data.items || [])
      } else if (nextTab === 'recovery') {
        const data = await listWorkflowRecovery().then(readApiResponse)
        if (current !== epoch.current) return
        setRecovery(data.runs || [])
      } else {
        const data = await listPersonalWorkflowRuns().then(readApiResponse)
        if (current !== epoch.current) return
        setRuns(data.runs || [])
      }
    } catch (cause) {
      if (current === epoch.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (current === epoch.current) setLoading(false)
    }
  }

  useEffect(() => {
    setDetail(null)
    setBusy(false)
    void refresh(tab)
    return () => { epoch.current += 1; detailEpoch.current += 1 }
  }, [tab])

  const openRun = async (runId: string) => {
    const current = ++detailEpoch.current
    try {
      const data = await getWorkflowRun(runId).then(readApiResponse)
      if (current === detailEpoch.current) setDetail(data.run || data)
    } catch (cause) { if (current === detailEpoch.current) setError(String(cause)) }
  }

  const action = async (runId: string, kind: 'pause' | 'resume') => {
    const current = detailEpoch.current
    setBusy(true)
    try {
      await (kind === 'pause' ? pauseWorkflowRun(runId) : resumeWorkflowRun(runId)).then(readApiResponse)
      if (current !== detailEpoch.current) return
      await refresh(tab)
      if (current === detailEpoch.current) await openRun(runId)
    } catch (cause) { if (current === detailEpoch.current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }

  const openCheckpoints = async (runId: string) => {
    const current = detailEpoch.current
    try {
      const data = await getWorkflowCheckpoints(runId).then(readApiResponse)
      if (current === detailEpoch.current) setDetail((prev) => ({ ...(prev || { workflow_run_id: runId }), checkpoints: data.checkpoints || data }))
    } catch (cause) { if (current === detailEpoch.current) setError(String(cause)) }
  }

  const rows = tab === 'definitions' ? definitions : tab === 'recovery' ? recovery : runs

  return (
    <FeatureSurface embedded={embedded} onClose={onClose} label={t('工作流', 'Workflows')}>
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('工作流', 'Workflows')}</h2>
          <button type="button" onClick={onClose} className="icon-button" title={t('关闭', 'Close')} aria-label={t('关闭', 'Close')}><X size={17} /></button>
        </div>

        <div className="flex border-b border-black/5 bg-white px-4 pt-2 gap-4">
          <TabButton active={tab === 'runs'} onClick={() => setTab('runs')}>{t('运行记录', 'Runs')}</TabButton>
          <TabButton active={tab === 'recovery'} onClick={() => setTab('recovery')}>{t('待恢复', 'Recovery')}</TabButton>
          <TabButton active={tab === 'definitions'} onClick={() => setTab('definitions')}>{t('定义', 'Definitions')}</TabButton>
          <button type="button" onClick={() => refresh()} className="ml-auto px-3 py-2 text-sm text-brand-600 hover:text-brand-700">
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} aria-label={t('刷新', 'Refresh')} />
          </button>
        </div>

        {error && <div role="alert" className="page-error"><span>{error}</span><button type="button" onClick={() => void refresh()}>{t('重试', 'Retry')}</button></div>}
        <div className="min-h-0 flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-[minmax(220px,35%)_1fr] bg-bg-page">
          <aside className={`border-r border-black/5 p-4 overflow-y-auto ${detail ? 'hidden lg:block' : ''}`}>
            <div className="flex flex-col gap-2">
              {rows.map((row) => {
                const runId = row.workflow_run_id || row.run_id || row.id
                const workflowId = row.workflow_id || row.id
                return (
                  <button
                    key={runId || workflowId}
                    type="button"
                    onClick={() => { if (tab !== 'definitions' && runId) void openRun(runId); else { detailEpoch.current += 1; setDetail(row) } }}
                    className="p-3 bg-white border border-black/5 rounded-xl text-left hover:border-brand-300"
                  >
                    <div className="text-sm font-semibold text-text-strong truncate">{row.name || workflowId || runId}</div>
                    <div className="text-xs text-text-muted truncate">{row.status || row.workflow_type || row.description || 'workflow'}</div>
                  </button>
                )
              })}
              {!loading && !error && rows.length === 0 && <div className="text-sm text-text-muted text-center mt-20">{t('暂无工作流数据。', 'No workflow data.')}</div>}
            </div>
          </aside>

          <section className={`p-5 overflow-y-auto ${detail ? '' : 'hidden lg:block'}`}>
            {detail && <button type="button" className="icon-button mb-3 lg:hidden" title={t('返回列表', 'Back to list')} aria-label={t('返回列表', 'Back to list')} onClick={() => { detailEpoch.current += 1; setDetail(null) }}><ArrowLeft size={16} /></button>}
            {typeof detail?.workflow_run_id === 'string' && (() => {
              const runId = detail.workflow_run_id
              return (
                <div className="flex gap-2 mb-4">
                  <button type="button" disabled={busy} onClick={() => action(runId, 'pause')} className="px-3 py-1.5 bg-gray-100 rounded-lg text-sm">{t('暂停', 'Pause')}</button>
                  <button type="button" disabled={busy} onClick={() => action(runId, 'resume')} className="px-3 py-1.5 bg-brand-50 text-brand-600 rounded-lg text-sm">{t('恢复', 'Resume')}</button>
                  <button type="button" onClick={() => openCheckpoints(runId)} className="px-3 py-1.5 bg-white border border-black/10 rounded-lg text-sm">{t('检查点', 'Checkpoints')}</button>
                </div>
              )
            })()}
            {detail ? <WorkflowDetail detail={detail} /> : <EmptyState>{t('选择一条工作流查看详情。', 'Select a workflow item to inspect.')}</EmptyState>}
          </section>
        </div>
    </FeatureSurface>
  )
}

function WorkflowDetail({ detail }: { detail: WorkflowRow }) {
  const { t } = useLanguage()
  const steps = Array.isArray(detail.steps) ? detail.steps : []
  const checkpoints = Array.isArray(detail.checkpoints) ? detail.checkpoints : []
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 text-xs">
        {[
          [t('名称', 'Name'), detail.name || detail.workflow_id || detail.workflow_run_id || detail.id || '-'],
          [t('状态', 'Status'), detail.status || '-'],
          [t('类型', 'Type'), detail.workflow_type || '-'],
          [t('运行 ID', 'Run ID'), detail.workflow_run_id || detail.run_id || '-'],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-xl bg-white p-3 shadow-sm">
            <dt className="mb-1 text-text-muted">{label}</dt>
            <dd className="break-words font-semibold text-text-strong">{String(value)}</dd>
          </div>
        ))}
      </dl>
      {detail.description && <p className="rounded-xl bg-white p-4 text-sm leading-7 text-text-normal shadow-sm">{String(detail.description)}</p>}
      <section className="rounded-xl bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-text-strong">{t('步骤', 'Steps')}</h3>
        <ItemList rows={steps} empty={t('暂无步骤。', 'No steps.')} />
      </section>
      <section className="rounded-xl bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-text-strong">{t('检查点', 'Checkpoints')}</h3>
        <ItemList rows={checkpoints} empty={t('暂无检查点。', 'No checkpoints.')} />
      </section>
    </div>
  )
}

function ItemList({ rows, empty }: { rows: any[]; empty: string }) {
  if (!rows.length) return <div className="text-sm text-text-muted">{empty}</div>
  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <div key={row.id || row.step_id || row.checkpoint_id || index} className="rounded-lg border border-black/5 bg-bg-page p-3 text-xs">
          <div className="mb-1 font-semibold text-text-strong">{row.name || row.step_id || row.checkpoint_id || `Item ${index + 1}`}</div>
          <div className="text-text-muted">{row.status || row.kind || row.created_at || row.updated_at || '-'}</div>
        </div>
      ))}
    </div>
  )
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-black/10 bg-white/70 p-6 text-center text-sm text-text-muted">{children}</div>
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        active ? 'border-brand-500 text-brand-600' : 'border-transparent text-text-muted hover:text-text-strong'
      }`}
    >
      {children}
    </button>
  )
}
