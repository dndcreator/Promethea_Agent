import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Activity, Beaker, ChevronLeft, Database, FileText, GitBranch, Menu, MessageSquare, Search, Settings } from 'lucide-react'
import { authFetch } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

interface NavigationSidebarProps {
  open: boolean
  onToggle: () => void
  onOpenModal: (modal: string) => void
  onSelectSession: (id: string) => void
}

export default function NavigationSidebar({ open, onToggle, onOpenModal, onSelectSession }: NavigationSidebarProps) {
  const { user } = useAuth()
  const { t } = useLanguage()
  const [sessions, setSessions] = useState<any[]>([])

  useEffect(() => {
    if (!user) {
      setSessions([])
      return
    }
    const fetchSessions = async () => {
      try {
        const res = await authFetch('/api/sessions?limit=8')
        if (!res.ok) return
        const data = await res.json()
        setSessions(data.sessions || [])
      } catch {
        setSessions([])
      }
    }
    void fetchSessions()
    const interval = window.setInterval(fetchSessions, 30000)
    return () => window.clearInterval(interval)
  }, [user])

  if (!open) {
    return (
      <button type="button" onClick={onToggle} title={t('打开功能栏', 'Open navigation')} className="fixed left-7 top-7 z-[55] flex h-10 w-10 items-center justify-center rounded-xl border border-white/70 bg-bg-card/90 text-brand-700 shadow-sm backdrop-blur transition-colors hover:bg-white">
        <Menu size={19} />
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-[80]">
      <button type="button" aria-label={t('关闭功能栏', 'Close navigation')} onClick={onToggle} className="absolute inset-0 bg-black/20 backdrop-blur-[1px]" />
      <aside className="absolute bottom-4 left-4 top-4 flex w-[268px] flex-col overflow-hidden rounded-[1.35rem] border border-white/75 p-4 shadow-2xl glass-panel">
        <div className="mb-4 flex items-center justify-between px-1">
          <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-text-muted">{t('工作区', 'Workspace')}</span>
          <button type="button" onClick={onToggle} title={t('关闭功能栏', 'Close navigation')} className="flex h-8 w-8 items-center justify-center rounded-lg text-text-muted hover:bg-white/60 hover:text-brand-600">
            <ChevronLeft size={17} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <nav className="mb-5 flex flex-col gap-1">
            <NavSection label={t('核心', 'Core')} />
            <NavItem icon={<MessageSquare size={17} />} label={t('对话', 'Chat')} active />
            <NavItem icon={<Search size={17} />} label={t('搜索', 'Search')} onClick={() => onOpenModal('search')} locked={!user} />
            <NavItem icon={<FileText size={17} />} label={t('文件', 'Files')} onClick={() => onOpenModal('files')} locked={!user} />
            <NavSection label={t('大脑', 'Brain')} />
            <NavItem icon={<Database size={17} />} label={t('记忆库', 'Memory')} onClick={() => onOpenModal('memory')} locked={!user} />
            <NavItem icon={<GitBranch size={17} />} label={t('工作流', 'Workflows')} onClick={() => onOpenModal('workflows')} locked={!user} />
            <NavSection label={t('运维', 'Ops')} />
            <NavItem icon={<Activity size={17} />} label={t('系统指标', 'Metrics')} onClick={() => onOpenModal('metrics')} />
            <NavItem icon={<Beaker size={17} />} label={t('自我进化', 'Self Evolve')} onClick={() => onOpenModal('evolve')} />
            <NavItem icon={<Search size={17} />} label={t('诊断中心', 'Doctor')} onClick={() => onOpenModal('doctor')} />
            <NavItem icon={<Settings size={17} />} label={t('设置', 'Settings')} onClick={() => onOpenModal('settings')} locked={!user} />
          </nav>
          <div className="rounded-2xl border border-white/55 bg-white/35 p-3">
            <h3 className="mb-2 px-1 text-[11px] font-semibold text-text-strong">{t('最近会话', 'Recent sessions')}</h3>
            <div className="flex flex-col gap-1">
              {sessions.map((session) => (
                <button type="button" key={session.session_id} onClick={() => onSelectSession(session.session_id)} className="truncate rounded-xl px-2 py-1.5 text-left text-[12px] text-text-normal hover:bg-white/60" title={session.title || session.last_message || session.session_id}>
                  {session.title || session.last_message || session.session_id}
                </button>
              ))}
              {!user && <div className="px-2 py-2 text-[12px] text-text-muted">{t('登录后显示个人会话', 'Sign in to show personal sessions')}</div>}
              {user && sessions.length === 0 && <div className="px-2 py-2 text-[12px] text-text-muted">{t('暂无会话', 'No sessions yet')}</div>}
            </div>
          </div>
        </div>
      </aside>
    </div>
  )
}

function NavSection({ label }: { label: string }) {
  return <div className="px-3 pb-1 pt-4 text-[9px] font-bold uppercase tracking-[0.22em] text-text-muted/75 first:pt-0">{label}</div>
}

function NavItem({ icon, label, active = false, locked = false, onClick }: { icon: ReactNode; label: string; active?: boolean; locked?: boolean; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-all ${active ? 'bg-bg-card text-brand-700 shadow-sm ring-1 ring-white/70' : 'text-text-normal hover:bg-white/45'}`}>
      <span className={active ? 'text-brand-600' : 'text-text-muted'}>{icon}</span>
      <span className="flex-1 text-left">{label}</span>
      {locked && <span className="rounded-full bg-white/70 px-1.5 py-0.5 text-[9px] text-text-muted">login</span>}
    </button>
  )
}
