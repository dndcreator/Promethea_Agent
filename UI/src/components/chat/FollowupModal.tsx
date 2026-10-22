import { useEffect, useState } from 'react'
import { MessageCircleQuestion, X } from 'lucide-react'
import { sendFollowup } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import type { FollowupData, TextSelection } from './types'

export default function FollowupModal({
  selection,
  sessionId,
  onClose,
  onCreated,
}: {
  selection: TextSelection
  sessionId: string
  onClose: () => void
  onCreated: (followup: FollowupData) => void
}) {
  const { t } = useLanguage()
  const [queryType, setQueryType] = useState<'why' | 'risk' | 'alternative' | 'custom'>('why')
  const [customQuery, setCustomQuery] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  const submit = async () => {
    if (queryType === 'custom' && !customQuery.trim()) return
    setIsSubmitting(true)
    setError('')
    try {
      const response = await sendFollowup({
        selected_text: selection.selectedText,
        query_type: queryType,
        custom_query: queryType === 'custom' ? customQuery.trim() : undefined,
        session_id: sessionId,
        message_id: selection.messageId,
        start_offset: selection.startOffset,
        end_offset: selection.endOffset,
      })
      const data = await response.json()
      if (!response.ok || !data.followup) throw new Error(data?.detail?.message || data?.detail || t('追问失败，请重试。', 'Follow-up failed. Please try again.'))
      onCreated(data.followup)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('追问失败，请重试。', 'Follow-up failed. Please try again.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-5 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="relative w-full max-w-lg rounded-xl border border-white/70 bg-bg-card p-5 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <button type="button" onClick={onClose} className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-lg text-text-muted hover:bg-black/5 hover:text-text-strong" aria-label={t('关闭', 'Close')}>
          <X size={16} />
        </button>
        <div className="flex items-center gap-2 pr-10 text-text-strong">
          <MessageCircleQuestion size={18} className="text-brand-600" />
          <h2 className="text-[16px] font-semibold">{t('追问这段内容', 'Follow up on this text')}</h2>
        </div>
        <blockquote className="mt-4 max-h-28 overflow-y-auto border-l-2 border-brand-300 bg-brand-50/55 px-3 py-2 text-[13px] leading-6 text-text-normal">
          {selection.selectedText}
        </blockquote>
        <div className="mt-4 grid grid-cols-3 gap-2">
          {([
            ['why', t('为什么', 'Why')],
            ['risk', t('风险', 'Risks')],
            ['alternative', t('替代方案', 'Alternatives')],
          ] as const).map(([value, label]) => (
            <button key={value} type="button" onClick={() => setQueryType(value)} className={`rounded-lg border px-3 py-2 text-[12px] font-medium ${queryType === value ? 'border-brand-300 bg-brand-100 text-brand-800' : 'border-black/10 text-text-normal hover:bg-black/5'}`}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => setQueryType('custom')} className={`mt-2 text-[12px] ${queryType === 'custom' ? 'font-semibold text-brand-700' : 'text-text-muted hover:text-text-strong'}`}>
          {t('自定义问题', 'Custom question')}
        </button>
        {queryType === 'custom' && (
          <textarea value={customQuery} onChange={(event) => setCustomQuery(event.target.value)} autoFocus rows={3} className="mt-2 w-full resize-none rounded-lg border border-black/10 bg-bg-page/45 p-3 text-[13px] text-text-strong outline-none focus:border-brand-300" placeholder={t('输入你的问题', 'Write your question')} />
        )}
        {error && <p className="mt-3 text-[12px] text-red-600">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={isSubmitting} className="rounded-lg px-3 py-2 text-[12px] font-medium text-text-muted hover:bg-black/5">{t('取消', 'Cancel')}</button>
          <button type="button" onClick={() => void submit()} disabled={isSubmitting || (queryType === 'custom' && !customQuery.trim())} className="rounded-lg bg-brand-600 px-3 py-2 text-[12px] font-semibold text-white hover:bg-brand-700 disabled:opacity-50">
            {isSubmitting ? t('生成中...', 'Generating...') : t('开始追问', 'Ask')}
          </button>
        </div>
      </div>
    </div>
  )
}
