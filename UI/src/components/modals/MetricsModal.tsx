import { useEffect, useState } from 'react'
import { getMetrics, readApiResponse } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import FeatureSurface from '../FeatureSurface'
import { RefreshCw, X } from 'lucide-react'

export default function MetricsModal({ onClose, embedded = false }: { onClose: () => void; embedded?: boolean }) {
  const [metrics, setMetrics] = useState<any>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const { t } = useLanguage()

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getMetrics().then(readApiResponse).then((data) => { if (!cancelled) { setMetrics(data.metrics || data); setError('') } }).catch((cause) => { if (!cancelled) setError(String(cause)) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [revision])

  const llm = metrics.llm || {}
  const memory = metrics.memory || {}
  const sessions = metrics.sessions || {}
  const personal = metrics.personal || {}
  const system = metrics.system || {}
  const cost = metrics.cost || {}
  const totalCalls = llm.total_calls ?? llm.calls
  const averageLatency = llm.average_latency_ms ?? llm.avg_time_ms
  const estimatedCost = llm.estimated_cost ?? cost.estimated_usd
  const totalRecalls = memory.total_recalls ?? memory.recalls
  const averageRecall = memory.average_recall_time_ms ?? memory.avg_time_ms
  const messagesTotal = metrics.chat?.messages_total ?? sessions.messages
  const uptimeSeconds = system.uptime_seconds ?? metrics.uptime_seconds
  const numeric = (value: unknown, digits = 0) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-'

  return (
    <FeatureSurface embedded={embedded} onClose={onClose} label={t('系统指标', 'Metrics')}>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('系统指标', 'Metrics')}</h2>
          <div className="flex gap-2"><button type="button" disabled={loading} onClick={() => setRevision((value) => value + 1)} className="icon-button" title={t('刷新', 'Refresh')} aria-label={t('刷新', 'Refresh')}><RefreshCw size={15} /></button><button type="button" onClick={onClose} className="icon-button" title={t('关闭', 'Close')} aria-label={t('关闭', 'Close')}><X size={17} /></button></div>
        </div>
        {loading ? <div className="empty-state">{t('正在加载', 'Loading')}</div> : error ? <div role="alert" className="page-error"><span>{error}</span><button type="button" aria-label={t('重试', 'Retry')} onClick={() => setRevision((value) => value + 1)}><RefreshCw size={15} /></button></div> : <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <MetricCard label={t('Token 用量', 'Token Usage')} value={numeric(llm.total_tokens)} sub={`${t('输入', 'In')}: ${numeric(llm.prompt_tokens)} / ${t('输出', 'Out')}: ${numeric(llm.completion_tokens)}`} />
          <MetricCard label={t('估算成本', 'Estimated Cost')} value={typeof estimatedCost === 'number' ? `$${numeric(estimatedCost, 4)}` : '-'} sub={`${t('模型调用', 'Model calls')}: ${numeric(totalCalls)} · ${t('平均延迟', 'Average')}: ${numeric(averageLatency)} ms`} />
          <MetricCard label={t('记忆召回', 'Memory Recalls')} value={numeric(totalRecalls)} sub={`${t('平均耗时', 'Average')}: ${numeric(averageRecall)} ms · ${t('召回条数', 'Items')}: ${numeric(memory.items_recalled)}`} />
          <MetricCard label={t('会话 / 消息', 'Sessions / Messages')} value={`${numeric(personal.sessions_current)} / ${numeric(messagesTotal)}`} sub={`${t('运行时间', 'Uptime')}: ${numeric(uptimeSeconds)} s`} />
        </div>}
      </div>
    </FeatureSurface>
  )
}

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub: string }) {
  return (
    <div className="p-4 bg-gray-50 rounded-xl border border-black/5 flex flex-col gap-1">
      <div className="text-xs font-semibold text-text-muted uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold text-brand-600">{value}</div>
      <div className="text-[10px] text-text-muted">{sub}</div>
    </div>
  )
}
