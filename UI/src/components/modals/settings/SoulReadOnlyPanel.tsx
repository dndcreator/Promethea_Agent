import { useState } from 'react'
import { getSoulConfig, readApiResponse } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'

export default function SoulReadOnlyPanel() {
  const { t } = useLanguage()
  const [soul, setSoul] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setBusy(true); setError('')
    try { const data = await getSoulConfig().then(readApiResponse); setSoul(data.soul || data) }
    catch { setError(t('加载失败', 'Could not load soul style')) }
    finally { setBusy(false) }
  }

  return (
    <section className="mt-4 flex flex-col gap-3 border-t border-black/5 pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-text-strong">{t('灵魂风格（只读）', 'Soul Style (Read-only)')}</h3>
        <button type="button" disabled={busy} onClick={load} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{busy ? t('正在加载', 'Loading') : t('查看', 'View')}</button>
      </div>
      {soul && <div className="soul-readonly"><div className="flex flex-wrap gap-3 text-xs text-text-muted"><span>{soul.enabled ? t('已启用', 'Enabled') : t('未启用', 'Disabled')}</span>{soul.version !== undefined && <span>{t('版本', 'Version')} {soul.version}</span>}{soul.updated_at && <time>{new Date(soul.updated_at).toLocaleString()}</time>}</div><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-relaxed">{soul.content || t('暂无内容', 'No content')}</p>{soul.last_reason && <details className="operation-details"><summary>{t('最近更新', 'Latest update')}</summary><p>{soul.last_reason}</p></details>}</div>}
      {error && <div role="alert" className="text-xs text-red-600">{error}</div>}
    </section>
  )
}
