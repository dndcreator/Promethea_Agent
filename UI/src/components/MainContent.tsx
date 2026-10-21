import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { BarChart3, BrainCircuit, ChevronDown, ChevronRight, CircleDot, Clock3, MessageCircleQuestion, Mic, Paperclip, Plus, Search, Send, Smile, Square, X } from 'lucide-react'
import ConfirmModal from './modals/ConfirmModal'
import MessageContent from './MessageContent'
import { sourceSelection } from '../utils/message-links'
import { getActiveReasoning, getMetrics, getReasoningTree, getSession, getWelcome, sendFollowup, sendVoicePtt, stopReasoningTree, streamChat } from '../services/api'
import { useWorkbench } from '../store/WorkbenchContext'
import type { ChatAttachment, WorkbenchActivity } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

interface MessageData {
  id: string
  role: 'user' | 'agent' | 'assistant' | 'tool' | 'status'
  content: string
  name?: string
  time?: string
  reasoningTreeId?: string
  conversationTurnId?: string
  reasoningSteps?: ReasoningStep[]
  runStatus?: string
  error?: Record<string, unknown>
}

type ReasoningStep = {
  step_id: string
  source: string
  content: string
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
  memoryReviewId?: string | null
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

function tokenCountFromPayload(payload: StreamPayload): number | null {
  const usage = payload.usage && typeof payload.usage === 'object' ? payload.usage : {}
  const candidates = [
    payload.total_tokens,
    payload.token_count,
    payload.tokens,
    usage.total_tokens,
    usage.total,
  ]
  for (const value of candidates) {
    if (value === null || value === undefined || value === '') continue
    const numeric = Number(value)
    if (Number.isFinite(numeric) && numeric >= 0) return numeric
  }
  if ([payload.prompt_tokens, usage.prompt_tokens, payload.completion_tokens, usage.completion_tokens].every((value) => value === null || value === undefined)) return null
  const prompt = Number(payload.prompt_tokens ?? usage.prompt_tokens ?? 0)
  const completion = Number(payload.completion_tokens ?? usage.completion_tokens ?? 0)
  const total = prompt + completion
  return Number.isFinite(total) && total >= 0 ? total : null
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
  const { snapshot: workbenchSnapshot } = useWorkbench()
  const pendingReviewId = memoryReviewId || workbenchSnapshot?.memory_proposals?.find((proposal) => proposal.session_id === sessionId)?.proposal_id || null
  const processActivities = workbenchSnapshot?.timeline || []
  const [meta, setMeta] = useState<{ tokens: number | null; latency: number | null }>({ tokens: null, latency: null })
  const [totalTokens, setTotalTokens] = useState<number | null>(null)
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const usageRef = useRef<HTMLDetailsElement>(null)
  const followOutputRef = useRef(true)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const activeStreamRef = useRef<{ controller: AbortController; sessionId: string | null; outcome: string } | null>(null)
  const viewSessionRef = useRef(sessionId)
  viewSessionRef.current = sessionId
  const activeTreeIdRef = useRef<string | null>(null)
  const welcomeLoadedAtRef = useRef(0)
  const welcomeRequestRef = useRef(0)
  const selectionActionRef = useRef<HTMLButtonElement>(null)
  const observedMemoryReviewRef = useRef<string | null>(null)
  useEffect(() => () => {
    activeStreamRef.current?.controller.abort()
    activeStreamRef.current = null
    abortControllerRef.current = null
    mediaRecorderRef.current?.stream.getTracks().forEach((track) => track.stop())
  }, [])
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
    observedMemoryReviewRef.current = pendingReviewId
    if (pendingReviewId) {
      setMemoryNotice({
        text: t('检测到记忆冲突，等待确认。', 'Memory conflict detected; review is needed.'),
        requiresReview: true,
      })
    } else if (previousReviewId) {
      setMemoryNotice((current) => current?.requiresReview ? null : current)
    }
  }, [pendingReviewId, t])

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
    const closeUsage = (event: PointerEvent) => {
      if (usageRef.current && !usageRef.current.contains(event.target as Node)) usageRef.current.open = false
    }
    document.addEventListener('pointerdown', closeUsage)
    return () => document.removeEventListener('pointerdown', closeUsage)
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
    const active = activeStreamRef.current
    if (active?.outcome === 'running' && active.sessionId !== sessionId) {
      active.controller.abort()
      activeStreamRef.current = null
      setIsStreaming(false)
      setChatRunning(false)
      return
    }
    if (isStreaming) {
      return
    }
    if (active?.sessionId === sessionId && ['failed', 'interrupted', 'waiting_confirmation'].includes(active.outcome)) return
    if (!sessionId) {
      setMessages([])
      setSessionTitle('')
      setTreeId(null)
      setMemoryNotice(null)
      return
    }
    let cancelled = false
    const fetchSessionHistory = async () => {
      try {
        const res = await getSession(sessionId)
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        setTreeId(data.tree_id || null)
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
            reasoningTreeId: message.reasoning_tree_id || undefined,
            conversationTurnId: message.conversation_turn_id || undefined,
            reasoningSteps: normalizeReasoningSteps(message.reasoning_steps),
            runStatus: message.run_status,
            error: message.error,
          }
        })
        setMessages(loadedMessages)
      } catch (error) {
        console.error('Failed to load session', error)
      }
    }
    fetchSessionHistory()
    return () => { cancelled = true }
  }, [sessionId, user, setTreeId, isStreaming])

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
    setMeta({ tokens: null, latency: null })
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
      const tokens = llm.total_tokens === undefined || llm.total_tokens === null ? null : Number(llm.total_tokens)
      if (tokens !== null && Number.isFinite(tokens) && tokens >= 0) {
        setTotalTokens(tokens)
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
    if (activeStreamRef.current) activeStreamRef.current.outcome = 'interrupted'
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsStreaming(false)
    setChatRunning(false)
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-stopped`,
        role: 'status',
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
    setMeta({ tokens: null, latency: null })
    setChatRunning(true)
    followOutputRef.current = true
    setIsNearBottom(true)
    const controller = new AbortController()
    abortControllerRef.current = controller
    const request = { controller, sessionId, outcome: 'running' }
    activeStreamRef.current = request

    const startTime = Date.now()

    await streamChat(
      userMessage.content,
      sessionId,
      attachments,
      (event, data) => {
        if (activeStreamRef.current !== request || viewSessionRef.current !== request.sessionId) return
        const payload = asStreamPayload(data)
        if (event === 'text') {
          const chunk = typeof data === 'string' ? data : String(payload.content || '')
          setMessages((prev) => prev.map((m) => (m.id === agentMessageId ? { ...m, content: m.content + chunk } : m)))
          return
        }
        if (event === 'tool_call' || event === 'tool_start') {
          return
        }
        if (event === 'tool_result') {
          return
        }
        if (event === 'session_started') {
          if (payload.session_id) {
            request.sessionId = String(payload.session_id)
            viewSessionRef.current = request.sessionId
            setSessionId(request.sessionId)
          }
          if (payload.conversation_turn_id) {
            setMessages((prev) => prev.map((message) => (
              message.id === agentMessageId
                ? { ...message, conversationTurnId: String(payload.conversation_turn_id) }
                : message
            )))
          }
          return
        }
        if (event === 'reasoning') {
          const stepId = String(payload.step_id || 'provider')
          const delta = String(payload.delta || '')
          if (!delta) return
          setMessages((prev) => prev.map((message) => {
            if (message.id !== agentMessageId) return message
            const steps = [...(message.reasoningSteps || [])]
            const index = steps.findIndex((step) => step.step_id === stepId)
            if (index >= 0) {
              steps[index] = { ...steps[index], content: steps[index].content + delta }
            } else {
              steps.push({ step_id: stepId, source: String(payload.source || 'provider'), content: delta })
            }
            return {
              ...message,
              conversationTurnId: String(payload.conversation_turn_id || message.conversationTurnId || '') || undefined,
              reasoningSteps: steps,
            }
          }))
          return
        }
        if (event === 'reasoning_meta') {
          if (payload.tree_id) {
            activeTreeIdRef.current = String(payload.tree_id)
            setTreeId(String(payload.tree_id))
            setMessages((prev) => prev.map((message) => (
              message.id === agentMessageId
                ? { ...message, reasoningTreeId: String(payload.tree_id) }
                : message
            )))
          }
          const tokens = tokenCountFromPayload(payload)
          setMeta((prev) => ({ ...prev, tokens: tokens ?? prev.tokens }))
          return
        }
        if (event === 'memory_visibility') {
          const notice = memoryNoticeInfoFromPayload(payload, t)
          if (notice) setMemoryNotice(notice)
          return
        }
        if (event === 'done') {
          request.outcome = payload.status === 'needs_confirmation' ? 'waiting_confirmation' : 'completed'
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
          setMeta((prev) => ({ ...prev, tokens: doneTokens ?? prev.tokens, latency: (Date.now() - startTime) / 1000 }))
          void refreshTokenMetric()
          if (payload.session_id && payload.status !== 'needs_confirmation') {
            void getSession(String(payload.session_id))
              .then(async (res) => {
                if (!res.ok) return
                const data = await res.json()
                if (activeStreamRef.current !== request || viewSessionRef.current !== request.sessionId) return
                const sessionInfo = data.session_info || data
                if (sessionInfo.title) setSessionTitle(String(sessionInfo.title))
                if (Array.isArray(sessionInfo.followups)) setFollowups(sessionInfo.followups)
                if (Array.isArray(data.messages)) {
                  const loadedMessages: MessageData[] = data.messages.map((message: any, index: number) => {
                    const role = message.role === 'assistant' ? 'agent' : message.role
                    return {
                      id: message.id || `${payload.session_id}-${index}`,
                      role,
                      content: message.content || '',
                      name: role === 'agent' ? user?.agent_name || 'Promethea' : user?.username || 'You',
                      reasoningTreeId: message.reasoning_tree_id || undefined,
                      conversationTurnId: message.conversation_turn_id || undefined,
                      reasoningSteps: normalizeReasoningSteps(message.reasoning_steps),
                      runStatus: message.run_status,
                      error: message.error,
                    }
                  })
                  setMessages(loadedMessages)
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
          request.outcome = 'failed'
          abortControllerRef.current = null
          setIsStreaming(false)
          setChatRunning(false)
          const message = typeof data === 'string' ? data : payload.content || 'Unknown error'
          setMessages((prev) => prev.map((item) => item.id === agentMessageId ? { ...item, role: 'status', content: '', runStatus: 'failed', error: { ...payload.error_detail, message } } : item))
        }
      },
      (error) => {
        if (activeStreamRef.current !== request || viewSessionRef.current !== request.sessionId) return
        request.outcome = 'failed'
        abortControllerRef.current = null
        setIsStreaming(false)
        setChatRunning(false)
        setMessages((prev) => prev.map((item) => item.id === agentMessageId ? {
          ...item, role: 'status', content: '', runStatus: 'failed',
          error: { code: 'code' in error ? error.code : 'RUN_FAILED', message: error.message },
        } : item))
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
    <main className="chat-main relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-white">
      <header className="chat-heading flex items-center justify-between border-b border-black/5 px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 truncate font-display text-[15px] font-semibold text-text-strong">
            {sessionId ? (sessionTitle || t('对话', 'Conversation')) : t('新的对话', 'New conversation')}
          </h1>
        </div>
        <div className="ml-2 flex shrink-0 items-center gap-1.5 sm:gap-4">
          <details ref={usageRef} className="chat-usage" onKeyDown={(event) => { if (event.key === 'Escape') event.currentTarget.open = false }}>
            <summary title={t('查看用量', 'View usage')} aria-label={t('查看用量', 'View usage')}><BarChart3 size={16} /></summary>
            <div className="chat-usage-panel">
              <Metric label={t('本次 Token', 'Request tokens')} value={meta.tokens === null ? '-' : meta.tokens.toLocaleString()} />
              <Metric label={t('累计 Token', 'Total tokens')} value={totalTokens === null ? '-' : totalTokens.toLocaleString()} />
              <Metric label={t('本次耗时', 'Request duration')} value={meta.latency === null ? '-' : `${meta.latency.toFixed(1)}s`} />
            </div>
          </details>
          <HeaderButton onClick={onOpenSearch} title={t('搜索会话和文件', 'Search sessions and files')}>
            <Search size={15} />
          </HeaderButton>
          <HeaderButton onClick={handleNewChat} title={t('新建对话', 'New chat')}>
            <Plus size={16} />
          </HeaderButton>
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

      <div ref={messagesScrollRef} onScroll={handleMessagesScroll} className="chat-messages relative flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="chat-message-column flex flex-col gap-6">
          {messages.length === 0 && sessionId && <p className="py-6 text-sm text-text-muted">{t('此会话没有已保存的消息。', 'No messages were saved in this session.')}</p>}
          {messages.length === 0 && !sessionId && (
            <div className="chat-welcome text-left text-text-muted">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="text-[12px] font-semibold text-brand-600">
                  {user?.agent_name || 'Promethea'}
                </div>
                <span className="inline-flex items-center gap-1.5 text-[11px] text-text-muted">
                  <Clock3 size={12} />
                  {formatWelcomeClock(welcomeClock, lang)}
                </span>
              </div>
              <h2 className="mb-3 max-w-[720px] font-display text-[26px] font-semibold leading-snug text-text-strong">
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
                    className="welcome-suggestion border-b border-black/10 py-2 text-left text-[12px] font-medium text-text-normal transition-colors hover:border-brand-400 hover:text-brand-700"
                  >
                    {action}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, index) => (
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
              reasoningTreeId={msg.reasoningTreeId}
              reasoningSteps={msg.reasoningSteps}
              runStatus={msg.runStatus}
              error={msg.error}
              onRetry={index > 0 && messages[index - 1].role === 'user' ? () => void handleSend(messages[index - 1].content) : undefined}
              processActivities={processActivities.filter((activity) => (
                Boolean(msg.conversationTurnId)
                && activity.conversation_turn_id === msg.conversationTurnId
              ))}
              onOpenWorkbench={onOpenWorkbench}
              processRunning={isStreaming && index === messages.length - 1 && (msg.role === 'agent' || msg.role === 'assistant')}
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

      <div className="chat-composer relative z-20 bg-white px-4 pb-4 pt-2 sm:px-6">
        <div className={`overflow-hidden rounded-lg border bg-bg-card shadow-sm transition-shadow focus-within:ring-2 ${isRecording ? 'border-red-300 ring-2 ring-red-100' : 'border-border-soft focus-within:ring-brand-100'}`}>
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
          onClose={(_approved, result) => {
            if (result.status === 'needs_confirmation') {
              setConfirmRequest({
                sessionId: result.session_id || confirmRequest.sessionId,
                toolCallId: result.tool_call_id,
                toolName: result.tool_name,
                toolArgs: JSON.stringify(result.args || {}, null, 2),
              })
              return
            }
            setConfirmRequest(null)
            void getSession(confirmRequest.sessionId).then(async (response) => {
              if (!response.ok) return
              const data = await response.json()
              if (!Array.isArray(data.messages)) return
              setMessages(data.messages.map((message: any) => ({
                id: message.id,
                role: message.role === 'assistant' ? 'agent' : message.role,
                content: message.content || '',
                name: message.role === 'assistant' ? user?.agent_name || 'Promethea' : user?.username || 'You',
                reasoningTreeId: message.reasoning_tree_id || undefined,
                conversationTurnId: message.conversation_turn_id || undefined,
                reasoningSteps: normalizeReasoningSteps(message.reasoning_steps),
                runStatus: message.run_status,
                error: message.error,
              })))
            }).catch(console.error)
          }}
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
  reasoningTreeId?: string
  reasoningSteps?: ReasoningStep[]
  processActivities?: WorkbenchActivity[]
  onOpenWorkbench: () => void
  processRunning?: boolean
  runStatus?: string
  error?: Record<string, unknown>
  onRetry?: () => void
}

function Message({ role, avatar, name, time, content, messageId, followups, onSelectText, reasoningTreeId, reasoningSteps = [], processActivities = [], onOpenWorkbench, processRunning = false, runStatus, error, onRetry }: MessageProps) {
  const { t } = useLanguage()
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
    <div className={`flex max-w-[86%] gap-3.5 ${isAgent ? '' : 'self-start'}`}>
      <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-xl text-[13px] font-bold shadow-sm ${isAgent ? 'bg-bg-card text-brand-700 ring-1 ring-white/80' : 'bg-brand-600 text-white'}`}>
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
          <MessageContent content={displayContent} followups={followups} />
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

type ReasoningNodeView = {
  id: string
  title: string
  summary: string
  status: string
}

function TurnProcess({
  treeId,
  reasoningSteps,
  activities,
  running,
  onOpenWorkbench,
}: {
  treeId?: string
  reasoningSteps: ReasoningStep[]
  activities: WorkbenchActivity[]
  running: boolean
  onOpenWorkbench: () => void
}) {
  const { lang, t } = useLanguage()
  const [tree, setTree] = useState<any>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    let interval: number | undefined
    const refresh = async () => {
      if (!treeId) {
        if (!cancelled) setTree(null)
        return
      }
      try {
        const response = await getReasoningTree(treeId)
        if (response.ok && !cancelled) setTree(await response.json())
      } catch {
        // The final answer remains usable when process projection is unavailable.
      }
    }
    void refresh()
    if (running && treeId) interval = window.setInterval(refresh, 1500)
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [treeId, running])

  const nodes: ReasoningNodeView[] = Array.isArray(tree?.nodes)
    ? tree.nodes
        .filter((node: any) => {
          const kind = String(node?.kind || '').toLowerCase()
          const status = String(node?.status || '').toLowerCase()
          return kind !== 'root' && status !== 'pruned'
        })
        .sort((left: any, right: any) => Number(left.updated_at || 0) - Number(right.updated_at || 0))
        .map((node: any, index: number) => ({
          id: String(node?.node_id || index),
          title: reasoningNodeTitle(node, t),
          summary: readableProcessSummary(node?.summary || node?.observation),
          status: String(node?.status || '').toLowerCase(),
        }))
    : []
  const latest = nodes[nodes.length - 1]
  const live = running
  const visibleActivities = activities.filter((activity) => !(treeId && activity.kind === 'reasoning'))
  const activityCount = visibleActivities.reduce((total, activity) => total + Number(activity.occurrence_count || 1), 0)
  const counts = [
    reasoningSteps.length > 0 ? t(`${reasoningSteps.length} 段思考`, `${reasoningSteps.length} thoughts`) : '',
    nodes.length > 0 ? t(`${nodes.length} 个推理步骤`, `${nodes.length} reasoning steps`) : '',
    activityCount > 0 ? t(`${activityCount} 次操作`, `${activityCount} actions`) : '',
  ].filter(Boolean)
  const label = live
    ? t('正在思考', 'Thinking')
    : counts.length > 0
      ? counts.join(' · ')
      : t('已思考', 'Thought for a while')
  const latestLabel = visibleActivities.length > 0
    ? localizedProcessActivity(visibleActivities[visibleActivities.length - 1], lang)
    : latest?.title || compactProcessText(reasoningSteps[reasoningSteps.length - 1]?.content || '', 90)

  return (
    <div className="mb-2 mt-1 overflow-hidden border-l-2 border-brand-200 pl-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-1 text-left text-[12px] text-text-muted transition-colors hover:text-text-strong"
      >
        <BrainCircuit size={13} className={live ? 'text-brand-600' : ''} />
        <span className="font-medium">{label}</span>
        {!open && latestLabel && <span className="min-w-0 flex-1 truncate">{latestLabel}</span>}
        <span className="ml-auto shrink-0">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
      </button>
      {open && (
        <div className="max-h-80 overflow-y-auto pb-2 pt-1 pr-2">
          {reasoningSteps.length === 0 && nodes.length === 0 && visibleActivities.length === 0 ? (
            <div className="flex items-center gap-2 py-1 text-[12px] text-text-muted">
              <CircleDot size={11} className={live ? 'animate-pulse text-brand-600' : ''} />
              <span>{label}</span>
            </div>
          ) : (
            <>
              {reasoningSteps.map((step, index) => (
                <div key={`${step.step_id}:${index}`} className="relative py-1.5 pl-5 text-[12px] leading-5">
                  <CircleDot size={10} className={`absolute left-0 top-3 ${live && index === reasoningSteps.length - 1 ? 'animate-pulse text-brand-600' : 'text-text-muted'}`} />
                  <ProcessText title={`${t('模型思考', 'Model reasoning')} ${index + 1}`} content={step.content} />
                </div>
              ))}
              {nodes.map((node, index) => {
              const active = live && (
                ['running', 'active', 'pending', 'waiting_tool', 'waiting_human'].includes(node.status)
                || index === nodes.length - 1
              )
              return (
                <div key={node.id} className="relative py-1.5 pl-5 text-[12px] leading-5">
                  <CircleDot size={10} className={`absolute left-0 top-3 ${active ? 'animate-pulse text-brand-600' : 'text-text-muted'}`} />
                  <ProcessText title={node.title} content={node.summary} />
                </div>
              )
              })}
              {visibleActivities.map((activity) => {
                const title = localizedProcessActivity(activity, lang)
                const count = Number(activity.occurrence_count || 1)
                return (
                  <button
                    key={activity.activity_id}
                    type="button"
                    onClick={onOpenWorkbench}
                    className="flex w-full items-center gap-2 py-1.5 pl-5 text-left text-[12px] leading-5 text-text-normal hover:text-brand-700"
                  >
                    <CircleDot size={10} className="shrink-0 text-text-muted" />
                    <span className="min-w-0 flex-1 truncate">{title}</span>
                    {count > 1 && <span className="shrink-0 font-mono text-[10px] text-text-muted">x{count}</span>}
                    <ChevronRight size={12} className="shrink-0 text-text-muted" />
                  </button>
                )
              })}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function ProcessText({ title, content }: { title: string; content: string }) {
  return (
    <details className="min-w-0 py-1 text-[12px] leading-5">
      <summary className="cursor-pointer text-text-normal">
        <span className="font-medium">{title}</span>
        {content && <span className="mt-1 line-clamp-2 break-words text-text-muted">{content.slice(0, 200)}</span>}
      </summary>
      {content && <div className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words border-l border-black/10 pl-2 text-text-muted">{content}</div>}
    </details>
  )
}

function readableProcessSummary(value: unknown): string {
  if (typeof value !== 'string') return ''
  try {
    const parsed = JSON.parse(value)
    return typeof parsed === 'string' ? parsed : String(parsed?.summary || parsed?.message || parsed?.text || '')
  } catch { return value }
}

function normalizeReasoningSteps(value: unknown): ReasoningStep[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map((item, index) => ({
      step_id: String(item.step_id || `reasoning-${index}`),
      source: String(item.source || 'provider'),
      content: String(item.content || ''),
    }))
    .filter((item) => item.content.trim().length > 0)
}

function localizedProcessActivity(activity: WorkbenchActivity, lang: 'zh' | 'en'): string {
  return String(activity.subject_i18n?.[lang] || activity.subject || activity.summary_i18n?.[lang] || activity.summary || '')
}

function compactProcessText(value: string, maxLength: number): string {
  const text = value.replace(/\s+/g, ' ').trim()
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text
}

function reasoningNodeTitle(node: any, t: (zh: string, en: string) => string): string {
  const kind = String(node?.kind || '').toLowerCase()
  const metadata = node?.metadata && typeof node.metadata === 'object' ? node.metadata : {}
  if (kind === 'memory') {
    const query = compactProcessText(String(metadata.query || ''), 90)
    return query ? `${t('召回记忆', 'Recall memory')} · ${query}` : compactProcessText(String(node.title || t('召回记忆', 'Recall memory')), 120)
  }
  if (kind === 'tool') {
    const identity = [metadata.service_name, metadata.tool_name].filter(Boolean).join('.')
    return identity ? `${t('调用工具', 'Use tool')} · ${identity}` : compactProcessText(String(node.title || t('调用工具', 'Use tool')), 120)
  }
  if (kind === 'think') return t('分析当前步骤', 'Analyze current step')
  return compactProcessText(String(node?.title || t('分析', 'Reasoning')), 120)
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
