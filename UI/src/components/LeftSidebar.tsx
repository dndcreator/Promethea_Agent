import { useEffect, useState } from 'react'
import { Activity, LogOut } from 'lucide-react'
import { authFetch } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'
import AvatarSurface from './avatar/AvatarSurface'

interface LeftSidebarProps {
  onSignIn: () => void
  chatRunning: boolean
}

type StatusState = {
  model: string
  memory: string
  api: string
  queue: string
}

export default function LeftSidebar({ onSignIn, chatRunning }: LeftSidebarProps) {
  const { user, logout } = useAuth()
  const { t } = useLanguage()
  const [sysStatus, setSysStatus] = useState<StatusState>({
    model: t('默认', 'Default'),
    memory: t('检测中', 'Checking'),
    api: t('检测中', 'Checking'),
    queue: '0',
  })

  useEffect(() => {
    if (!user) return
    const fetchStatus = async () => {
      try {
        const [statusRes, secretsRes] = await Promise.all([
          authFetch('/api/status'),
          authFetch('/api/config/secrets'),
        ])
        if (!statusRes.ok) return
        const data = await statusRes.json()
        const secrets = secretsRes.ok ? await secretsRes.json() : {}
        const model = String(secrets?.secrets?.api?.model || '').trim()
        const sync = data.memory_sync || {}
        const pending = Number(sync.pending || sync.queued || 0)
        setSysStatus({
          model: model || t('默认', 'Default'),
          memory: data.memory_active ? t('正常', 'Normal') : t('未连接', 'Disconnected'),
          api: data.conversation_ready ? t('正常', 'Normal') : t('降级', 'Degraded'),
          queue: pending > 0 ? String(pending) : '0',
        })
      } catch {
        setSysStatus({ model: t('未知', 'Unknown'), memory: t('异常', 'Error'), api: t('异常', 'Error'), queue: '?' })
      }
    }
    void fetchStatus()
    const interval = window.setInterval(fetchStatus, 30000)
    return () => window.clearInterval(interval)
  }, [user, t])

  return (
    <aside className="flex h-full w-[282px] shrink-0 flex-col overflow-hidden rounded-[1.35rem] p-4 glass-panel">
      <div className="mb-5 flex shrink-0 items-center gap-3 pl-11 pr-1">
        <div className="neural-surface fine-border flex h-9 w-9 items-center justify-center rounded-2xl">
          <Activity size={18} className="text-brand-600" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="font-display text-[21px] font-semibold tracking-[-0.035em] text-text-strong">Promethea</span>
          <span className="text-[9px] font-bold uppercase tracking-[0.24em] text-text-muted">{t('Agent 控制台', 'Agent Console')}</span>
        </div>
      </div>

      <section className="flex min-h-0 flex-1 flex-col rounded-[1.25rem] border border-white/65 bg-bg-card/58 p-4 fine-border">
        <div className="relative flex min-h-0 flex-1">
          <AvatarSurface state={chatRunning ? 'thinking' : 'idle'} active={Boolean(user)} spacious />
          <div className="absolute left-3 right-3 top-3 flex items-start justify-between gap-3">
            <div className="min-w-0 rounded-xl border border-white/65 bg-white/72 px-3 py-2 shadow-sm backdrop-blur">
              <h2 className="truncate text-[16px] font-semibold tracking-[-0.02em] text-text-strong">{user?.agent_name || 'Promethea'}</h2>
              <p className="text-[10px] text-text-muted">{t('记忆原生 Agent', 'Memory-native agent')}</p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/65 bg-white/72 px-2 py-1 text-[10px] font-medium text-text-muted shadow-sm backdrop-blur">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]" />
              {user ? t('在线', 'Awake') : t('访客', 'Guest')}
            </span>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <InfoStat label="Model" value={sysStatus.model} />
          <InfoStat label="Queue" value={sysStatus.queue} />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-text-muted">
          <StatusDot label="API" status={sysStatus.api} />
          <StatusDot label="Memory" status={sysStatus.memory} />
        </div>
      </section>

      <div className="mt-4 flex shrink-0 items-center gap-3 border-t border-white/55 pt-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-100 text-xs font-bold uppercase text-brand-700">
          {user?.username ? user.username.charAt(0) : 'U'}
        </div>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium text-text-strong">{user?.username || t('访客', 'Guest')}</span>
          <span className="text-[10px] text-text-muted">{t('在线', 'online')}</span>
        </div>
        {user ? (
          <button type="button" onClick={logout} className="ml-auto text-text-muted transition-colors hover:text-red-500" title="Logout">
            <LogOut size={16} />
          </button>
        ) : (
          <button type="button" onClick={onSignIn} className="ml-auto rounded-full bg-brand-500 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-brand-600">
            {t('登录', 'Sign in')}
          </button>
        )}
      </div>
    </aside>
  )
}

function InfoStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/44 px-2.5 py-2">
      <span className="mb-0.5 block text-[9px] uppercase tracking-[0.12em] text-text-muted">{label}</span>
      <span className="block truncate text-[12px] font-semibold leading-5 text-text-strong" title={value}>{value}</span>
    </div>
  )
}

function StatusDot({ label, status }: { label: string; status: string }) {
  const normalized = status.toLowerCase()
  const isOk = ['online', 'ok', 'normal', '正常', '0'].includes(normalized)
  return (
    <span className="inline-flex items-center gap-1.5 rounded-xl bg-white/40 px-2.5 py-2" title={`${label}: ${status}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${isOk ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      {label}
    </span>
  )
}
