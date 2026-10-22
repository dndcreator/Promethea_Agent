import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Folder, MoreHorizontal, PanelLeftClose, Pencil, Pin, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { assignSessionProject, createProject, deleteProject, listProjects, listSessions, renameProject, setSessionPinned } from '../services/api'
import type { Project, Session } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'
import FeatureSurface from './FeatureSurface'
import LeftSidebar from './LeftSidebar'

export default function SessionSidebar({ sessionId, revision, onSelect, onNew, onCollapse, onSignIn, running }: {
  sessionId: string | null; revision: number; onSelect: (id: string) => void; onNew: (projectId?: string) => void; onCollapse: () => void; onSignIn: () => void; running: boolean
}) {
  const { user } = useAuth()
  const { t } = useLanguage()
  const [sessions, setSessions] = useState<Session[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [editor, setEditor] = useState<Project | 'new' | null>(null)
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<Session | null>(null)
  const [destination, setDestination] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!user) return
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      try {
        const [rows, groups] = await Promise.allSettled([listSessions(controller.signal), listProjects(controller.signal)])
        if (!controller.signal.aborted) {
          if (rows.status === 'fulfilled') setSessions(rows.value)
          if (groups.status === 'fulfilled') setProjects(groups.value)
          setError(rows.status === 'rejected' ? t('会话列表加载失败', 'Could not load conversations')
            : groups.status === 'rejected' ? t('项目列表加载失败', 'Could not load projects') : '')
        }
      } catch {
        if (!controller.signal.aborted) setError(t('会话列表加载失败', 'Could not load conversations'))
      } finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => void load(), 30000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [user?.user_id, revision, refresh, t])

  const reload = () => setRefresh((value) => value + 1)
  const mutate = async (operation: () => Promise<unknown>) => {
    setBusy(true); setActionError('')
    try { await operation(); reload(); return true }
    catch (cause) { setActionError(cause instanceof Error ? cause.message : t('操作失败', 'Operation failed')); return false }
    finally { setBusy(false) }
  }
  const saveProject = async () => {
    if (!name.trim() || !editor) return
    if (await mutate(() => editor === 'new' ? createProject(name.trim()) : renameProject(editor.project_id, name.trim()))) setEditor(null)
  }
  const removeProject = async (project: Project) => {
    if (!window.confirm(t(`删除项目“${project.name}”？对话不会被删除。`, `Delete project “${project.name}”? Conversations will not be deleted.`))) return
    await mutate(() => deleteProject(project.project_id))
  }
  const openActions = (session: Session) => {
    setSelected(session); setDestination(projects.find((p) => p.session_ids?.includes(session.session_id))?.project_id || ''); setActionError('')
  }
  const matches = (session: Session) => !query.trim() || (session.title || '').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const row = (session: Session) => <div key={session.session_id} className={`session-item ${sessionId === session.session_id ? 'is-selected' : ''}`}>
    <button type="button" className="session-select" onClick={() => onSelect(session.session_id)} title={session.title}>{session.pinned ? <Pin size={12} /> : <span className="session-point" />}<span>{session.title}</span></button>
    <button type="button" className="session-more" aria-label={t(`管理会话：${session.title}`, `Manage chat: ${session.title}`)} title={t('管理会话', 'Manage chat')} onClick={() => openActions(session)}><MoreHorizontal size={15} /></button>
  </div>
  const grouped = new Set(projects.flatMap((project) => project.session_ids || []))
  const ungrouped = sessions.filter((session) => !grouped.has(session.session_id) && matches(session)).sort((a, b) => Number(b.pinned) - Number(a.pinned))

  return <aside className="session-sidebar" aria-label={t('项目与对话', 'Projects and conversations')}>
    <header className="session-sidebar-header"><strong>Promethea</strong><button type="button" className="icon-button" title={t('收起会话栏', 'Collapse sidebar')} aria-label={t('收起会话栏', 'Collapse sidebar')} onClick={onCollapse}><PanelLeftClose size={16} /></button></header>
    <button type="button" className="new-conversation" onClick={() => onNew()}><Plus size={16} />{t('新建对话', 'New conversation')}</button>
    {user && <label className="session-search"><Search size={14} /><input aria-label={t('搜索会话', 'Search conversations')} placeholder={t('搜索会话', 'Search conversations')} value={query} onChange={(event) => setQuery(event.target.value)} /></label>}
    <div className="session-sidebar-scroll">
      {error && <div role="alert" className="sidebar-error"><span>{error}</span><button type="button" title={t('重试', 'Retry')} onClick={reload}><RefreshCw size={13} /></button></div>}
      {user && <div className="sidebar-section-title"><span>{t('项目', 'Projects')}</span><button type="button" title={t('新建项目', 'New project')} aria-label={t('新建项目', 'New project')} onClick={() => { setName(''); setEditor('new'); setActionError('') }}><Plus size={14} /></button></div>}
      {projects.map((project) => {
        const rows = sessions.filter((session) => project.session_ids?.includes(session.session_id) && matches(session))
        const folded = collapsed.has(project.project_id) && !query
        return <section key={project.project_id} className="project-group"><div className="project-heading"><button type="button" className="project-toggle" aria-expanded={!folded} onClick={() => setCollapsed((old) => { const next = new Set(old); if (next.has(project.project_id)) next.delete(project.project_id); else next.add(project.project_id); return next })}>{folded ? <ChevronRight size={12} /> : <ChevronDown size={12} />}<Folder size={14} /><span>{project.name}</span></button><div className="project-actions"><button type="button" title={t('在项目中新建对话', 'New chat in project')} onClick={() => onNew(project.project_id)}><Plus size={13} /></button><button type="button" title={t('重命名项目', 'Rename project')} onClick={() => { setName(project.name); setEditor(project); setActionError('') }}><Pencil size={12} /></button><button type="button" disabled={busy} title={t('删除项目', 'Delete project')} onClick={() => void removeProject(project)}><Trash2 size={12} /></button></div></div>{!folded && <div className="project-sessions">{rows.map(row)}{rows.length === 0 && <div className="sidebar-empty">{query ? t('没有匹配会话', 'No matching conversations') : t('暂无会话', 'No conversations')}</div>}</div>}</section>
      })}
      <div className="sidebar-section-title spaced"><span>{user ? t('其他对话', 'Other conversations') : t('临时对话', 'Temporary chat')}</span>{loading && <RefreshCw size={11} className="animate-spin" />}</div>
      {ungrouped.map(row)}
      {user && !loading && !error && sessions.length === 0 && <p className="sidebar-empty">{t('暂无会话', 'No conversations')}</p>}
      {actionError && !selected && !editor && <p role="alert" className="sidebar-error">{actionError}</p>}
    </div>
    <LeftSidebar onSignIn={onSignIn} chatRunning={running} />
    {editor && <FeatureSurface onClose={() => setEditor(null)} size="compact" label={editor === 'new' ? t('新建项目', 'New project') : t('重命名项目', 'Rename project')}><form className="project-form" onSubmit={(event) => { event.preventDefault(); void saveProject() }}><header><h2>{editor === 'new' ? t('新建项目', 'New project') : t('重命名项目', 'Rename project')}</h2><button type="button" className="icon-button" title={t('关闭', 'Close')} onClick={() => setEditor(null)}><X size={16} /></button></header><label>{t('名称', 'Name')}<input autoFocus maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></label>{actionError && <p role="alert">{actionError}</p>}<footer><button type="button" className="secondary-button" onClick={() => setEditor(null)}>{t('取消', 'Cancel')}</button><button type="submit" className="primary-button" disabled={busy || !name.trim()}>{t('保存', 'Save')}</button></footer></form></FeatureSurface>}
    {selected && <FeatureSurface onClose={() => setSelected(null)} size="compact" label={t('管理会话', 'Manage conversation')}><div className="project-form"><header><h2>{selected.title}</h2><button type="button" className="icon-button" title={t('关闭', 'Close')} onClick={() => setSelected(null)}><X size={16} /></button></header><label>{t('所属项目', 'Project')}<select aria-label={t('所属项目', 'Project')} value={destination} onChange={(event) => setDestination(event.target.value)}><option value="">{t('不属于项目', 'No project')}</option>{projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}</select></label><button type="button" className="secondary-button" disabled={busy} onClick={() => void mutate(async () => { await setSessionPinned(selected.session_id, !selected.pinned); setSelected({ ...selected, pinned: !selected.pinned }) })}><Pin size={13} />{selected.pinned ? t('取消置顶', 'Unpin') : t('置顶会话', 'Pin conversation')}</button>{actionError && <p role="alert">{actionError}</p>}<footer><button type="button" className="secondary-button" onClick={() => setSelected(null)}>{t('取消', 'Cancel')}</button><button type="button" className="primary-button" disabled={busy} onClick={async () => { if (await mutate(() => assignSessionProject(selected.session_id, destination || null))) setSelected(null) }}>{t('保存', 'Save')}</button></footer></div></FeatureSurface>}
  </aside>
}
