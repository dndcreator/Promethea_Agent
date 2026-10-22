import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { BarChart3, Clock3, MessageCircleQuestion, Mic, Paperclip, Plus, Search, Send, Smile, Square, UsersRound } from 'lucide-react'
import ConfirmModal from './modals/ConfirmModal'
import { getActiveReasoning, getConfig, getGuestChatStatus, getMetrics, getSession, getWelcome, sendGuestChat, sendVoicePtt, stopReasoningTree, streamChat } from '../services/api'
import { useWorkbench } from '../store/WorkbenchContext'
import type { ChatAttachment, GuestChatStatus, StreamHandler } from '../services/api'
import { guestTranscript } from '../utils/guest-chat'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

import Message from './chat/ChatMessage'
import FollowupModal from './chat/FollowupModal'
import { normalizeReasoningSteps } from './chat/TurnProcess'
import type { FollowupData, MessageData, TextSelection } from './chat/types'


interface MainContentProps {
  visible?: boolean
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
  visible = true,
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
  const [multiAgent, setMultiAgent] = useState(false)
  const [multiAgentAvailable, setMultiAgentAvailable] = useState(false)
  const [guestStatus, setGuestStatus] = useState<GuestChatStatus | null>(null)
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
  const completedAgentTurns = (workbenchSnapshot?.tasks || []).flatMap((task) => task.runs || [])
    .filter((run) => ['agent_inbox', 'ambient'].includes(run.run_type || '') && run.status === 'completed' && run.session_id === sessionId)
    .map((run) => run.run_id).sort().join(':') + `:${workbenchSnapshot?.ambient?.revision || 0}`
  const syncedAgentTurnsRef = useRef('')
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
  const welcomeCycleRef = useRef('')
  const welcomeInstanceRef = useRef(crypto.randomUUID())
  const welcomeAbortRef = useRef<AbortController | null>(null)
  const selectionActionRef = useRef<HTMLButtonElement>(null)
  const observedMemoryReviewRef = useRef<string | null>(null)
  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    void getConfig(controller.signal).then(async (response) => {
      if (!response.ok) return
      const payload = await response.json()
      if (!controller.signal.aborted) setMultiAgentAvailable(payload.config?.multi_agent?.enabled === true)
    }).catch(() => {})
    return () => controller.abort()
  }, [user?.user_id])
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
    context_hint: user ? t('可以直接告诉我你想推进的任务。', 'Tell me what you want to work on.') : t('今天想聊些什么？', 'What is on your mind today?'),
    suggested_actions: user ? [
      t('开始一个新任务', 'Start a new task'),
      t('查看当前工作台状态', 'Review workspace status'),
      t('整理下一步计划', 'Plan next steps'),
    ] : [t('帮我整理一个想法', 'Help me organize an idea'), t('解释一个有趣的概念', 'Explain an interesting concept'), t('一起写一小段文字', 'Write something together')],
  }), [t, user?.agent_name])
  const quickEmojis = ['\u{1F642}', '\u{1F44D}', '\u{1F64F}', '\u{1F4A1}', '\u{2705}', '\u{1F525}']

  useEffect(() => {
    if (user) return
    const controller = new AbortController()
    void getGuestChatStatus(controller.signal).then((status) => {
      if (!controller.signal.aborted) setGuestStatus(status)
    }).catch(() => {
      if (!controller.signal.aborted) setGuestStatus({ enabled: false, available: false, max_messages: 1, max_input_chars: 0 })
    })
    return () => controller.abort()
  }, [user?.user_id])

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
    welcomeAbortRef.current?.abort()
    const controller = new AbortController()
    welcomeAbortRef.current = controller
    try {
      const res = await getWelcome(lang, `${welcomeInstanceRef.current}:${welcomeRefreshToken}`, controller.signal)
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
  }, [lang, localWelcomeFallback, user?.user_id, welcomeRefreshToken])

  useEffect(() => {
    if (!user?.user_id) {
      welcomeRequestRef.current += 1
      welcomeLoadedAtRef.current = 0
      setWelcome(null)
      welcomeCycleRef.current = ''
      welcomeAbortRef.current?.abort()
      return
    }
    if (sessionId || !visible || isStreaming) return
    const cycle = `${user.user_id}:${lang}:${welcomeRefreshToken}`
    if (welcomeCycleRef.current === cycle) return
    welcomeCycleRef.current = cycle
    void loadWelcome()
  }, [loadWelcome, user?.user_id, welcomeRefreshToken, sessionId, visible, isStreaming, lang])

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
    if (active?.sessionId === sessionId && ['failed', 'interrupted', 'waiting_confirmation'].includes(active.outcome) && completedAgentTurns === syncedAgentTurnsRef.current) return
    if (!sessionId) {
      if (!user) return
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
        syncedAgentTurnsRef.current = completedAgentTurns
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
  }, [sessionId, user, setTreeId, isStreaming, completedAgentTurns])

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
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    activeStreamRef.current = null
    setIsStreaming(false)
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
    if (!user && !guestStatus?.available) {
      onRequireAuth()
      return
    }

    const userMessage: MessageData = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: text,
      name: user?.username || t('访客', 'Guest'),
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
        name: user?.agent_name || 'Promethea',
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

    const onEvent: StreamHandler = (event, data) => {
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
          if (user) void refreshTokenMetric()
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
      }
    const onError = (error: Error) => {
        if (activeStreamRef.current !== request || viewSessionRef.current !== request.sessionId) return
        request.outcome = 'failed'
        abortControllerRef.current = null
        setIsStreaming(false)
        setChatRunning(false)
        setMessages((prev) => prev.map((item) => item.id === agentMessageId ? {
          ...item, role: 'status', content: '', runStatus: 'failed',
          error: { code: 'code' in error ? error.code : 'RUN_FAILED', message: error.message },
        } : item))
      }
    if (user) await streamChat(userMessage.content, sessionId, attachments, onEvent, onError, controller.signal, multiAgent)
    else if (guestStatus) await sendGuestChat(guestTranscript(messages, text, guestStatus), onEvent, onError, controller.signal)
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
            {sessionTitle || (sessionId ? t('对话', 'Conversation') : user ? t('新的对话', 'New conversation') : t('临时对话', 'Temporary chat'))}
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
              sessionId={sessionId}
              followups={followups.filter((item) => item.message_id === msg.id)}
              onSelectText={(selection) => { if (user) setTextSelection(selection) }}
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
        {!user && <div className="guest-chat-status" role="status"><span className={`health-dot ${guestStatus?.available ? 'healthy' : 'unknown'}`} />{guestStatus?.available ? t('临时对话', 'Temporary chat') : guestStatus ? t('游客对话暂不可用', 'Guest chat unavailable') : t('正在连接', 'Connecting')}</div>}
        <div className={`composer-surface overflow-hidden ${isRecording ? 'border-red-300 ring-2 ring-red-100' : ''}`}>
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
          <div className="composer-toolbar flex items-center justify-between px-3 py-2">
            <div className="relative flex items-center gap-1 text-text-muted">
              {user && multiAgentAvailable && (
                <label className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md px-2 text-xs text-text-muted hover:bg-black/5">
                  <UsersRound size={15} />
                  <span>{t('多 Agent', 'Multi-agent')}</span>
                  <input type="checkbox" role="switch" aria-label={t('多 Agent', 'Multi-agent')} checked={multiAgent} disabled={isStreaming} onChange={(event) => setMultiAgent(event.target.checked)} className="h-3.5 w-3.5 accent-zinc-700" />
                </label>
              )}
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
              disabled={(!isStreaming && (!input.trim() || (!user && !guestStatus?.available))) || isRecording}
              title={isStreaming ? t('停止当前任务', 'Stop current task') : t('发送', 'Send')}
              className={`composer-submit ${isStreaming ? 'is-stopping' : ''} flex h-8 w-8 cursor-pointer items-center justify-center rounded-md transition-colors disabled:opacity-50 ${
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



function formatWelcomeClock(value: Date, lang: string) {
  return value.toLocaleString(lang === 'en' ? 'en-US' : 'zh-CN', {
    month: 'short',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
