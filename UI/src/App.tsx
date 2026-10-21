import { useCallback, useRef, useState } from 'react'
import { PanelLeftOpen, PanelRightOpen, X } from 'lucide-react'
import NavigationSidebar from './components/NavigationSidebar'
import type { WorkspaceView } from './components/NavigationSidebar'
import SessionSidebar from './components/SessionSidebar'
import MainContent from './components/MainContent'
import RightSidebar from './components/RightSidebar'
import TasksPage from './components/TasksPage'
import ArtifactPreview from './components/ArtifactPreview'
import AuthModal from './components/AuthModal'
import SettingsModal from './components/modals/SettingsModal'
import MemoryModal from './components/modals/MemoryModal'
import type { MemoryModalTab } from './components/modals/MemoryModal'
import MetricsModal from './components/modals/MetricsModal'
import DoctorModal from './components/modals/DoctorModal'
import EvolveModal from './components/modals/EvolveModal'
import FilesModal from './components/modals/FilesModal'
import SearchModal from './components/modals/SearchModal'
import WorkflowsModal from './components/modals/WorkflowsModal'
import CanvasModal from './components/modals/CanvasModal'
import { assignSessionProject } from './services/api'
import type { ChatAttachment, Task, WorkbenchReference } from './services/api'
import { useAuth } from './store/AuthContext'
import { useLanguage } from './store/LanguageContext'
import { WorkbenchProvider } from './store/WorkbenchContext'

export default function App() {
  const { user } = useAuth()
  return <Workspace key={user?.user_id || 'guest'} />
}

function Workspace() {
  const { user, loading, checking, authNotice } = useAuth()
  const { t } = useLanguage()
  const [view, setView] = useState<WorkspaceView>('chat')
  const [authOpen, setAuthOpen] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [chatKey, setChatKey] = useState(0)
  const [revision, setRevision] = useState(0)
  const [treeId, setTreeId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 900 && localStorage.getItem('session_sidebar_open') !== 'false')
  const [workbenchOpen, setWorkbenchOpen] = useState(() => window.innerWidth >= 1400 && localStorage.getItem('workbench_open') !== 'false')
  const [workbenchView, setWorkbenchView] = useState<'work' | 'activity'>('work')
  const [observedTask, setObservedTask] = useState<{ task: Task; runId?: string } | null>(null)
  const [canvas, setCanvas] = useState<{ workspaceId: string; environmentId?: string } | null>(null)
  const [artifact, setArtifact] = useState<{ reference: WorkbenchReference; workspaceId: string } | null>(null)
  const [memoryTab, setMemoryTab] = useState<MemoryModalTab>('cognition')
  const [memoryQuery, setMemoryQuery] = useState('')
  const [fileQuery, setFileQuery] = useState('')
  const [fileId, setFileId] = useState<string | undefined>()
  const [projectError, setProjectError] = useState('')
  const pendingProject = useRef<string | null>(null)
  const assignment = useRef<{ sessionId: string; projectId: string } | null>(null)

  const toggleSidebar = () => setSidebarOpen((current) => { localStorage.setItem('session_sidebar_open', String(!current)); return !current })
  const toggleWorkbench = (next: boolean) => { setWorkbenchOpen(next); localStorage.setItem('workbench_open', String(next)) }
  const navigate = (next: WorkspaceView) => {
    if (!user && !['chat', 'doctor', 'metrics'].includes(next)) { setAuthOpen(true); return }
    setView(next)
    if (next === 'memory') { setMemoryTab('cognition'); setMemoryQuery('') }
    if (next === 'files') { setFileQuery(''); setFileId(undefined) }
    if (window.innerWidth < 900) setSidebarOpen(false)
  }
  const selectSession = (id: string) => {
    setSessionId(id); setView('chat'); setTreeId(null); setObservedTask(null); setCanvas(null); setArtifact(null)
    pendingProject.current = null; assignment.current = null; setProjectError(''); setAttachments([])
    if (window.innerWidth < 900) setSidebarOpen(false)
  }
  const newChat = (projectId?: string) => {
    pendingProject.current = projectId || null; assignment.current = null; setProjectError('')
    setSessionId(null); setTreeId(null); setRunning(false); setObservedTask(null); setCanvas(null); setArtifact(null); setAttachments([]); setChatKey((value) => value + 1); setView('chat')
    if (window.innerWidth < 900) setSidebarOpen(false)
  }
  const assignPending = async () => {
    const target = assignment.current
    if (!target) return
    try {
      await assignSessionProject(target.sessionId, target.projectId)
      if (assignment.current === target) { assignment.current = null; setProjectError(''); setRevision((value) => value + 1) }
    } catch { if (assignment.current === target) setProjectError(t('项目归属保存失败', 'Could not save project assignment')) }
  }
  const updateSession = (id: string | null) => {
    setSessionId(id); setRevision((value) => value + 1)
    if (id && pendingProject.current) {
      assignment.current = { sessionId: id, projectId: pendingProject.current }; pendingProject.current = null
      void assignPending()
    }
  }
  const updateRunning = useCallback((value: boolean) => { setRunning(value); if (!value) setRevision((current) => current + 1) }, [])
  const openMemory = (tab: MemoryModalTab, query = '') => { setMemoryTab(tab); setMemoryQuery(query); setView('memory'); if (window.innerWidth < 1200) setWorkbenchOpen(false) }
  const openCanvas = (workspaceId = sessionId || 'default', environmentId?: string) => { setCanvas({ workspaceId, environmentId }); setArtifact(null); setWorkbenchView('work'); toggleWorkbench(true) }
  const preview = canvas ? <CanvasModal key={`${canvas.workspaceId}:${canvas.environmentId}`} embedded compact workspaceId={canvas.workspaceId} initialEnvironmentId={canvas.environmentId} onClose={() => setCanvas(null)} /> : artifact ? <ArtifactPreview reference={artifact.reference} workspaceId={artifact.workspaceId} onClose={() => setArtifact(null)} /> : undefined
  const workbench = <RightSidebar sessionId={observedTask ? null : sessionId} treeId={observedTask ? null : treeId} taskId={observedTask?.task.task_id} runId={observedTask?.runId} chatRunning={!observedTask && running} onOpenMemoryReview={() => openMemory('proposals')} onOpenMemory={openMemory} onOpenCanvas={openCanvas} onOpenArtifact={(reference, workspaceId) => { setArtifact({ reference, workspaceId }); setCanvas(null); setWorkbenchView('work') }} onOpenWorkflows={() => navigate('workflows')} view={workbenchView} onViewChange={setWorkbenchView} onClose={() => toggleWorkbench(false)} content={preview} />
  if (loading) return <div className="app-loading" role="status" aria-label={t('正在加载', 'Loading')}><div className="loading-spinner" /></div>
  return <WorkbenchProvider sessionId={sessionId}>
    <div className={`app-shell ${sidebarOpen ? 'sidebar-open' : ''} ${workbenchOpen ? 'workbench-open' : ''}`}>
      <NavigationSidebar activeView={view} onNavigate={navigate} account={user?.username || t('登录', 'Sign in')} onAccount={() => user ? navigate('settings') : setAuthOpen(true)} />
      {sidebarOpen && <><button type="button" className="sidebar-scrim" aria-label={t('关闭会话栏', 'Close sidebar')} onClick={() => setSidebarOpen(false)} /><SessionSidebar sessionId={sessionId} revision={revision} onSelect={selectSession} onNew={newChat} onCollapse={toggleSidebar} onSignIn={() => setAuthOpen(true)} running={running} /></>}
      <div className="workspace-main">
        <div className="workspace-topbar"><div className="workspace-location"><button type="button" className="icon-button" aria-label={t('展开会话栏', 'Open sidebar')} title={t('展开会话栏', 'Open sidebar')} onClick={toggleSidebar}><PanelLeftOpen size={17} /></button><span>{t('工作空间', 'Workspace')}</span></div><div className="workspace-status">{(!user || authNotice) && <button type="button" className="text-button" onClick={() => setAuthOpen(true)}>{checking ? t('正在校验登录状态', 'Checking sign-in') : authNotice || t('登录', 'Sign in')}</button>}<button type="button" className={`icon-button ${workbenchOpen ? 'is-active' : ''}`} aria-label={t('切换工作台', 'Toggle workbench')} title={t('切换工作台', 'Toggle workbench')} onClick={() => toggleWorkbench(!workbenchOpen)}><PanelRightOpen size={17} /></button></div></div>
        {projectError && <div role="alert" className="page-error"><span>{projectError}</span><button type="button" onClick={() => void assignPending()}>{t('重试', 'Retry')}</button></div>}
        <div className="workspace-body">
          <div className="conversation-surface" hidden={view !== 'chat'}><MainContent key={chatKey} sessionId={sessionId} setSessionId={updateSession} setTreeId={setTreeId} setChatRunning={updateRunning} onRequireAuth={() => setAuthOpen(true)} onOpenFiles={() => navigate('files')} onOpenSearch={() => navigate('search')} onOpenMemory={() => openMemory('proposals')} onOpenWorkbench={() => toggleWorkbench(true)} attachments={attachments} onRemoveAttachment={(fileId) => setAttachments((rows) => rows.filter((row) => row.file_id !== fileId))} onClearAttachments={() => setAttachments([])} /></div>
          {view === 'tasks' && <TasksPage onOpenSession={selectSession} onObserve={(task, runId) => { setObservedTask({ task, runId }); setCanvas(null); setArtifact(null); setWorkbenchView('activity'); toggleWorkbench(true) }} />}
          {view === 'memory' && <MemoryModal key={`${memoryTab}:${memoryQuery}`} embedded initialTab={memoryTab} initialQuery={memoryQuery} onClose={() => setView('chat')} />}
          {view === 'canvas' && <CanvasModal embedded workspaceId={sessionId} onClose={() => setView('chat')} />}
          {view === 'files' && <FilesModal key={`${fileId || ''}:${fileQuery}`} embedded initialFileId={fileId} initialQuery={fileQuery} sessionId={sessionId} onClose={() => setView('chat')} onAttach={(file) => { setAttachments((rows) => rows.some((row) => row.file_id === file.file_id) ? rows : [...rows, file]); setView('chat') }} />}
          {view === 'workflows' && <WorkflowsModal embedded onClose={() => setView('chat')} />}
          {view === 'search' && <SearchModal embedded onClose={() => setView('chat')} onSelectSession={selectSession} onOpenFile={(filename, id) => { setFileQuery(filename); setFileId(id); setView('files') }} />}
          {view === 'settings' && <SettingsModal embedded onClose={() => setView('chat')} onWorkspaceRestored={() => {
            setSessionId(null); setTreeId(null); setRunning(false); setObservedTask(null); setCanvas(null); setArtifact(null); setAttachments([])
            pendingProject.current = null; assignment.current = null; setProjectError(''); setFileQuery(''); setFileId(undefined)
            setChatKey((value) => value + 1); setRevision((value) => value + 1)
          }} />}
          {view === 'metrics' && <MetricsModal embedded onClose={() => setView('chat')} />}
          {view === 'evolve' && <EvolveModal embedded onClose={() => setView('chat')} />}
          {view === 'doctor' && <DoctorModal embedded onClose={() => setView('chat')} />}
        </div>
      </div>
      {workbenchOpen && <><button type="button" className="workbench-scrim" aria-label={t('关闭工作台', 'Close workbench')} onClick={() => toggleWorkbench(false)} /><div className={`workspace-workbench ${preview ? 'with-preview' : ''}`}>{observedTask && <div className="observed-task"><span>{observedTask.task.title}{observedTask.runId ? ` · ${t('运行', 'Run')} ${(observedTask.task.runs || []).findIndex((run) => run.run_id === observedTask.runId) + 1}` : ''}</span>{observedTask.runId && <button type="button" className="text-button" onClick={() => { setObservedTask({ task: observedTask.task }); setCanvas(null); setArtifact(null) }}>{t('整个任务', 'Whole task')}</button>}<button type="button" className="icon-button" title={t('返回当前会话', 'Return to chat')} aria-label={t('返回当前会话', 'Return to chat')} onClick={() => { setObservedTask(null); setCanvas(null); setArtifact(null) }}><X size={14} /></button></div>}{observedTask ? <WorkbenchProvider taskId={observedTask.task.task_id} runId={observedTask.runId} sessionId={null}>{workbench}</WorkbenchProvider> : workbench}</div></>}
      {authOpen && !user && <AuthModal onClose={() => setAuthOpen(false)} onEnterSetup={() => { setAuthOpen(false); setView('doctor') }} />}
    </div>
  </WorkbenchProvider>
}
