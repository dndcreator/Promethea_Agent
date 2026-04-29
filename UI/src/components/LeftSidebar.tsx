import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Activity, Beaker, Database, LogOut, MessageSquare, Search, Settings } from 'lucide-react'
import { useAuth } from '../store/AuthContext'
import { authFetch } from '../lib/api'
import { useLanguage } from '../store/LanguageContext'

interface LeftSidebarProps {
  onOpenModal: (modal: string) => void
  onSelectSession: (id: string) => void
}

type StatusState = {
  memory: string
  api: string
  vector: string
}

export default function LeftSidebar({ onOpenModal, onSelectSession }: LeftSidebarProps) {
  const { user, logout } = useAuth()
  const { t } = useLanguage()
  const [sysStatus, setSysStatus] = useState<StatusState>({
    memory: t('检测中', 'Checking'),
    api: t('检测中', 'Checking'),
    vector: t('检测中', 'Checking'),
  })
  const [sessions, setSessions] = useState<any[]>([])

  useEffect(() => {
    if (!user) return

    const fetchStatus = async () => {
      try {
        const res = await authFetch('/api/status')
        if (res.ok) {
          const data = await res.json()
          setSysStatus({
            memory: data.memory_active ? t('正常', 'Normal') : t('未连接', 'Disconnected'),
            api: data.conversation_ready ? t('正常', 'Normal') : t('降级', 'Degraded'),
            vector: data.memory_active ? t('正常', 'Normal') : t('未连接', 'Disconnected'),
          })
        }
      } catch {
        setSysStatus({ memory: t('异常', 'Error'), api: t('异常', 'Error'), vector: t('异常', 'Error') })
      }
    }

    const fetchSessions = async () => {
      try {
        const res = await authFetch('/api/sessions?limit=5')
        if (res.ok) {
          const data = await res.json()
          setSessions(data.sessions || [])
        }
      } catch {
        setSessions([])
      }
    }

    fetchStatus()
    fetchSessions()
    const interval = window.setInterval(fetchStatus, 30000)
    return () => window.clearInterval(interval)
  }, [user, t])

  return (
    <aside className="w-[280px] h-full flex flex-col glass-panel rounded-2xl p-5 shrink-0 overflow-y-auto">
      <div className="flex items-center gap-3 mb-8 shrink-0 cursor-pointer" onClick={() => onOpenModal('showcase')}>
        <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-brand-500 to-brand-100 flex items-center justify-center shadow-md">
          <Activity size={18} className="text-white" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-lg font-semibold text-text-strong tracking-tight">Promethea</span>
          <span className="text-[10px] text-text-muted font-medium uppercase tracking-wider">{t('Agent 控制台', 'Agent Console')}</span>
        </div>
      </div>

      <div className="flex flex-col items-center mb-6 shrink-0 relative">
        <div className="w-24 h-24 rounded-full mb-4 shadow-lg border-4 border-white/80 overflow-hidden relative bg-bg-subtle flex items-center justify-center">
          <Activity size={40} className="text-brand-500 opacity-70" />
          <div className="absolute inset-0 bg-brand-500/10 mix-blend-overlay"></div>
        </div>
        <div className="flex items-center justify-between w-full px-2 mb-2">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)] animate-pulse"></span>
            <span className="text-xs text-text-muted font-medium">{t('在线', 'Awake')}</span>
          </div>
          <span className="text-xs text-text-muted bg-bg-subtle px-2 py-0.5 rounded-full font-mono">v2.1.0</span>
        </div>

        <h2 className="text-xl font-bold text-text-strong mb-1 self-start px-2">{user?.agent_name || 'Promethea'}</h2>
        <p className="text-xs text-text-muted self-start px-2 mb-4">{t('记忆原生 Agent', 'Memory-Native Agent')}</p>

        <div className="grid grid-cols-3 gap-2 w-full px-2">
          <InfoStat label="Model" value="Runtime" />
          <InfoStat label="Memory" value={sysStatus.memory} />
          <InfoStat label="Context" value="Live" />
        </div>
      </div>

      <nav className="flex flex-col gap-1 mb-6 shrink-0">
        <NavItem icon={<MessageSquare size={18} />} label={t('对话', 'Chat')} active />
        <NavItem icon={<Database size={18} />} label={t('记忆库', 'Memory')} onClick={() => onOpenModal('memory')} />
        <NavItem icon={<Activity size={18} />} label={t('系统指标', 'Metrics')} onClick={() => onOpenModal('metrics')} />
        <NavItem icon={<Beaker size={18} />} label={t('自我进化', 'Self Evolve')} onClick={() => onOpenModal('evolve')} />
        <NavItem icon={<Search size={18} />} label={t('诊断中心', 'Doctor')} onClick={() => onOpenModal('doctor')} />
        <NavItem icon={<Settings size={18} />} label={t('设置', 'Settings')} onClick={() => onOpenModal('settings')} />
      </nav>

      {sessions.length > 0 && (
        <div className="mb-6 shrink-0">
          <h3 className="text-xs font-semibold text-text-strong mb-2 px-2">{t('最近会话', 'Recent Sessions')}</h3>
          <div className="flex flex-col gap-1">
            {sessions.map((session) => (
              <button
                type="button"
                key={session.session_id}
                onClick={() => onSelectSession(session.session_id)}
                className="text-left text-xs text-text-normal truncate px-2 py-1.5 hover:bg-black/5 cursor-pointer rounded-lg"
                title={session.title || session.last_message || session.session_id}
              >
                {session.title || session.last_message || session.session_id}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1"></div>

      <div className="bg-bg-page/50 rounded-xl p-4 mb-4 shrink-0">
        <h3 className="text-xs font-semibold text-text-strong mb-3">{t('系统状态', 'System Status')}</h3>
        <div className="flex flex-col gap-2">
          <StatusRow label="Memory" status={sysStatus.memory} />
          <StatusRow label="API Gateway" status={sysStatus.api} />
          <StatusRow label="Vector Index" status={sysStatus.vector} />
        </div>
      </div>

      <div className="flex items-center gap-3 pt-4 border-t border-black/5 shrink-0">
        <div className="w-8 h-8 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-bold text-xs uppercase">
          {user?.username ? user.username.charAt(0) : 'U'}
        </div>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium text-text-strong truncate">{user?.username || t('访客', 'Guest')}</span>
          <span className="text-[10px] text-text-muted">{t('在线', 'online')}</span>
        </div>
        <button onClick={logout} className="ml-auto text-text-muted hover:text-red-500 transition-colors" title="Logout">
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  )
}

function InfoStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-text-muted mb-0.5">{label}</span>
      <span className="text-sm font-semibold text-text-strong truncate">{value}</span>
    </div>
  )
}

function NavItem({ icon, label, active = false, onClick }: { icon: ReactNode; label: string; active?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
        active
          ? 'bg-brand-50 text-brand-600 shadow-sm border border-brand-100'
          : 'text-text-normal hover:bg-black/5'
      }`}
    >
      <span className={active ? 'text-brand-500' : 'text-text-muted'}>{icon}</span>
      {label}
    </button>
  )
}

function StatusRow({ label, status }: { label: string; status: string }) {
  const normalized = status.toLowerCase()
  const isOk = ['online', 'ok', 'normal', '正常'].includes(normalized) || status === '正常'
  return (
    <div className="flex items-center justify-between text-xs">
      <div className="flex items-center gap-2 text-text-muted">
        <span className={`w-1.5 h-1.5 rounded-full ${isOk ? 'bg-green-500' : 'bg-red-500'}`}></span>
        {label}
      </div>
      <span className="text-text-strong font-medium truncate max-w-[80px]" title={status}>{status}</span>
    </div>
  )
}
