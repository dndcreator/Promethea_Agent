import { useState } from 'react'
import { MessageCircle, PanelTop, Smile, X, ListChecks } from 'lucide-react'
import { sendSemanticFeedback } from '../services/api'
import type { SemanticExpression } from '../services/api'
import { useWorkbench } from '../store/WorkbenchContext'
import { useLanguage } from '../store/LanguageContext'
import { useAuth } from '../store/AuthContext'

const icons = { note: MessageCircle, gesture: Smile, choice: ListChecks, panel: PanelTop }

export default function SemanticExpressions({ sessionId, messageId }: { sessionId: string | null; messageId?: string }) {
  const { snapshot } = useWorkbench()
  const { user } = useAuth()
  const { t } = useLanguage()
  const [updates, setUpdates] = useState<Record<string, SemanticExpression>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const identity = user?.user_id || ''
  const expressions = (snapshot?.semantic_ui?.expressions || []).map((item) => {
    const updated = updates[`${identity}:${item.expression_id}`]
    return updated && updated.revision >= item.revision ? updated : item
  }).filter((item) => !item.hidden && item.state !== 'dismissed'
    && (messageId ? item.message_id === messageId && item.session_id === sessionId : !item.message_id && (!item.session_id || item.session_id === sessionId)))

  if (!user || !expressions.length) return null

  const respond = async (item: SemanticExpression, choiceId?: string) => {
    if (busy) return
    const key = `${identity}:${item.expression_id}`
    setBusy(key)
    setError('')
    try {
      const result = await sendSemanticFeedback(item.expression_id, {
        expected_revision: item.revision, action: choiceId ? 'respond' : 'dismiss', choice_id: choiceId || null,
      })
      setUpdates((previous) => ({ ...previous, [key]: result }))
    } catch {
      setError(t('暂时未能保存，请重试。', 'Could not save. Please retry.'))
    } finally {
      setBusy(null)
    }
  }

  return <div className="semantic-expressions space-y-2" aria-label={t('Agent 互动', 'Agent expressions')}>
    {expressions.map((item) => {
      const Icon = icons[item.kind]
      return <section key={item.expression_id} data-expression-id={item.expression_id} className={`semantic-expression semantic-${item.tone} flex min-w-0 gap-2.5 rounded-md border border-black/10 bg-bg-card px-3 py-2.5 text-[13px]`}>
        <Icon size={16} className="mt-0.5 shrink-0 text-text-muted" aria-hidden="true" />
        <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
          {item.title && <h3 className="mb-1 text-[13px] font-semibold text-text-strong">{item.title}</h3>}
          <p className="whitespace-pre-wrap leading-6 text-text-normal">{item.content}</p>
          {item.kind === 'choice' && <div className="mt-2 flex flex-wrap gap-2">
            {(item.choices || []).map((choice) => <button key={choice.id} type="button" disabled={busy !== null || item.state !== 'open'} aria-pressed={item.response === choice.id} onClick={() => void respond(item, choice.id)} className={`rounded border px-2.5 py-1 text-left text-xs transition-colors disabled:cursor-default ${item.response === choice.id ? 'border-brand-400 bg-brand-50 text-brand-800' : 'border-black/10 hover:border-brand-400 disabled:opacity-50'}`}>{choice.label}</button>)}
          </div>}
        </div>
        <button type="button" className="flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-black/5 disabled:opacity-50" disabled={busy !== null} title={t('收起', 'Dismiss')} aria-label={t('收起', 'Dismiss')} onClick={() => void respond(item)}><X size={14} /></button>
      </section>
    })}
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
  </div>
}
