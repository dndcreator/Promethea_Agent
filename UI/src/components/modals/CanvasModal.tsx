import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookmarkPlus, MonitorPlay, RefreshCw, Trash2, X } from 'lucide-react'
import { connectCanvasFrame } from '@promethea/sdk'

import { getCanvasClient, getSemanticUIClient, type CanvasEnvironment } from '../../services/api'
import FeatureSurface from '../FeatureSurface'
import { useLanguage } from '../../store/LanguageContext'
import { useEnvironmentObservation } from '../../hooks/useEnvironmentObservation'

const identity = (item: Pick<CanvasEnvironment, 'workspace_id' | 'environment_id'>) => `${item.workspace_id}/${item.environment_id}`

export default function CanvasModal({ workspaceId, initialEnvironmentId, onClose, embedded = false, compact = false }: {
  workspaceId?: string | null
  initialEnvironmentId?: string
  onClose: () => void
  embedded?: boolean
  compact?: boolean
}) {
  const { t } = useLanguage()
  const resolvedWorkspace = workspaceId || 'default'
  const [client] = useState(getCanvasClient)
  const [semanticUI] = useState(getSemanticUIClient)
  const [attention, setAttention] = useState<{ component_id: string; definition_revision: string } | null>(null)
  const [environments, setEnvironments] = useState<CanvasEnvironment[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const disconnect = useRef<(() => void) | null>(null)
  const requestEpoch = useRef(0)

  const load = useCallback(async (signal?: AbortSignal) => {
    const epoch = ++requestEpoch.current
    try {
      const workspaces = [...new Set([resolvedWorkspace, '_canvas_library'])]
      const lists = await Promise.all(workspaces.map((id) => client.list(id, signal)))
      if (signal?.aborted || epoch !== requestEpoch.current) return
      const rows = lists.flatMap((list) => list.environments || [])
      setEnvironments(rows)
      setSelectedId((current) => rows.some((row) => identity(row) === current) ? current
        : identity(rows.find((row) => row.environment_id === initialEnvironmentId) || rows[0] || { workspace_id: '', environment_id: '' }))
      setError('')
    } catch (reason) {
      if (!signal?.aborted && epoch === requestEpoch.current) setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      if (!signal?.aborted && epoch === requestEpoch.current) setLoading(false)
    }
  }, [client, resolvedWorkspace, initialEnvironmentId])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    void load(controller.signal)
    const timer = window.setInterval(() => void load(controller.signal), 5000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [load])
  useEffect(() => () => { disconnect.current?.() }, [])

  const selected = useMemo(() => environments.find((item) => identity(item) === selectedId), [environments, selectedId])
  const observe = useEnvironmentObservation('canvas', selected ? [{ kind: 'canvas', id: selected.environment_id, workspace_id: selected.workspace_id }] : [], true, attention)
  useEffect(() => { setAttention(null); disconnect.current?.(); disconnect.current = null }, [selectedId])
  const refresh = () => { setReload((value) => value + 1); void load() }
  const retain = async () => {
    if (!selected || busy) return
    setBusy(true)
    try {
      const retained = await client.retain(selected)
      await load()
      setSelectedId(identity(retained))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const remove = async () => {
    if (!selected || busy || !window.confirm(t('删除此画布？', 'Delete this canvas?'))) return
    setBusy(true)
    try { await client.remove(selected); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  return (
    <FeatureSurface surfaceRef={observe} embedded={embedded} onClose={onClose} label={t('画布', 'Canvas')}>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className={`${compact ? 'hidden' : 'hidden md:flex'} w-56 shrink-0 flex-col border-r border-border-soft bg-bg-page p-3`}>
          <h2 className="mb-3 px-2 text-sm font-semibold text-text-strong">{t('画布', 'Canvas')}</h2>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {environments.map((item) => (
              <button type="button" key={identity(item)} onClick={() => setSelectedId(identity(item))}
                className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left ${selectedId === identity(item) ? 'bg-white text-text-strong shadow-sm' : 'text-text-normal hover:bg-white/55'}`}>
                <MonitorPlay size={16} className="shrink-0" />
                <span className="min-w-0 flex-1 truncate text-xs">{item.name}</span>
                {item.lifetime === 'reusable' && <BookmarkPlus size={13} className="shrink-0 text-emerald-600" />}
              </button>
            ))}
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col bg-white">
          <header className="flex h-12 shrink-0 items-center gap-1 border-b border-border-soft px-2 sm:gap-2 sm:px-4">
            <span className={`${compact ? 'hidden' : 'hidden md:block'} min-w-0 flex-1 truncate text-xs font-medium text-text-normal`}>{selected?.name || t('画布', 'Canvas')}</span>
            <select aria-label={t('选择画布', 'Select canvas')} value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className={`min-w-0 flex-1 bg-transparent text-xs ${compact ? '' : 'md:hidden'}`}>
              {!environments.length && <option value="/">{t('画布', 'Canvas')}</option>}
              {environments.map((row) => <option key={identity(row)} value={identity(row)}>{row.name}</option>)}
            </select>
            {selected?.kind === 'static' && selected.lifetime !== 'reusable' && <button type="button" disabled={busy} onClick={() => void retain()} title={t('保留复用', 'Keep for reuse')} className="icon-button h-8 w-8"><BookmarkPlus size={16} /></button>}
            {selected && <button type="button" disabled={busy} onClick={() => void remove()} title={t('删除', 'Delete')} className="icon-button h-8 w-8"><Trash2 size={15} /></button>}
            <button type="button" onClick={refresh} title={t('刷新', 'Refresh')} className="icon-button h-8 w-8"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
            <button type="button" onClick={onClose} title={t('关闭', 'Close')} className="icon-button h-8 w-8"><X size={16} /></button>
          </header>
          {error && <div role="alert" className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{error}</div>}
          {!!selected?.diagnostics?.length && <details className="border-b border-border-soft px-4 py-2 text-xs text-red-700"><summary>{t('运行错误', 'Runtime errors')} ({selected.diagnostics.length})</summary><pre className="max-h-28 overflow-auto whitespace-pre-wrap">{selected.diagnostics.map((item) => String(item.message || '')).join('\n')}</pre></details>}
          <div className="min-h-0 flex-1">
            {selected ? <iframe key={`${identity(selected)}:${selected.content_revision || selected.updated_at || ''}:${reload}`}
              src={selected.preview_url} title={selected.name} sandbox="allow-scripts allow-forms allow-modals"
              onLoad={(event) => { disconnect.current?.(); setAttention(null); disconnect.current = connectCanvasFrame(event.currentTarget, client, selected, { semanticUI, onAttention: setAttention, labels: { dismiss: t('收起', 'Dismiss'), retry: t('暂时未能保存，请重试。', 'Could not save. Please retry.') } }) }}
              className="h-full w-full border-0" />
              : <div className="flex h-full items-center justify-center text-sm text-text-muted">{loading ? t('正在加载', 'Loading') : t('暂无画布', 'No canvas')}</div>}
          </div>
        </div>
      </div>
    </FeatureSurface>
  )
}
