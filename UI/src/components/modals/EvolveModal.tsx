import { useEffect, useState } from 'react'
import { createSelfEvolveTask, getSelfEvolveStatus, refreshSelfEvolveSelfModel } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import ResultCard from './settings/ResultCard'

export default function EvolveModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<any>({})
  const [goal, setGoal] = useState('')
  const [capabilityId, setCapabilityId] = useState('')
  const [command, setCommand] = useState('')
  const [result, setResult] = useState<unknown>(null)
  const { t } = useLanguage()

  useEffect(() => {
    getSelfEvolveStatus().then((res) => res.json()).then(setStatus).catch(() => {})
  }, [])

  const evolve = status?.self_evolve || {}
  const profile = evolve?.profile || {}
  const stats = evolve?.task_stats || {}
  const byStatus = stats?.by_status || {}
  const enabled = Boolean(evolve?.enabled)
  const selfModel = evolve?.self_model || {}
  const freshness = selfModel?.freshness || {}

  const reloadStatus = () => {
    getSelfEvolveStatus().then((res) => res.json()).then(setStatus).catch(() => {})
  }

  const createTask = async () => {
    if (!goal.trim()) return
    if (!capabilityId.trim() || !command.trim()) return
    const data = await createSelfEvolveTask({
      goal: goal.trim(),
      capability_id: capabilityId.trim(),
      version: '1.0.0',
      description: goal.trim(),
      commands: [{ command: command.trim(), description: goal.trim(), test_args: {} }],
      acceptance_criteria: [],
    })
      .then((res) => res.json())
    setResult(data)
    reloadStatus()
  }

  const refreshSelfModel = async () => {
    const data = await refreshSelfEvolveSelfModel().then((res) => res.json())
    setResult(data)
    reloadStatus()
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[800px] max-h-[80vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong flex items-center gap-2">
            {t('自我进化实验室', 'Self Evolution Lab')}
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded">{t('实验性', 'Experimental')}</span>
          </h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="flex-1 p-6 overflow-y-auto grid grid-cols-2 gap-6 bg-bg-page">
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm">
            <h3 className="font-semibold text-text-strong mb-4">{t('模块状态', 'Module Status')}</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatusPill label={t('启用状态', 'Enabled')} value={enabled ? t('已开启', 'Enabled') : t('未开启', 'Disabled')} tone={enabled ? 'ok' : 'warn'} />
              <StatusPill label={t('核心能力', 'Core Capability')} value={profile.core_capability || '-'} />
              <StatusPill label={t('任务总数', 'Total Tasks')} value={String(stats.total ?? 0)} />
              <StatusPill label={t('最大列表', 'List Limit')} value={String(profile.max_tasks_list ?? '-')} />
            </div>
            {evolve.notice && <p className="mt-3 rounded-lg bg-orange-50 px-3 py-2 text-xs leading-5 text-orange-700">{String(evolve.notice)}</p>}
          </div>
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="font-semibold text-text-strong">{t('自我模型', 'Self Model')}</h3>
              <button type="button" onClick={refreshSelfModel} disabled={!enabled} className="rounded-lg bg-brand-100 px-3 py-1.5 text-xs font-semibold text-brand-700 disabled:opacity-50">
                {t('刷新', 'Refresh')}
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <StatusPill label={t('存在状态', 'Exists')} value={selfModel.exists ? t('已生成', 'Generated') : t('未生成', 'Missing')} tone={selfModel.exists ? 'ok' : 'warn'} />
              <StatusPill label={t('新鲜度', 'Freshness')} value={freshness.stale ? t('可能过期', 'Possibly stale') : t('当前有效', 'Current')} tone={freshness.stale ? 'warn' : 'ok'} />
              <StatusPill label={t('能力域', 'Capability Areas')} value={Array.isArray(selfModel.capability_areas) ? String(selfModel.capability_areas.length) : '-'} />
              <StatusPill label={t('改进项', 'Backlog')} value={String(selfModel.backlog_count ?? '-')} />
              <StatusPill label={t('模型位置', 'Model Path')} value={selfModel.path || '-'} wide />
            </div>
          </div>
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm col-span-2">
            <h3 className="font-semibold text-text-strong mb-4">{t('任务审计', 'Task Audit')}</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatusPill label={t('存储位置', 'Store Path')} value={evolve.store_path || '-'} wide />
              {Object.keys(byStatus).length > 0 ? (
                Object.entries(byStatus).map(([key, value]) => (
                  <StatusPill key={key} label={key} value={String(value)} />
                ))
              ) : (
                <p className="text-text-muted">{t('暂无进化任务。', 'No evolution tasks yet.')}</p>
              )}
            </div>
          </div>
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm col-span-2">
            <h3 className="font-semibold text-text-strong mb-3">{t('创建进化任务', 'Create Evolution Task')}</h3>
            <div className="flex gap-2">
              <input
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                placeholder={t('描述一个经过确认的改进方向...', 'Describe an approved improvement direction...')}
                className="flex-1 px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
              <input
                value={capabilityId}
                onChange={(event) => setCapabilityId(event.target.value)}
                placeholder={t('能力 ID', 'Capability ID')}
                className="w-40 px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
              <input
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder={t('命令', 'Command')}
                className="w-40 px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
              />
              <button type="button" onClick={createTask} className="px-4 py-2 bg-brand-500 text-white rounded-lg text-sm font-medium">
                {t('创建', 'Create')}
              </button>
            </div>
            {!enabled && (
              <p className="mt-3 rounded-lg bg-orange-50 px-3 py-2 text-xs leading-5 text-orange-700">
                {t('Self Evolve 未开启。', 'Self Evolve is disabled.')}
              </p>
            )}
            <div className="mt-3">
              <ResultCard payload={result} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusPill({ label, value, tone = 'neutral', wide = false }: { label: string; value: string; tone?: 'neutral' | 'ok' | 'warn'; wide?: boolean }) {
  const toneClass = tone === 'ok'
    ? 'bg-emerald-50 text-emerald-800'
    : tone === 'warn'
      ? 'bg-orange-50 text-orange-800'
      : 'bg-bg-page text-text-strong'
  return (
    <div className={`${wide ? 'col-span-2' : ''} rounded-lg px-3 py-2 ${toneClass}`}>
      <div className="mb-1 text-[11px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="break-words font-medium">{value}</div>
    </div>
  )
}
