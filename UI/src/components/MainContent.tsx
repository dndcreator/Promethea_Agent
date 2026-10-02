import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Clock3, Link2, MessageCircleQuestion, Mic, PanelRightOpen, Paperclip, Plus, Search, Send, Smile, Square, X } from 'lucide-react'
import ConfirmModal from './modals/ConfirmModal'
import { getActiveReasoning, getMetrics, getSession, getWelcome, sendFollowup, sendVoicePtt, stopReasoningTree, streamChat } from '../services/api'
import type { ChatAttachment } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

interface MessageData {
  id: string
  role: 'user' | 'agent' | 'assistant' | 'tool'
  content: string
  name?: string
  time?: string
}

interface MainContentProps {
  sessionId: string | null
  setSessionId: (id: string | null) => void
  setTreeId: (id: string | null) => void
  setChatRunning: (running: boolean) => void
  onRequireAuth: () => void
  onOpenFiles: () => void
  onOpenSearch: () => void
  onOpenMemory: () => void
  onOpenWorkbench: () => void
  memoryReviewId: string | null
  attachments: ChatAttachment[]
  onRemoveAttachment: (fileId: string) => void
  onClearAttachments: () => void
}

type StreamPayload = Record<string, any>
type MemoryNotice = {
  text: string
  requiresReview: boolean
}

type FollowupData = {
  id: string
  message_id: string
  selected_text: string
  start_offset: number
  end_offset: number
  query_type: string
  custom_query?: string | null
  query: string
  response: string
  created_at: number
}

type TextSelection = {
  messageId: string
  selectedText: string
  startOffset: number
  endOffset: number
  left: number
  top: number
}

type WelcomeState = {
  greeting: string
  context_hint: string
  suggested_actions: string[]
}

function asStreamPayload(data: unknown): StreamPayload {
  return data && typeof data === 'object' ? (data as StreamPayload) : {}
}

function memoryNoticeFromPayload(payload: StreamPayload, t: (zh: string, en: string) => string): string {
  const visibility = payload.memory_visibility || payload.memory_write_summary
  if (!visibility || typeof visibility !== 'object') return ''
  const notices = Array.isArray(visibility.notices) ? visibility.notices.filter(Boolean) : []
  const direct = [visibility.recall_notice, visibility.write_notice, visibility.review_notice].filter(Boolean)
  const hints = Array.isArray(visibility.feedback_hints)
    ? visibility.feedback_hints
        .map((hint: any) => {
          const type = String(hint?.type || '')
          if (type === 'memory_saved') return t('已写入长期记忆。', 'Saved to long-term memory.')
          if (type === 'memory_review_needed') return t('检测到记忆冲突，等待确认。', 'Memory conflict detected; review is needed.')
          return ''
        })
        .filter(Boolean)
    : []
  return [...notices, ...direct, ...hints].filter(Boolean).join(' ')
}

const WELCOME_IDLE_REFRESH_MS = 3 * 60 * 60 * 1000

function memoryNoticeInfoFromPayload(payload: StreamPayload, t: (zh: string, en: string) => string): MemoryNotice | null {
  const text = memoryNoticeFromPayload(payload, t)
  if (!text) return null
  const visibility = payload.memory_visibility || payload.memory_write_summary
  const hints = visibility && typeof visibility === 'object' && Array.isArray(visibility.feedback_hints)
    ? visibility.feedback_hints
    : []
  const requiresReview = hints.some((hint: any) => String(hint?.type || '') === 'memory_review_needed')
  return { text, requiresReview }
}

function tokenCountFromPayload(payload: StreamPayload): number {
  const usage = payload.usage && typeof payload.usage === 'object' ? payload.usage : {}
  const candidates = [
    payload.total_tokens,
    payload.token_count,
    payload.tokens,
    usage.total_tokens,
    usage.total,
  ]
  for (const value of candidates) {
    const numeric = Number(value)
    if (Number.isFinite(numeric) && numeric > 0) return numeric
  }
  const prompt = Number(payload.prompt_tokens ?? usage.prompt_tokens ?? 0)
  const completion = Number(payload.completion_tokens ?? usage.completion_tokens ?? 0)
  const total = prompt + completion
  return Number.isFinite(total) && total > 0 ? total : 0
}

export default function MainContent({
  sessionId,
  setSessionId,
  setTreeId,
  setChatRunning,
  onRequireAuth,
  onOpenFiles,
  onOpenSearch,
  onOpenMemory,
  onOpenWorkbench,
  memoryReviewId,
  attachments,
  onRemoveAttachment,
  onClearAttachments,
}: MainContentProps) {
  const { user } = useAuth()
  const { lang, t } = useLanguage()
  const [messages, setMessages] = useState<MessageData[]>([])
  const [input, setInput] = useState('')
  const [sessionTitle, setSessionTitle] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [confirmRequest, setConfirmRequest] = useState<any>(null)
  const [memoryNotice, setMemoryNotice] = useState<MemoryNotice | null>(null)
  const [welcome, setWelcome] = useState<WelcomeState | null>(null)
  const [welcomeRefreshToken, setWelcomeRefreshToken] = useState(0)
  const [welcomeClock, setWelcomeClock] = useState(() => new Date())
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [isNearBottom, setIsNearBottom] = useState(true)
  const [followups, setFollowups] = useState<FollowupData[]>([])
  const [textSelection, setTextSelection] = useState<TextSelection | null>(null)
  const [followupDraft, setFollowupDraft] = useState<TextSelection | null>(null)
  const [meta, setMeta] = useState({ tokens: 0, latency: 0, intensity: 'idle' })
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const followOutputRef = useRef(true)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const activeTreeIdRef = useRef<string | null>(null)
  const welcomeLoadedAtRef = useRef(0)
  const welcomeRequestRef = useRef(0)
  const selectionActionRef = useRef<HTMLButtonElement>(null)
  const observedMemoryReviewRef = useRef<string | null>(null)
  const localWelcomeFallback = useMemo<WelcomeState>(() => ({
    greeting: t(
      `你好，我是 ${user?.agent_name || 'Promethea'}。`,
      `Hi, I am ${user?.agent_name || 'Promethea'}.`,
    ),
    context_hint: t('可以直接告诉我你想推进的任务。', 'Tell me what you want to work on.'),
    suggested_actions: [
      t('开始一个新任务', 'Start a new task'),
      t('查看当前工作台状态', 'Review workspace status'),
      t('整理下一步计划', 'Plan next steps'),
    ],
  }), [t, user?.agent_name])
  const quickEmojis = ['\u{1F642}', '\u{1F44D}', '\u{1F64F}', '\u{1F4A1}', '\u{2705}', '\u{1F525}']

  useEffect(() => {
    const previousReviewId = observedMemoryReviewRef.current
    observedMemoryReviewRef.current = memoryReviewId
    if (memoryReviewId) {
      setMemoryNotice({
        text: t('检测到记忆冲突，等待确认。', 'Memory conflict detected; review is needed.'),
        requiresReview: true,
      })
    } else if (previousReviewId) {
      setMemoryNotice((current) => current?.requiresReview ? null : current)
    }
  }, [memoryReviewId, t])

  useEffect(() => {
    if (!textSelection) return

    const dismiss = (event: PointerEvent) => {
      if (selectionActionRef.current?.contains(event.target as Node)) return
      setTextSelection(null)
    }
    const dismissOnKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTextSelection(null)
    }
    const dismissOnScroll = () => setTextSelection(null)

    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismissOnKey)
    window.addEventListener('scroll', dismissOnScroll, true)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismissOnKey)
      window.removeEventListener('scroll', dismissOnScroll, true)
    }
  }, [textSelection])

  useEffect(() => {
    if (followOutputRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(160, Math.max(32, el.scrollHeight))}px`
  }, [input])

  useEffect(() => {
    refreshTokenMetric()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => setWelcomeClock(new Date()), 30000)
    return () => window.clearInterval(timer)
  }, [])

  const loadWelcome = useCallback(async () => {
    if (!user) return
    const requestId = welcomeRequestRef.current + 1
    welcomeRequestRef.current = requestId
    const fallback = localWelcomeFallback
    try {
      const res = await getWelcome(lang)
      if (!res.ok) throw new Error(`welcome status ${res.status}`)
      const data = await res.json()
      if (welcomeRequestRef.current !== requestId) return
      setWelcome({
        greeting: data.greeting || fallback.greeting,
        context_hint: data.context_hint || fallback.context_hint,
        suggested_actions: Array.isArray(data.suggested_actions) && data.suggested_actions.length > 0
          ? data.suggested_actions.slice(0, 3)
          : fallback.suggested_actions,
      })
    } catch (error) {
      if (welcomeRequestRef.current === requestId) setWelcome(fallback)
    }
    if (welcomeRequestRef.current === requestId) {
      welcomeLoadedAtRef.current = Date.now()
    }
  }, [lang, localWelcomeFallback, user?.user_id])

  useEffect(() => {
    if (!user?.user_id) {
      welcomeRequestRef.current += 1
      welcomeLoadedAtRef.current = 0
      setWelcome(null)
      return
    }
    void loadWelcome()
  }, [loadWelcome, user?.user_id, welcomeRefreshToken])

  useEffect(() => {
    const refreshAfterLongIdle = () => {
      if (document.visibilityState !== 'visible' || sessionId || messages.length > 0 || isStreaming) return
      if (Date.now() - welcomeLoadedAtRef.current < WELCOME_IDLE_REFRESH_MS) return
      setWelcomeRefreshToken((current) => current + 1)
    }
    window.addEventListener('focus', refreshAfterLongIdle)
    document.addEventListener('visibilitychange', refreshAfterLongIdle)
    return () => {
      window.removeEventListener('focus', refreshAfterLongIdle)
      document.removeEventListener('visibilitychange', refreshAfterLongIdle)
    }
  }, [isStreaming, messages.length, sessionId])

  useEffect(() => {
    if (isStreaming) {
      return
    }
    if (!sessionId) {
      setMessages([])
      setSessionTitle('')
      setTreeId(null)
      setMemoryNotice(null)
      return
    }
    const fetchSessionHistory = async () => {
      try {
        const res = await getSession(sessionId)
        if (!res.ok) return
        const data = await res.json()
        if (data.tree_id) setTreeId(data.tree_id)
        const sessionInfo = data.session_info || data
        setSessionTitle(String(sessionInfo.title || '').trim())
        setFollowups(Array.isArray(sessionInfo.followups) ? sessionInfo.followups : [])
        const loadedMessages: MessageData[] = (data.messages || []).map((message: any, index: number) => {
          const role = message.role === 'assistant' ? 'agent' : message.role
          return {
            id: message.id || `${sessionId}-${index}`,
            role,
            content: message.content || '',
            name: role === 'agent' ? user?.agent_name || 'Promethea' : user?.username || 'You',
          }
        })
        if (loadedMessages.length === 0 && messages.length > 0) return
        setMessages(loadedMessages)
      } catch (error) {
        console.error('Failed to load session', error)
      }
    }
    fetchSessionHistory()
  }, [sessionId, user, setTreeId, isStreaming, messages.length])

  const insertIntoInput = (text: string) => {
    const el = inputRef.current
    if (!el) {
      setInput((prev) => prev + text)
      return
    }
    const start = el.selectionStart ?? input.length
    const end = el.selectionEnd ?? input.length
    const next = input.slice(0, start) + text + input.slice(end)
    setInput(next)
    requestAnimationFrame(() => {
      el.focus()
      const pos = start + text.length
      el.setSelectionRange(pos, pos)
    })
  }

  const handleNewChat = () => {
    setSessionId(null)
    setTreeId(null)
    setChatRunning(false)
    activeTreeIdRef.current = null
    setMessages([])
    setSessionTitle('')
    setMemoryNotice(null)
    setFollowups([])
    setTextSelection(null)
    setFollowupDraft(null)
    followOutputRef.current = true
    setIsNearBottom(true)
    setWelcomeRefreshToken((current) => current + 1)
  }

  const refreshTokenMetric = async () => {
    try {
      const res = await getMetrics()
      if (!res.ok) return
      const data = await res.json()
      const llm = (data.metrics || data).llm || {}
      const tokens = Number(llm.total_tokens || 0)
      if (Number.isFinite(tokens) && tokens > 0) {
        setMeta((prev) => ({ ...prev, tokens }))
      }
    } catch {
      // Metrics are secondary UI chrome; chat should not fail if they are unavailable.
    }
  }

  const handleMessagesScroll = () => {
    const el = messagesScrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    followOutputRef.current = nearBottom
    setIsNearBottom(nearBottom)
  }

  const jumpToLatest = () => {
    followOutputRef.current = true
    setIsNearBottom(true)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }

  const resolveActiveTreeId = async (): Promise<string | null> => {
    if (activeTreeIdRef.current) return activeTreeIdRef.current
    if (!sessionId) return null
    const res = await getActiveReasoning(sessionId)
    if (!res.ok) return null
    const data = await res.json()
    const items = Array.isArray(data.items) ? data.items : []
    const active = items.find((item: any) => ['running', 'active', 'pending'].includes(String(item?.status || '').toLowerCase()))
    return active?.tree_id ? String(active.tree_id) : null
  }

  const handleStopStreaming = async () => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsStreaming(false)
    setChatRunning(false)
    setMeta((prev) => ({ ...prev, intensity: 'idle' }))
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-stopped`,
        role: 'tool',
        content: t('任务已请求停止。', 'Stop requested.'),
      },
    ])
    try {
      const treeId = await resolveActiveTreeId()
      if (treeId) {
        await stopReasoningTree(treeId, 'User stopped via main composer')
      }
    } catch (error) {
      console.error('Failed to stop reasoning tree', error)
    }
  }

  const handleSend = async (text: string = input) => {
    if (!text.trim() || isStreaming) return
    if (!user) {
      onRequireAuth()
      return
    }

    const userMessage: MessageData = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: text,
      name: user.username || 'You',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }
    const agentMessageId = `${Date.now()}-agent`
    if (!sessionId && !sessionTitle) {
      const oneLineTitle = text.trim().replace(/\s+/g, ' ')
      setSessionTitle(oneLineTitle.slice(0, 40) + (oneLineTitle.length > 40 ? '...' : ''))
    }

    setMessages((prev) => [
      ...prev,
      userMessage,
      {
        id: agentMessageId,
        role: 'agent',
        content: '',
        name: user.agent_name || 'Promethea',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ])
    setInput('')
    setMemoryNotice(null)
    setIsStreaming(true)
    setChatRunning(true)
    followOutputRef.current = true
    setIsNearBottom(true)
    const controller = new AbortController()
    abortControllerRef.current = controller

    const startTime = Date.now()

    await streamChat(
      userMessage.content,
      sessionId,
      attachments,
      (event, data) => {
        const payload = asStreamPayload(data)
        if (event === 'text') {
          const chunk = typeof data === 'string' ? data : String(payload.content || '')
          setMessages((prev) => prev.map((m) => (m.id === agentMessageId ? { ...m, content: m.content + chunk } : m)))
          return
        }
        if (event === 'tool_call' || event === 'tool_start') {
          setMessages((prev) => [...prev, { id: `${Date.now()}-tool`, role: 'tool', content: `Running tool: ${payload.tool_name || payload.name || 'tool'}...` }])
          return
        }
        if (event === 'tool_result') {
          setMessages((prev) => [...prev, { id: `${Date.now()}-tool`, role: 'tool', content: `Tool ${payload.tool_name || payload.name || 'tool'} completed.` }])
          return
        }
        if (event === 'session_started') {
          if (payload.session_id) setSessionId(String(payload.session_id))
          return
        }
        if (event === 'reasoning_meta') {
          if (payload.tree_id) {
            activeTreeIdRef.current = String(payload.tree_id)
            setTreeId(String(payload.tree_id))
          }
          const tokens = tokenCountFromPayload(payload)
          setMeta((prev) => ({ ...prev, tokens: tokens || prev.tokens, intensity: payload.status || 'thinking' }))
          return
        }
        if (event === 'memory_visibility') {
          const notice = memoryNoticeInfoFromPayload(payload, t)
          if (notice) setMemoryNotice(notice)
          return
        }
        if (event === 'done') {
          abortControllerRef.current = null
          setIsStreaming(false)
          setChatRunning(false)
          if (payload.session_id) setSessionId(String(payload.session_id))
          if (payload.tree_id) {
            activeTreeIdRef.current = String(payload.tree_id)
            setTreeId(String(payload.tree_id))
          }
          onClearAttachments()
          const notice = memoryNoticeInfoFromPayload(payload, t)
          if (notice) setMemoryNotice(notice)
          const doneTokens = tokenCountFromPayload(payload)
          setMeta((prev) => ({ ...prev, tokens: doneTokens || prev.tokens, latency: (Date.now() - startTime) / 1000, intensity: 'idle' }))
          void refreshTokenMetric()
          if (payload.session_id) {
            void getSession(String(payload.session_id))
              .then(async (res) => {
                if (!res.ok) return
                const data = await res.json()
                const sessionInfo = data.session_info || data
                if (sessionInfo.title) setSessionTitle(String(sessionInfo.title))
                if (Array.isArray(sessionInfo.followups)) setFollowups(sessionInfo.followups)
                if (Array.isArray(data.messages)) {
                  setMessages(data.messages.map((message: any, index: number) => {
                    const role = message.role === 'assistant' ? 'agent' : message.role
                    return {
                      id: message.id || `${payload.session_id}-${index}`,
                      role,
                      content: message.content || '',
                      name: role === 'agent' ? user?.agent_name || 'Promethea' : user?.username || 'You',
                    }
                  }))
                }
              })
              .catch(() => {})
          }
          if (payload.status === 'needs_confirmation') {
            setConfirmRequest({
              sessionId: String(payload.session_id || sessionId || ''),
              toolCallId: String(payload.tool_call_id || ''),
              toolName: String(payload.tool_name || 'tool'),
              toolArgs: typeof payload.args === 'string' ? payload.args : JSON.stringify(payload.args, null, 2),
            })
          }
          return
        }
        if (event === 'error') {
          abortControllerRef.current = null
          setIsStreaming(false)
          setChatRunning(false)
          const message = typeof data === 'string' ? data : payload.content || 'Unknown error'
          setMessages((prev) => [...prev, { id: `${Date.now()}-error`, role: 'agent', content: `Error: ${message}` }])
        }
      },
      (error) => {
        abortControllerRef.current = null
        setIsStreaming(false)
        setChatRunning(false)
        setMessages((prev) => [...prev, { id: `${Date.now()}-error`, role: 'agent', content: `Error: ${error.message}` }])
      },
      controller.signal,
    )
  }

  const startRecording = async () => {
    if (!user) {
      onRequireAuth()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data)
      }
      mediaRecorder.start()
      setIsRecording(true)
    } catch {
      alert(t('无法访问麦克风。', 'Microphone access denied or unavailable.'))
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        const formData = new FormData()
        formData.append('audio', audioBlob, 'voice.webm')
        if (sessionId) formData.append('session_id', sessionId)
        formData.append('speak', 'true')
        try {
          setIsStreaming(true)
          setChatRunning(true)
          const res = await sendVoicePtt(formData)
          if (res.ok) {
            const data = await res.json()
            setMessages((prev) => [
              ...prev,
              { id: `${Date.now()}-voice-user`, role: 'user', content: data.transcript || t('语音消息', 'voice message'), name: user?.username || 'You' },
              { id: `${Date.now()}-voice-agent`, role: 'agent', content: data.turn?.response || '', name: user?.agent_name || 'Promethea' },
            ])
            if (data.turn?.session_id) setSessionId(data.turn.session_id)
            if (data.tts?.audio_base64) {
              const audioUrl = `data:${data.tts.mime || 'audio/mp3'};base64,${data.tts.audio_base64}`
              new Audio(audioUrl).play()
            }
          }
        } catch (error) {
          console.error('Voice PTT failed', error)
        } finally {
          setIsStreaming(false)
          setChatRunning(false)
        }
      }
      mediaRecorderRef.current.stop()
      mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop())
      setIsRecording(false)
    }
  }

  return (
    <main className="relative flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[1.35rem] border border-white/70 bg-bg-card/46 backdrop-blur-md fine-border">
      <header className="flex items-center justify-between border-b border-white/55 bg-bg-card/48 py-3 pl-14 pr-3 sm:px-6 sm:py-4">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 truncate font-display text-[18px] font-semibold tracking-[-0.035em] text-text-strong sm:text-[21px]">
            {sessionId ? (sessionTitle || `${t('会话', 'Session')}: ${sessionId.slice(0, 8)}...`) : t('新的对话', 'New conversation')}
            <Link2 size={15} className="text-text-muted" />
          </h1>
        </div>
        <div className="ml-2 flex shrink-0 items-center gap-1.5 sm:gap-4">
          <div className="hidden items-center gap-2 text-[11px] lg:flex">
            <span className="text-text-muted">{t('思考强度', 'Thinking')}</span>
            <div className="flex h-3 items-end gap-0.5">
              <span className={`h-1/3 w-1 rounded-sm bg-brand-200 ${isStreaming ? 'animate-pulse' : ''}`} />
              <span className={`h-2/3 w-1 rounded-sm bg-brand-300 ${isStreaming ? 'animate-pulse delay-75' : ''}`} />
              <span className={`h-full w-1 rounded-sm bg-brand-500 ${isStreaming ? 'animate-pulse delay-150' : ''}`} />
            </div>
            <span className="ml-1 font-semibold text-brand-600">{meta.intensity === 'idle' ? t('空闲', 'idle') : t('活跃', 'active')}</span>
          </div>
          <div className="hidden sm:contents">
            <Metric label="Tokens" value={meta.tokens > 1000 ? `${(meta.tokens / 1000).toFixed(1)}k` : String(meta.tokens)} />
            <Metric label="Latency" value={meta.latency ? `${meta.latency.toFixed(1)}s` : '-'} />
          </div>
          <HeaderButton onClick={onOpenSearch} title={t('搜索会话和文件', 'Search sessions and files')}>
            <Search size={15} />
          </HeaderButton>
          <HeaderButton onClick={handleNewChat} title={t('新建对话', 'New chat')}>
            <Plus size={16} />
          </HeaderButton>
          <span className="xl:hidden">
            <HeaderButton onClick={onOpenWorkbench} title={t('打开工作台', 'Open workbench')}>
              <PanelRightOpen size={16} />
            </HeaderButton>
          </span>
        </div>
      </header>

      {memoryNotice && (
        <div className={`mx-6 mt-4 flex items-center justify-between gap-3 rounded-2xl border px-4 py-2 text-[12px] font-medium ${
          memoryNotice.requiresReview
            ? 'border-amber-200 bg-amber-50/90 text-amber-900'
            : 'border-emerald-100 bg-emerald-50/80 text-emerald-800'
        }`}>
          <span>{memoryNotice.text}</span>
          {memoryNotice.requiresReview && (
            <button type="button" onClick={onOpenMemory} className="shrink-0 rounded-lg bg-amber-100 px-3 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-200">
              {t('打开记忆', 'Open Memory')}
            </button>
          )}
        </div>
      )}

      <div ref={messagesScrollRef} onScroll={handleMessagesScroll} className="relative flex-1 overflow-y-auto p-3 sm:p-6">
        <div className="flex flex-col gap-6">
          {messages.length === 0 && (
            <div className="hero-panel soft-grid rounded-[1.6rem] border border-white/70 p-4 text-left text-text-muted fine-border sm:p-8">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="rounded-full border border-brand-100 bg-bg-card/82 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.24em] text-brand-600">
                  {user?.agent_name || 'Promethea'}
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-card/82 px-3 py-1 text-[11px] text-text-muted shadow-sm">
                  <Clock3 size={12} />
                  {formatWelcomeClock(welcomeClock, lang)}
                </span>
              </div>
              <h2 className="mb-3 max-w-[720px] font-display text-[30px] font-semibold leading-tight text-text-strong">
                {welcome?.greeting || localWelcomeFallback.greeting}
              </h2>
              <p className="max-w-[680px] text-[14px] leading-7 text-text-normal">
                {welcome?.context_hint || localWelcomeFallback.context_hint}
              </p>
              <div className="mt-6 flex flex-wrap gap-2">
                {(welcome?.suggested_actions || localWelcomeFallback.suggested_actions).map((action) => (
                  <button
                    key={action}
                    type="button"
                    onClick={() => {
                      setInput(action)
                      setTimeout(() => inputRef.current?.focus(), 0)
                    }}
                    className="rounded-xl border border-white/70 bg-bg-card/88 px-3 py-2 text-[12px] font-medium text-text-normal shadow-sm transition-colors hover:border-brand-200 hover:text-brand-700"
                  >
                    {action}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <Message
              key={msg.id}
              role={msg.role}
              avatar={msg.role === 'agent' || msg.role === 'assistant' ? 'agent' : msg.name?.charAt(0).toUpperCase() || 'U'}
              name={msg.name || msg.role}
              time={msg.time}
              content={msg.content}
              messageId={msg.id}
              followups={followups.filter((item) => item.message_id === msg.id)}
              onSelectText={(selection) => setTextSelection(selection)}
            />
          ))}

          <div ref={messagesEndRef} />
        </div>
        {isStreaming && !isNearBottom && (
          <button
            type="button"
            onClick={jumpToLatest}
            className="sticky bottom-2 left-1/2 z-20 -translate-x-1/2 rounded-full border border-brand-100 bg-bg-card/95 px-3 py-1.5 text-[11px] font-semibold text-brand-700 shadow-sm backdrop-blur hover:border-brand-300"
          >
            {t('跳到最新', 'Jump to latest')}
          </button>
        )}
      </div>

      <div className="relative z-20 border-t border-white/60 bg-bg-card/70 p-2 sm:p-4">
        <div className={`overflow-hidden rounded-[1.15rem] border bg-bg-card shadow-sm transition-shadow focus-within:ring-2 ${isRecording ? 'border-red-300 ring-2 ring-red-100' : 'border-white/70 focus-within:ring-brand-100'}`}>
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 border-b border-black/5 bg-brand-50/45 px-4 py-2">
              {attachments.map((file) => (
                <button
                  key={file.file_id}
                  type="button"
                  onClick={() => onRemoveAttachment(file.file_id)}
                  className="rounded-full border border-brand-100 bg-bg-card px-3 py-1 text-[11px] text-brand-700 hover:border-brand-300"
                  title={t('点击移除附件', 'Click to remove attachment')}
                >
                  {file.filename || file.file_id}
                  {file.text_extraction_status && file.text_extraction_status !== 'ok' ? ` · ${t('仅保存', 'stored only')}` : ''}
                  <span className="ml-1 text-brand-400">x</span>
                </button>
              ))}
            </div>
          )}
          <div className="flex min-h-[62px] items-center px-4 py-3">
            {isRecording ? (
              <div className="flex w-full animate-pulse items-center gap-2 text-sm font-medium text-red-500">
                <span className="h-2 w-2 rounded-full bg-red-500" /> {t('正在录音...', 'Recording voice...')}
              </div>
            ) : (
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    if (isStreaming) {
                      void handleStopStreaming()
                    } else {
                      void handleSend()
                    }
                  }
                }}
                placeholder={t('输入消息', 'Type a message')}
                rows={1}
                className="max-h-40 min-h-8 w-full resize-none overflow-y-auto whitespace-pre-wrap break-words border-none bg-transparent text-[14px] leading-6 text-text-strong outline-none placeholder:text-text-muted"
              />
            )}
          </div>
          <div className="flex items-center justify-between border-t border-black/5 bg-bg-page/45 px-3 py-2">
            <div className="relative flex items-center gap-1 text-text-muted">
              <IconButton icon={<Paperclip size={16} />} onClick={user ? onOpenFiles : onRequireAuth} title={t('上传或搜索文件', 'Upload or search files')} />
              <IconButton icon={<span className="text-sm font-bold">@</span>} onClick={() => insertIntoInput('@')} title={t('插入提及符号', 'Insert mention')} />
              <IconButton icon={<Smile size={16} />} onClick={() => setShowEmojiPicker((value) => !value)} title={t('插入表情', 'Insert emoji')} />
              {showEmojiPicker && (
                <div className="absolute bottom-10 left-20 z-30 flex gap-1 rounded-xl border border-black/10 bg-white p-2 shadow-lg">
                  {quickEmojis.map((emoji) => (
                    <button
                      key={emoji}
                      type="button"
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-lg hover:bg-black/5"
                      onClick={() => {
                        insertIntoInput(emoji)
                        setShowEmojiPicker(false)
                      }}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              )}
              <button type="button" onMouseDown={startRecording} onMouseUp={stopRecording} onMouseLeave={stopRecording} className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${isRecording ? 'bg-red-100 text-red-600' : 'text-text-muted hover:bg-black/5 hover:text-text-strong'}`}>
                <Mic size={16} />
              </button>
            </div>
            <button
              type="button"
              onClick={() => (isStreaming ? handleStopStreaming() : handleSend(input))}
              disabled={(!isStreaming && !input.trim()) || isRecording}
              title={isStreaming ? t('停止当前任务', 'Stop current task') : t('发送', 'Send')}
              className={`flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors disabled:opacity-50 ${
                isStreaming ? 'bg-red-100 text-red-600 hover:bg-red-200' : 'bg-brand-100 text-brand-700 hover:bg-brand-200'
              }`}
            >
              {isStreaming ? <Square size={14} /> : <Send size={14} className="translate-x-[1px]" />}
            </button>
          </div>
        </div>
      </div>

      {confirmRequest && (
        <ConfirmModal
          toolName={confirmRequest.toolName}
          toolArgs={confirmRequest.toolArgs}
          sessionId={confirmRequest.sessionId}
          toolCallId={confirmRequest.toolCallId}
          onClose={() => setConfirmRequest(null)}
        />
      )}

      {textSelection && (
        <button
          ref={selectionActionRef}
          type="button"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            setFollowupDraft(textSelection)
            setTextSelection(null)
          }}
          className="fixed z-40 inline-flex items-center gap-1.5 rounded-lg border border-brand-200 bg-bg-card px-2.5 py-1.5 text-[12px] font-semibold text-brand-700 shadow-lg transition-colors hover:bg-brand-50"
          style={{ left: textSelection.left, top: textSelection.top }}
        >
          <MessageCircleQuestion size={14} />
          {t('追问', 'Follow up')}
        </button>
      )}

      {followupDraft && sessionId && (
        <FollowupModal
          selection={followupDraft}
          sessionId={sessionId}
          onClose={() => setFollowupDraft(null)}
          onCreated={(followup) => {
            setFollowups((items) => [...items, followup])
            setFollowupDraft(null)
          }}
        />
      )}
    </main>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[9px] uppercase tracking-[0.14em] text-text-muted">{label}</span>
      <span className="text-[12px] font-semibold text-text-strong">{value}</span>
    </div>
  )
}

function HeaderButton({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button type="button" className="flex h-8 w-8 items-center justify-center rounded-xl border border-white/65 bg-bg-card text-text-muted shadow-sm transition-colors hover:text-brand-700" {...props}>
      {children}
    </button>
  )
}

type MessageProps = {
  role: MessageData['role']
  avatar: string
  name: string
  time?: string
  content: string
  messageId: string
  followups: FollowupData[]
  onSelectText: (selection: TextSelection) => void
}

function Message({ role, avatar, name, time, content, messageId, followups, onSelectText }: MessageProps) {
  const isAgent = role === 'agent' || role === 'assistant'
  const isTool = role === 'tool'

  if (isTool) {
    return (
      <div className="flex w-full justify-center py-1">
        <div className="rounded-xl border border-brand-100 bg-bg-page/70 px-3 py-1.5 font-mono text-[11px] text-text-muted">
          Tool: {content}
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
    <div className={`flex max-w-[86%] gap-3.5 ${isAgent ? '' : 'self-start'}`}>
      <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-xl text-[13px] font-bold shadow-sm ${isAgent ? 'bg-bg-card text-brand-700 ring-1 ring-white/80' : 'bg-brand-600 text-white'}`}>
        {isAgent && avatar === 'agent' ? 'P' : avatar}
      </div>
      <div className="mt-0.5 flex w-full flex-col gap-1 overflow-hidden">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold text-text-strong">{name}</span>
          {time && <span className="text-[11px] text-text-muted">{time}</span>}
        </div>
        {thinkingContent && (
          <details className="mb-2">
            <summary className="cursor-pointer text-[11px] text-text-muted hover:text-text-strong">Thinking trace</summary>
            <div className="mt-1 rounded-xl bg-black/5 p-2 font-mono text-[11px] whitespace-pre-wrap text-text-normal">{thinkingContent}</div>
          </details>
        )}
        <div
          className="relative whitespace-pre-wrap text-[14px] leading-7 text-text-normal"
          onMouseUp={(event) => {
            if (displayContent !== content) return
            const selection = window.getSelection()
            const rawText = selection?.toString() || ''
            const range = selection?.rangeCount ? selection.getRangeAt(0) : null
            const root = event.currentTarget
            if (!rawText.trim() || !range || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return
            const before = range.cloneRange()
            before.selectNodeContents(root)
            before.setEnd(range.startContainer, range.startOffset)
            const rawStartOffset = before.toString().length
            const leadingWhitespace = rawText.length - rawText.trimStart().length
            const selectedText = rawText.trim()
            const startOffset = rawStartOffset + leadingWhitespace
            const endOffset = startOffset + selectedText.length
            const rect = range.getBoundingClientRect()
            if (!rect.width && !rect.height) return
            onSelectText({
              messageId,
              selectedText,
              startOffset,
              endOffset,
              left: Math.max(12, Math.min(window.innerWidth - 130, rect.left)),
              top: Math.min(window.innerHeight - 44, rect.bottom + 8),
            })
          }}
        >
          <AnnotatedContent content={displayContent} followups={followups} />
        </div>
      </div>
    </div>
  )
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: ReactNode
}

function IconButton({ icon, ...props }: IconButtonProps) {
  return (
    <button type="button" className="flex h-8 w-8 items-center justify-center rounded-lg text-text-muted transition-colors hover:bg-black/5 hover:text-text-strong" {...props}>
      {icon}
    </button>
  )
}

function AnnotatedContent({ content, followups }: { content: string; followups: FollowupData[] }) {
  const valid = followups
    .filter((item) => item.start_offset >= 0 && item.end_offset > item.start_offset && item.end_offset <= content.length && content.slice(item.start_offset, item.end_offset) === item.selected_text)
    .sort((a, b) => a.start_offset - b.start_offset)
  if (valid.length === 0) return <>{content || <span className="animate-pulse">...</span>}</>

  const parts: ReactNode[] = []
  let cursor = 0
  for (const item of valid) {
    if (item.start_offset < cursor) continue
    if (item.start_offset > cursor) parts.push(content.slice(cursor, item.start_offset))
    parts.push(
      <span
        key={item.id}
        title={`${item.query}\n\n${item.response}`}
        className="cursor-help rounded-sm bg-brand-100/80 decoration-brand-500 decoration-2 underline underline-offset-2"
      >
        {content.slice(item.start_offset, item.end_offset)}
      </span>,
    )
    cursor = item.end_offset
  }
  if (cursor < content.length) parts.push(content.slice(cursor))
  return <>{parts}</>
}

function FollowupModal({
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

function formatWelcomeClock(value: Date, lang: string) {
  return value.toLocaleString(lang === 'en' ? 'en-US' : 'zh-CN', {
    month: 'short',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
