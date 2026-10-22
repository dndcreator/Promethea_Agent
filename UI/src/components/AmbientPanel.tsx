import { useEffect, useState } from 'react'
import { Check, X, Save, Activity } from 'lucide-react'
import { confirmAmbient, getAmbient, setAmbient, type AmbientState } from '../services/api'
import { useLanguage } from '../store/LanguageContext'
import { useAuth } from '../store/AuthContext'

export default function AmbientPanel({ sessionId, snapshot, onObserve }: { sessionId: string | null; snapshot?: AmbientState | null; onObserve?: (taskId: string) => void }) {
  const { lang, t } = useLanguage()
  const { user } = useAuth()
  const [state, setState] = useState<AmbientState | null>(null)
  const [direction, setDirection] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingEnabled, setPendingEnabled] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    setState(null)
    setError('')
    void getAmbient(sessionId, controller.signal).then((value) => {
      if (!controller.signal.aborted) { setState((current) => !current || (value.revision || 0) >= (current.revision || 0) ? value : current); setDirection(value.settings?.direction || '') }
    }).catch(() => { if (!controller.signal.aborted) setError(t('状态读取失败', 'Could not load status')) })
    return () => controller.abort()
  }, [sessionId, t, user?.user_id])
  useEffect(() => {
    if (snapshot) setState((current) => !current || (snapshot.revision || 0) >= (current.revision || 0) ? snapshot : current)
  }, [sessionId, snapshot])
  const execute = async (operation: () => Promise<AmbientState>) => {
    setBusy(true)
    setError('')
    try { setState(await operation()) }
    catch (cause) { setError(cause instanceof Error ? cause.message : t('操作失败', 'Operation failed')) }
    finally { setBusy(false) }
  }
  const save = async (enabled: boolean) => {
    setPendingEnabled(enabled)
    try { await execute(() => setAmbient(sessionId, { enabled, direction, ui_language: lang, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })) }
    finally { setPendingEnabled(null) }
  }
  if (!user || (!state?.available && !error)) return null
  const pending = state?.pending
  return <section className="workbench-section ambient-panel">
    <div className="flex items-center justify-between gap-3">
      <h3>{t('主动协作', 'Ambient collaboration')}</h3>
      {state?.task_id && onObserve && <button type="button" className="icon-button ml-auto" title={t('查看行动', 'Inspect actions')} aria-label={t('查看主动行动', 'Inspect ambient actions')} onClick={() => onObserve(state.task_id!)}><Activity size={15} /></button>}
      <input type="checkbox" role="switch" className="accent-brand-600" aria-label={t('主动协作', 'Ambient collaboration')} checked={pendingEnabled ?? state?.settings?.enabled ?? false} disabled={busy || !state?.available} onChange={(event) => void save(event.target.checked)} />
    </div>
    {state?.settings?.enabled && <>
      {state.status === 'budget_exhausted' && <p className="mt-2 text-xs text-text-muted">{t('今日自主运行额度已用尽', 'Daily autonomous budget reached')}</p>}
      <div className="mt-2 flex items-center gap-2">
        <input className="min-w-0 flex-1 rounded border border-black/10 bg-transparent px-2 py-1 text-sm" aria-label={t('关注方向', 'Focus')} placeholder={t('关注方向', 'Focus')} value={direction} maxLength={2000} onChange={(event) => setDirection(event.target.value)} />
        <button type="button" className="icon-button" title={t('保存', 'Save')} aria-label={t('保存关注方向', 'Save focus')} disabled={busy} onClick={() => void save(true)}><Save size={15} /></button>
      </div>
      {state.status === 'paused' && <button type="button" className="mt-2 text-sm underline" disabled={busy} onClick={() => void save(true)}>{t('继续', 'Resume')}</button>}
      {(state.attention || []).length > 0 && <ul className="mt-2 space-y-1 text-sm">{state.attention?.map((item, i) => <li key={i}>{item}</li>)}</ul>}
      {((state.questions || []).length > 0 || state.reflection) && <details className="mt-2 text-sm"><summary>{t('当前关注', 'Current attention')}</summary><div className="mt-2 whitespace-pre-wrap break-words">{state.reflection}</div>{state.questions?.map((item, i) => <p key={i}>{item}</p>)}</details>}
      {pending && <div className="mt-3 border-l-2 border-amber-400 pl-3 text-sm">
        <strong>{t('等待批准', 'Approval needed')}</strong><p className="break-words">{pending.tool_name}</p>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(pending.args, null, 2)}</pre>
        <div className="mt-2 flex gap-2">{(['approve', 'reject'] as const).map((action) => <button key={action} type="button" disabled={busy} className="flex items-center gap-1 rounded border border-black/10 px-2 py-1" onClick={() => void execute(() => confirmAmbient(sessionId, { run_id: pending.run_id, tool_call_id: pending.tool_call_id, action }))}>{action === 'approve' ? <Check size={14} /> : <X size={14} />}{action === 'approve' ? t('批准这次操作', 'Approve once') : t('拒绝', 'Reject')}</button>)}</div>
      </div>}
    </>}
    {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
  </section>
}
