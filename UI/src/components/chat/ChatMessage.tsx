import MessageContent from '../MessageContent'
import { useState } from 'react'
import AgentNotes from './AgentNotes'
import SemanticExpressions from '../SemanticExpressions'
import { sourceSelection } from '../../utils/message-links'
import { useLanguage } from '../../store/LanguageContext'
import type { WorkbenchActivity } from '../../services/api'
import TurnProcess, { ProcessText } from './TurnProcess'
import type { FollowupData, MessageData, ReasoningStep, TextSelection } from './types'

type MessageProps = {
  role: MessageData['role']
  avatar: string
  name: string
  time?: string
  content: string
  messageId: string
  sessionId?: string | null
  followups: FollowupData[]
  onSelectText: (selection: TextSelection) => void
  reasoningTreeId?: string
  reasoningSteps?: ReasoningStep[]
  processActivities?: WorkbenchActivity[]
  onOpenWorkbench: () => void
  processRunning?: boolean
  runStatus?: string
  error?: Record<string, unknown>
  onRetry?: () => void
}

export default function ChatMessage({ role, avatar, name, time, content, messageId, sessionId, followups, onSelectText, reasoningTreeId, reasoningSteps = [], processActivities = [], onOpenWorkbench, processRunning = false, runStatus, error, onRetry }: MessageProps) {
  const { t } = useLanguage()
  const [selectedNote, setSelectedNote] = useState<string | null>(null)
  const [noteFocus, setNoteFocus] = useState(0)
  const isAgent = role === 'agent' || role === 'assistant'
  const isTool = role === 'tool' || role === 'status'

  if (isTool) {
    if (runStatus) {
      const code = String(error?.code || '')
      const label = code === 'MODEL_OUTPUT_LIMIT'
        ? t('模型输出额度已用尽，本次未完成。', 'The model reached its output limit before completing the request.')
        : code === 'MODEL_EMPTY_RESPONSE'
          ? t('模型没有返回可执行动作或回答。', 'The model returned no action or answer.')
          : t('本次请求未完成。', 'This request did not complete.')
      return (
        <div className="max-w-[86%] border-l-2 border-amber-300 py-1 pl-3 text-[13px] text-text-muted">
          <div className="flex items-center gap-3"><span>{label}</span>{onRetry && <button type="button" onClick={onRetry} className="shrink-0 text-brand-700 underline">{t('重试', 'Retry')}</button>}</div>
          {(reasoningTreeId || reasoningSteps.length > 0) && <TurnProcess treeId={reasoningTreeId} reasoningSteps={reasoningSteps} activities={processActivities} running={false} onOpenWorkbench={onOpenWorkbench} />}
          {error && <details className="mt-1 text-xs"><summary className="cursor-pointer">{t('错误详情', 'Error details')}</summary><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words py-2">{[code, String(error.message || '')].filter(Boolean).join('\n')}</pre></details>}
        </div>
      )
    }
    return (
      <div className="flex w-full justify-center py-1">
        <div className="rounded-xl border border-brand-100 bg-bg-page/70 px-3 py-1.5 font-mono text-[11px] text-text-muted">
          {content}
        </div>
      </div>
    )
  }

  let displayContent = content
  let thinkingContent = ''
  if (typeof content === 'string' && content.includes('<thinking>')) {
    const parts = content.split('<thinking>')
    const rest = parts[1]
    if (rest && rest.includes('</thinking>')) {
      const restParts = rest.split('</thinking>')
      thinkingContent = restParts[0]
      displayContent = parts[0] + restParts[1]
    }
  }

  return (
    <div className={`chat-message flex max-w-[86%] gap-3.5 ${isAgent ? '' : 'self-start'}`}>
      <div className={`chat-avatar flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden text-[13px] font-semibold ${isAgent ? 'bg-bg-card text-brand-700 ring-1 ring-black/5' : 'bg-brand-600 text-white'}`}>
        {isAgent && avatar === 'agent' ? 'P' : avatar}
      </div>
      <div className="mt-0.5 flex w-full flex-col gap-1 overflow-hidden">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold text-text-strong">{name}</span>
          {time && <span className="text-[11px] text-text-muted">{time}</span>}
        </div>
        {isAgent && (reasoningTreeId || reasoningSteps.length > 0 || processActivities.length > 0 || processRunning) && (
          <TurnProcess
            treeId={reasoningTreeId}
            reasoningSteps={reasoningSteps}
            activities={processActivities}
            running={processRunning}
            onOpenWorkbench={onOpenWorkbench}
          />
        )}
        {thinkingContent && <ProcessText title={t('模型思考', 'Model reasoning')} content={thinkingContent} />}
        <div
          className="relative min-w-0 whitespace-pre-wrap text-[14px] leading-7 text-text-normal [overflow-wrap:anywhere]"
          onMouseUp={(event) => {
            if (displayContent !== content) return
            const selection = window.getSelection()
            const range = selection?.rangeCount ? selection.getRangeAt(0) : null
            const root = event.currentTarget
            if (!range || selection?.isCollapsed) return
            const source = sourceSelection(root, content, range)
            if (!source) return
            const rect = range.getBoundingClientRect()
            if (!rect.width && !rect.height) return
            onSelectText({
              messageId,
              ...source,
              left: Math.max(12, Math.min(window.innerWidth - 130, rect.left)),
              top: Math.min(window.innerHeight - 44, rect.bottom + 8),
            })
          }}
        >
          <MessageContent content={displayContent} followups={followups} onAnnotationClick={sessionId ? (id) => { setSelectedNote(id); setNoteFocus((value) => value + 1) } : undefined} />
        </div>
        {sessionId && <AgentNotes sessionId={sessionId} notes={followups} selectedId={selectedNote} focusVersion={noteFocus} />}
        {sessionId && <SemanticExpressions sessionId={sessionId} messageId={messageId} />}
      </div>
    </div>
  )
}
