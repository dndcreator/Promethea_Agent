import { useEffect, useRef, useState } from 'react'
import { Activity, RefreshCw, X } from 'lucide-react'
import { getDoctor, migrateConfig, readApiResponse } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import FeatureSurface from '../FeatureSurface'

export default function DoctorModal({ onClose, embedded = false }: { onClose: () => void; embedded?: boolean }) {
  const { t } = useLanguage()
  const [output, setOutput] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const epoch = useRef(0)
  const run = async (reload = false) => {
    const current = ++epoch.current
    setBusy(true); setError('')
    try {
      if (reload) await migrateConfig().then(readApiResponse)
      const data = await getDoctor().then(readApiResponse)
      if (current === epoch.current) setOutput(data)
    } catch { if (current === epoch.current) setError(t('诊断请求失败', 'Diagnostics request failed')) }
    finally { if (current === epoch.current) setBusy(false) }
  }
  useEffect(() => { void run(); return () => { epoch.current += 1 } }, [])
  const names: Record<string, string> = {
    config_api: t('模型接口', 'Model API'), memory: t('记忆服务', 'Memory'), plugins: t('插件', 'Plugins'),
    mcp: t('外部工具', 'External tools'), sessions: t('会话', 'Sessions'), metrics: t('运行指标', 'Metrics'),
    gateway: t('网关', 'Gateway'), environment: t('运行环境', 'Environment'),
  }
  const overall = output?.status === 'healthy' ? t('运行正常', 'Healthy') : output?.status === 'degraded' ? t('部分服务异常', 'Degraded') : output?.status === 'unhealthy' ? t('服务异常', 'Unhealthy') : t('暂无诊断结果', 'No diagnostic result')
  return <FeatureSurface embedded={embedded} onClose={onClose} label={t('系统诊断', 'Diagnostics')}>
    <header className="page-heading"><div><Activity size={19} /><h1>{t('系统诊断', 'Diagnostics')}</h1></div><button type="button" className="icon-button" onClick={onClose} aria-label={t('关闭', 'Close')} title={t('关闭', 'Close')}><X size={17} /></button></header>
    <div className="settings-actions p-4 border-b border-black/5"><button type="button" disabled={busy} className="secondary-button" onClick={() => void run()}><RefreshCw size={14} className={busy ? 'animate-spin' : ''} />{t('重新运行', 'Run again')}</button><button type="button" disabled={busy} className="secondary-button" onClick={() => void run(true)}>{t('重载配置', 'Reload config')}</button></div>
    {error && <div role="alert" className="page-error">{error}</div>}
    <div className="diagnostics-content overflow-y-auto p-4 sm:p-6">
      <h2 role="status" className="text-base font-semibold mb-4">{busy ? t('正在运行诊断', 'Running diagnostics') : overall}</h2>
      {Object.entries(output?.checks || {}).map(([key, value]) => {
        const check = value as { ok?: boolean; issues?: string[] }
        return <details key={key} className="diagnostic-row"><summary><span>{names[key] || key}</span><span className={check.ok === true ? 'text-emerald-700' : check.ok === false ? 'text-red-600' : 'text-text-muted'}>{check.ok === true ? t('正常', 'OK') : check.ok === false ? t('异常', 'Issue') : t('未知', 'Unknown')}</span></summary>{check.issues?.map((issue, index) => <p key={index} className="text-xs text-red-600 py-2 break-words">{issue}</p>)}<pre>{JSON.stringify(value, null, 2)}</pre></details>
      })}
      {output && <details className="operation-details mt-4"><summary>{t('完整诊断', 'Full diagnostic report')}</summary><pre>{JSON.stringify(output, null, 2)}</pre></details>}
    </div>
  </FeatureSurface>
}
