import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getWorkflowCheckpoints, getWorkflowRun, listPersonalWorkflowRuns, listWorkflowRecovery, listWorkflows, pauseWorkflowRun, resumeWorkflowRun } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'

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

export default function WorkflowsModal({ onClose }: { onClose: () => void }) {
  const { t } = useLanguage()
  const [tab, setTab] = useState<Tab>('runs')
  const [definitions, setDefinitions] = useState<WorkflowRow[]>([])
  const [runs, setRuns] = useState<WorkflowRow[]>([])
  const [recovery, setRecovery] = useState<WorkflowRow[]>([])
  const [detail, setDetail] = useState<WorkflowRow | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = async (nextTab = tab) => {
    setLoading(true)
    try {
      if (nextTab === 'definitions') {
        const data = await listWorkflows().then((res) => res.json())
        setDefinitions(data.workflows || data.items || [])
      } else if (nextTab === 'recovery') {
        const data = await listWorkflowRecovery().then((res) => res.json())
        setRecovery(data.runs || [])
      } else {
        const data = await listPersonalWorkflowRuns().then((res) => res.json())
        setRuns(data.runs || [])
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh(tab)
  }, [tab])

  const openRun = async (runId: string) => {
    const data = await getWorkflowRun(runId).then((res) => res.json())
    setDetail(data.run || data)
  }

  const action = async (runId: string, kind: 'pause' | 'resume') => {
    if (kind === 'pause') await pauseWorkflowRun(runId)
    if (kind === 'resume') await resumeWorkflowRun(runId)
    await refresh(tab)
  }

  const openCheckpoints = async (runId: string) => {
    const data = await getWorkflowCheckpoints(runId).then((res) => res.json())
    setDetail((prev) => ({ ...(prev || { workflow_run_id: runId }), checkpoints: data.checkpoints || data }))
  }

  const rows = tab === 'definitions' ? definitions : tab === 'recovery' ? recovery : runs

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[1100px] h-[78vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('工作流', 'Workflows')}</h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>

        <div className="flex border-b border-black/5 bg-white px-4 pt-2 gap-4">
          <TabButton active={tab === 'runs'} onClick={() => setTab('runs')}>{t('运行记录', 'Runs')}</TabButton>
          <TabButton active={tab === 'recovery'} onClick={() => setTab('recovery')}>{t('待恢复', 'Recovery')}</TabButton>
          <TabButton active={tab === 'definitions'} onClick={() => setTab('definitions')}>{t('定义', 'Definitions')}</TabButton>
          <button type="button" onClick={() => refresh()} className="ml-auto px-3 py-2 text-sm text-brand-600 hover:text-brand-700">
            {loading ? t('加载中...', 'Loading...') : t('刷新', 'Refresh')}
          </button>
        </div>

        <div className="flex-1 overflow-hidden grid grid-cols-[380px_1fr] bg-bg-page">
          <aside className="border-r border-black/5 p-4 overflow-y-auto">
            <div className="flex flex-col gap-2">
              {rows.map((row) => {
                const runId = row.workflow_run_id || row.run_id || row.id
                const workflowId = row.workflow_id || row.id
                return (
                  <button
                    key={runId || workflowId}
                    type="button"
                    onClick={() => (runId ? openRun(runId) : setDetail(row))}
                    className="p-3 bg-white border border-black/5 rounded-xl text-left hover:border-brand-300"
                  >
                    <div className="text-sm font-semibold text-text-strong truncate">{row.name || workflowId || runId}</div>
                    <div className="text-xs text-text-muted truncate">{row.status || row.workflow_type || row.description || 'workflow'}</div>
                  </button>
                )
              })}
              {rows.length === 0 && <div className="text-sm text-text-muted text-center mt-20">{t('暂无工作流数据。', 'No workflow data.')}</div>}
            </div>
          </aside>

          <section className="p-6 overflow-y-auto">
            {typeof detail?.workflow_run_id === 'string' && (() => {
              const runId = detail.workflow_run_id
              return (
                <div className="flex gap-2 mb-4">
                  <button type="button" onClick={() => action(runId, 'pause')} className="px-3 py-1.5 bg-gray-100 rounded-lg text-sm">{t('暂停', 'Pause')}</button>
                  <button type="button" onClick={() => action(runId, 'resume')} className="px-3 py-1.5 bg-brand-50 text-brand-600 rounded-lg text-sm">{t('恢复', 'Resume')}</button>
                  <button type="button" onClick={() => openCheckpoints(runId)} className="px-3 py-1.5 bg-white border border-black/10 rounded-lg text-sm">{t('检查点', 'Checkpoints')}</button>
                </div>
              )
            })()}
            {detail ? <WorkflowDetail detail={detail} /> : <EmptyState>{t('选择一条工作流查看详情。', 'Select a workflow item to inspect.')}</EmptyState>}
          </section>
        </div>
      </div>
    </div>
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
