import { useState } from 'react'
import { Check, X } from 'lucide-react'
import { sendAmbientFeedback } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import type { FollowupData } from './types'

export default function AgentNotes({ sessionId, notes, selectedId, focusVersion }: { sessionId: string; notes: FollowupData[]; selectedId: string | null; focusVersion: number }) {
  const { t } = useLanguage()
  const [states, setStates] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const feedback = async (id: string, decision: 'accepted' | 'dismissed') => {
    setBusy(true)
    setError('')
    try { await sendAmbientFeedback(sessionId, { annotation_id: id, decision, comment: '' }); setStates((value) => ({ ...value, [id]: decision })) }
    catch { setError(t('反馈保存失败', 'Could not save feedback')) }
    finally { setBusy(false) }
  }
  return <div className="space-y-2 text-sm">{notes.filter((note) => note.source === 'agent' && (states[note.id] || note.state) !== 'dismissed').map((note) => <details key={`${note.id}:${selectedId === note.id ? focusVersion : ''}`} open={selectedId === note.id || undefined} className="border-l-2 border-black/15 pl-3">
    <summary className="cursor-pointer text-text-muted">{note.query}</summary>
    <blockquote className="my-1 text-xs text-text-muted">{note.selected_text}</blockquote>
    <p className="whitespace-pre-wrap break-words">{note.response}</p>
    <div className="flex items-center gap-1">{(states[note.id] || note.state) === 'accepted' ? <span className="text-xs text-text-muted">{t('已采纳', 'Accepted')}</span> : <button type="button" className="icon-button" disabled={busy} title={t('采纳', 'Accept')} aria-label={t('采纳', 'Accept')} onClick={() => void feedback(note.id, 'accepted')}><Check size={14} /></button>}<button type="button" className="icon-button" disabled={busy} title={t('忽略', 'Dismiss')} aria-label={t('忽略', 'Dismiss')} onClick={() => void feedback(note.id, 'dismissed')}><X size={14} /></button></div>
  </details>)}{error && <p role="alert" className="text-xs text-red-600">{error}</p>}</div>
}
