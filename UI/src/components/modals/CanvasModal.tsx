import { useEffect, useMemo, useState } from 'react'
import { MonitorPlay, RefreshCw, X } from 'lucide-react'

import { listCanvasEnvironments, type CanvasEnvironment } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'

export default function CanvasModal({ workspaceId, onClose }: { workspaceId?: string | null; onClose: () => void }) {
  const { t } = useLanguage()
  const resolvedWorkspace = workspaceId || 'default'
  const [environments, setEnvironments] = useState<CanvasEnvironment[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const result = await listCanvasEnvironments(resolvedWorkspace)
      setEnvironments(result.environments || [])
      setSelectedId((current) => current || result.environments?.[0]?.environment_id || '')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    setSelectedId('')
    void load()
    const timer = window.setInterval(load, 5000)
    return () => window.clearInterval(timer)
  }, [resolvedWorkspace])

  const selected = useMemo(
    () => environments.find((item) => item.environment_id === selectedId) || environments[0],
    [environments, selectedId],
  )

  return (
    <div className="fixed inset-0 z-[100] flex bg-black/25 p-4 backdrop-blur-sm sm:p-7">
      <section className="mx-auto flex min-h-0 w-full max-w-[1500px] flex-1 overflow-hidden rounded-2xl border border-white/70 bg-bg-card shadow-2xl">
        <aside className="flex w-64 shrink-0 flex-col border-r border-border-soft bg-bg-page/65 p-3">
          <div className="mb-3 flex items-center justify-between px-2 py-1">
            <h2 className="text-sm font-semibold text-text-strong">{t('画布', 'Canvas')}</h2>
            <button type="button" onClick={() => void load()} title={t('刷新', 'Refresh')} className="icon-button h-8 w-8">
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {environments.map((item) => (
              <button
                type="button"
                key={item.environment_id}
                onClick={() => setSelectedId(item.environment_id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left ${selected?.environment_id === item.environment_id ? 'bg-white text-text-strong shadow-sm' : 'text-text-normal hover:bg-white/55'}`}
              >
                <MonitorPlay size={16} className="shrink-0 text-brand-600" />
                <span className="min-w-0 flex-1 truncate text-xs font-medium">{item.name}</span>
                <span className={`h-2 w-2 shrink-0 rounded-full ${item.status === 'running' ? 'bg-emerald-500' : item.status === 'failed' ? 'bg-red-500' : 'bg-zinc-300'}`} />
              </button>
            ))}
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col bg-white">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border-soft px-4">
            <span className="min-w-0 flex-1 truncate text-xs font-medium text-text-normal">{selected?.name || t('空白画布', 'Empty canvas')}</span>
            <button type="button" onClick={onClose} title={t('关闭', 'Close')} className="icon-button h-8 w-8">
              <X size={16} />
            </button>
          </header>
          <div className="min-h-0 flex-1 bg-white">
            {selected ? (
              <iframe
                key={`${selected.environment_id}:${selected.updated_at || ''}`}
                src={selected.preview_url}
                title={selected.name}
                sandbox="allow-scripts allow-forms allow-modals"
                className="h-full w-full border-0"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-text-muted">{loading ? t('正在加载', 'Loading') : t('暂无画布', 'No canvas')}</div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
