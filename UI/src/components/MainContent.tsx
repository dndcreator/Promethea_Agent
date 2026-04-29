import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link2, Mic, Paperclip, Send, Smile } from 'lucide-react'
import AgentGraph from './AgentGraph'
import { getSession, sendVoicePtt, streamChat } from '../lib/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'
import ConfirmModal from './modals/ConfirmModal'

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
}

export default function MainContent({ sessionId, setSessionId, setTreeId }: MainContentProps) {
  const { user } = useAuth()
  const { t } = useLanguage()
  const [messages, setMessages] = useState<MessageData[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const [confirmRequest, setConfirmRequest] = useState<any>(null)
  const [meta, setMeta] = useState({ tokens: 0, latency: 0, intensity: 'idle' })

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      setTreeId(null)
      return
    }
    const fetchSessionHistory = async () => {
      try {
        const res = await getSession(sessionId)
        if (res.ok) {
          const data = await res.json()
          if (data.tree_id) setTreeId(data.tree_id)
          const loadedMessages: MessageData[] = (data.messages || []).map((message: any, index: number) => {
            const role = message.role === 'assistant' ? 'agent' : message.role
            return {
              id: message.id || `${sessionId}-${index}`,
              role,
              content: message.content || '',
              name: role === 'agent' ? (user?.agent_name || 'Promethea') : (user?.username || 'You'),
            }
          })
          setMessages(loadedMessages)
        }
      } catch (error) {
        console.error('Failed to load session', error)
      }
    }
    fetchSessionHistory()
  }, [sessionId, user, setTreeId])

  const handleSend = async (text: string = input) => {
    if (!text.trim() || isStreaming || !user) return

    const userMessage: MessageData = {
      id: `${Date.now()}-user`,
      role: 'user',
      content: text,
      name: user.username || 'You',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }
    const agentMessageId = `${Date.now()}-agent`

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
    setIsStreaming(true)

    const startTime = Date.now()

    await streamChat(
      userMessage.content,
      sessionId,
      (event, data) => {
        if (event === 'text') {
          const chunk = typeof data === 'string' ? data : String(data?.content || '')
          setMessages((prev) => prev.map((m) => (m.id === agentMessageId ? { ...m, content: m.content + chunk } : m)))
        } else if (event === 'tool_call' || event === 'tool_start') {
          setMessages((prev) => [...prev, { id: `${Date.now()}-tool`, role: 'tool', content: `Running tool: ${data.tool_name || data.name || 'tool'}...` }])
        } else if (event === 'tool_result') {
          setMessages((prev) => [...prev, { id: `${Date.now()}-tool`, role: 'tool', content: `Tool ${data.tool_name || data.name || 'tool'} completed.` }])
        } else if (event === 'reasoning_meta') {
          if (data?.tree_id) setTreeId(data.tree_id)
          setMeta((prev) => ({ ...prev, tokens: data.total_tokens || prev.tokens, intensity: data.status || 'thinking' }))
        } else if (event === 'done') {
          setIsStreaming(false)
          if (data?.session_id) setSessionId(data.session_id)
          if (data?.tree_id) setTreeId(data.tree_id)
          setMeta((prev) => ({ ...prev, latency: (Date.now() - startTime) / 1000, intensity: 'idle' }))
          if (data?.status === 'needs_confirmation') {
            setConfirmRequest({
              sessionId: data.session_id || sessionId,
              toolCallId: data.tool_call_id,
              toolName: data.tool_name,
              toolArgs: typeof data.args === 'string' ? data.args : JSON.stringify(data.args, null, 2),
            })
          }
        } else if (event === 'error') {
          setIsStreaming(false)
          const message = typeof data === 'string' ? data : data?.content || 'Unknown error'
          setMessages((prev) => [...prev, { id: `${Date.now()}-error`, role: 'agent', content: `Error: ${message}` }])
        }
      },
      (error) => {
        setIsStreaming(false)
        setMessages((prev) => [...prev, { id: `${Date.now()}-error`, role: 'agent', content: `Error: ${error.message}` }])
      },
    )
  }

  const startRecording = async () => {
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
        }
      }
      mediaRecorderRef.current.stop()
      mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop())
      setIsRecording(false)
    }
  }

  return (
    <main className="flex-1 flex flex-col h-full bg-white/40 backdrop-blur-md rounded-2xl border border-white shadow-sm overflow-hidden relative">
      <header className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-white/30">
        <h1 className="text-lg font-bold text-text-strong flex items-center gap-2">
          {sessionId ? `${t('会话', 'Session')}: ${sessionId.slice(0, 8)}...` : t('新的对话', 'New Conversation')} <Link2 size={16} className="text-text-muted" />
        </h1>
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-text-muted">{t('思考强度', 'Thinking')}</span>
            <div className="flex gap-0.5 h-3 items-end">
              <span className={`w-1 bg-brand-200 h-1/3 rounded-sm ${isStreaming ? 'animate-pulse' : ''}`}></span>
              <span className={`w-1 bg-brand-300 h-2/3 rounded-sm ${isStreaming ? 'animate-pulse delay-75' : ''}`}></span>
              <span className={`w-1 bg-brand-400 h-full rounded-sm ${isStreaming ? 'animate-pulse delay-150' : ''}`}></span>
            </div>
            <span className="font-medium text-brand-600 ml-1">{meta.intensity === 'idle' ? t('闲置', 'idle') : t('活跃', 'active')}</span>
          </div>
          <Metric label="Tokens" value={meta.tokens > 1000 ? `${(meta.tokens / 1000).toFixed(1)}k` : String(meta.tokens)} />
          <Metric label="Latency" value={meta.latency ? `${meta.latency.toFixed(1)}s` : '-'} />
          <div className="flex items-center gap-2 px-3 py-1.5 bg-green-50 text-green-700 rounded-full border border-green-100 text-xs font-medium">
            <span className="w-2 h-2 rounded-full bg-green-500"></span>
            {t('健康状态', 'Healthy')}
          </div>
          <button className="text-text-muted hover:text-text-strong" onClick={() => setSessionId(null)} title={t('新建对话', 'New Chat')}>
            <span className="text-xl leading-none">+</span>
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 relative">
        {messages.length === 0 && (
          <div className="text-center text-text-muted mt-10">
            <h2 className="text-2xl font-bold text-text-strong mb-2">{t('今天想让 Agent 做什么？', 'How can I help you today?')}</h2>
            <p>{t(`你的请求会由 ${user?.agent_name || 'Promethea'} 处理。`, `Your requests will be processed by ${user?.agent_name || 'Promethea'}.`)}</p>
          </div>
        )}

        {messages.map((msg) => (
          <Message key={msg.id} role={msg.role} avatar={msg.role === 'agent' || msg.role === 'assistant' ? 'agent' : (msg.name?.charAt(0).toUpperCase() || 'U')} name={msg.name || msg.role} time={msg.time} content={msg.content} />
        ))}

        {messages.length === 0 && (
          <div className="w-full h-[300px] bg-white/50 rounded-2xl border border-brand-50 shadow-inner overflow-hidden mb-4 relative z-10 shrink-0 opacity-70 mt-auto">
            <AgentGraph />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 bg-white/60 border-t border-white shadow-[0_-10px_40px_rgba(0,0,0,0.02)] relative z-20">
        <div className={`bg-white rounded-2xl border ${isRecording ? 'border-red-300 ring-2 ring-red-100' : 'border-black/5'} shadow-sm overflow-hidden focus-within:ring-2 focus-within:ring-brand-100 transition-shadow`}>
          <div className="px-4 py-3 min-h-[60px] flex items-center">
            {isRecording ? (
              <div className="w-full flex items-center gap-2 text-red-500 font-medium text-sm animate-pulse">
                <span className="w-2 h-2 rounded-full bg-red-500"></span> {t('正在录音...', 'Recording voice...')}
              </div>
            ) : (
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={t('输入你的消息，支持 @ 提及 / 命令 / 快捷操作', 'Type a message, mention @, or enter a command')}
                className="w-full bg-transparent border-none outline-none text-sm text-text-strong placeholder:text-text-muted"
              />
            )}
          </div>
          <div className="px-3 py-2 bg-gray-50/50 flex items-center justify-between border-t border-black/5">
            <div className="flex items-center gap-1 text-text-muted">
              <IconButton icon={<Paperclip size={16} />} />
              <IconButton icon={<span className="font-bold text-sm">@</span>} />
              <IconButton icon={<Smile size={16} />} />
              <button type="button" onMouseDown={startRecording} onMouseUp={stopRecording} onMouseLeave={stopRecording} className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors ${isRecording ? 'bg-red-100 text-red-600' : 'hover:bg-black/5 text-text-muted hover:text-text-strong'}`}>
                <Mic size={16} />
              </button>
            </div>
            <button type="button" onClick={() => handleSend(input)} disabled={isStreaming || !input.trim() || isRecording} className="w-8 h-8 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center hover:bg-brand-100 transition-colors disabled:opacity-50 cursor-pointer">
              <Send size={14} className="translate-x-[1px]" />
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
    </main>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[10px] text-text-muted">{label}</span>
      <span className="text-xs font-semibold">{value}</span>
    </div>
  )
}

function Message({ role, avatar, name, time, content }: any) {
  const isAgent = role === 'agent' || role === 'assistant'
  const isTool = role === 'tool'

  if (isTool) {
    return (
      <div className="flex justify-center w-full my-2">
        <div className="px-3 py-1.5 bg-gray-100 rounded-lg text-xs font-mono text-gray-500 border border-gray-200">
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
    <div className={`flex gap-4 max-w-[85%] ${isAgent ? '' : 'self-start'}`}>
      <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm font-bold shadow-sm overflow-hidden ${isAgent ? 'bg-white text-brand-600' : 'bg-gradient-to-tr from-blue-500 to-indigo-400 text-white'}`}>
        {isAgent && avatar === 'agent' ? 'P' : avatar}
      </div>
      <div className="flex flex-col gap-1 mt-1 w-full overflow-hidden">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold text-text-strong">{name}</span>
          {time && <span className="text-xs text-text-muted">{time}</span>}
        </div>
        {thinkingContent && (
          <details className="mb-2">
            <summary className="text-xs text-text-muted cursor-pointer hover:text-text-strong">Thinking trace</summary>
            <div className="mt-1 p-2 bg-black/5 rounded-lg text-xs text-text-normal font-mono whitespace-pre-wrap">{thinkingContent}</div>
          </details>
        )}
        <div className="text-sm text-text-normal leading-relaxed whitespace-pre-wrap">
          {displayContent || <span className="animate-pulse">...</span>}
        </div>
      </div>
    </div>
  )
}

function IconButton({ icon, ...props }: { icon: ReactNode }) {
  return (
    <button type="button" className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-black/5 transition-colors text-text-muted hover:text-text-strong" {...props}>
      {icon}
    </button>
  )
}
