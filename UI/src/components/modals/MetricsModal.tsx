import { useEffect, useState } from 'react'
import { getMetrics } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'

export default function MetricsModal({ onClose }: { onClose: () => void }) {
  const [metrics, setMetrics] = useState<any>({})
  const { t } = useLanguage()

  useEffect(() => {
    getMetrics().then((res) => res.json()).then((data) => setMetrics(data.metrics || data)).catch(() => {})
  }, [])

  const llm = metrics.llm || {}
  const memory = metrics.memory || {}
  const sessions = metrics.sessions || {}
  const personal = metrics.personal || {}
  const system = metrics.system || {}
  const cost = metrics.cost || {}
  const totalCalls = llm.total_calls ?? llm.calls ?? 0
  const averageLatency = llm.average_latency_ms ?? llm.avg_time_ms ?? 0
  const estimatedCost = llm.estimated_cost ?? cost.estimated_usd ?? 0
  const totalRecalls = memory.total_recalls ?? memory.recalls ?? 0
  const averageRecall = memory.average_recall_time_ms ?? memory.avg_time_ms ?? 0
  const messagesTotal = metrics.chat?.messages_total ?? sessions.messages ?? 0
  const uptimeSeconds = system.uptime_seconds ?? metrics.uptime_seconds ?? 0

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[500px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('系统指标', 'Metrics')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-6 grid grid-cols-2 gap-4">
          <MetricCard label={t('Token 用量', 'Token Usage')} value={llm.total_tokens || 0} sub={`${t('输入', 'In')}: ${llm.prompt_tokens || 0} / ${t('输出', 'Out')}: ${llm.completion_tokens || 0}`} />
          <MetricCard label={t('估算成本', 'Estimated Cost')} value={`$${Number(estimatedCost || 0).toFixed(4)}`} sub={`${t('LLM 调用', 'LLM Calls')}: ${totalCalls} · Avg: ${Number(averageLatency || 0).toFixed(0)}ms`} />
          <MetricCard label={t('记忆召回', 'Memory Recalls')} value={totalRecalls} sub={`Avg: ${Number(averageRecall || 0).toFixed(0)}ms · Items: ${memory.items_recalled || 0}`} />
          <MetricCard label={t('会话 / 消息', 'Sessions / Messages')} value={`${personal.sessions_current || 0}/${messagesTotal}`} sub={`Uptime: ${uptimeSeconds}s`} />
        </div>
      </div>
    </div>
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
