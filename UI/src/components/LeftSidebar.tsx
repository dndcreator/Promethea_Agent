import { useEffect, useState } from 'react'
import { ChevronRight, LogOut, X } from 'lucide-react'
import { authFetch } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'
import AvatarSurface from './avatar/AvatarSurface'
import FeatureSurface from './FeatureSurface'

type Status = { model: string; backend: string; apiReady: boolean | null; memoryReady: boolean | null; queue: string }
const EMPTY_STATUS: Status = { model: '-', backend: 'Memory', apiReady: null, memoryReady: null, queue: '-' }

export default function LeftSidebar({ onSignIn, chatRunning }: { onSignIn: () => void; chatRunning: boolean }) {
  const { user, logout } = useAuth()
  const { t } = useLanguage()
  const [status, setStatus] = useState<Status>(EMPTY_STATUS)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    if (!user) return () => controller.abort()
    const read = async (path: string) => {
      try {
        const response = await authFetch(path, { signal: controller.signal })
        return response.ok ? await response.json() : null
      } catch { return null }
    }
    const load = async () => {
      const [runtime, memory, secrets] = await Promise.all([read('/api/status'), read('/api/health/memory'), read('/api/config/secrets')])
      if (controller.signal.aborted) return
      const sync = runtime?.memory_sync || {}
      const backend = String(memory?.active_backend || memory?.configured_backend || 'Memory')
      setStatus({
        model: String(secrets?.secrets?.api?.model || '-'), backend: backend.toLowerCase() === 'neo4j' ? 'Neo4j' : backend,
        apiReady: runtime ? Boolean(runtime.conversation_ready) : null, memoryReady: memory ? Boolean(memory.ready) : null,
        queue: runtime ? String(sync.pending || sync.queued || 0) : '-',
      })
    }
    void load()
    const timer = window.setInterval(() => void load(), 30000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [user?.user_id])
  const dot = (ready: boolean | null) => <span className={`health-dot ${ready === null ? 'unknown' : ready ? 'healthy' : 'unavailable'}`} />
  return <div className="agent-identity-dock">
    <button type="button" className="agent-identity-trigger" onClick={() => user ? setOpen(true) : onSignIn()} aria-label={t('展开 Agent 形象', 'Expand agent avatar')}>
      <AvatarSurface compact active={Boolean(user)} state={chatRunning ? 'thinking' : 'idle'} />
      <span className="agent-name"><strong>{user?.agent_name || 'Promethea'}</strong><span>{chatRunning ? t('思考中', 'Thinking') : t('空闲', 'Idle')}</span></span><ChevronRight size={14} />
    </button>
    <div className="agent-runtime-status"><span className="model-name" title={status.model}>{status.model}</span><span title={status.apiReady ? t('API 正常', 'API ready') : t('API 未就绪', 'API unavailable')}>{dot(status.apiReady)}API</span><span title={status.memoryReady ? t('记忆已连接', 'Memory ready') : t('记忆未连接', 'Memory unavailable')}>{dot(status.memoryReady)}{status.backend}</span></div>
    <div className="agent-account"><span>{user?.username || t('访客', 'Guest')}</span><span>{t('队列', 'Queue')} {status.queue}</span>{user ? <button type="button" onClick={() => void logout()} aria-label={t('退出登录', 'Sign out')} title={t('退出登录', 'Sign out')}><LogOut size={12} /></button> : <button type="button" onClick={onSignIn}>{t('登录', 'Sign in')}</button>}</div>
    {open && <FeatureSurface size="compact" onClose={() => setOpen(false)} label={t('Agent 形象', 'Agent avatar')}><div className="avatar-view"><header><strong>{user?.agent_name || 'Promethea'}</strong><button type="button" className="icon-button" title={t('关闭', 'Close')} onClick={() => setOpen(false)}><X size={17} /></button></header><AvatarSurface spacious active={Boolean(user)} state={chatRunning ? 'thinking' : 'idle'} /></div></FeatureSurface>}
  </div>
}
