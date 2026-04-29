import { useEffect, useState } from 'react'
import { getMetrics } from '../../lib/api'
import { useLanguage } from '../../store/LanguageContext'

export default function MetricsModal({ onClose }: { onClose: () => void }) {
  const [metrics, setMetrics] = useState<any>({})
  const { t } = useLanguage()

  useEffect(() => {
    getMetrics().then((res) => res.json()).then((data) => setMetrics(data.metrics || data)).catch(() => {})
  }, [])

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[500px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('运行指标', 'Metrics')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-6 grid grid-cols-2 gap-4">
          <MetricCard label={t('Token 使用量', 'Token Usage')} value={metrics.llm?.total_tokens || 0} sub={`Est. Cost: $${(metrics.llm?.estimated_cost || 0).toFixed(4)}`} />
          <MetricCard label={t('LLM 调用', 'LLM Calls')} value={metrics.llm?.total_calls || 0} sub={`Avg: ${(metrics.llm?.average_latency_ms || 0).toFixed(0)}ms`} />
          <MetricCard label={t('记忆召回', 'Memory Recalls')} value={metrics.memory?.total_recalls || 0} sub={`Avg: ${(metrics.memory?.average_recall_time_ms || 0).toFixed(0)}ms`} />
          <MetricCard label={t('会话 / 消息', 'Sessions / Messages')} value={`${metrics.personal?.sessions_current || 0}/${metrics.chat?.messages_total || 0}`} sub={`Uptime: ${metrics.system?.uptime_seconds || 0}s`} />
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
