import { useState } from 'react'
import LeftSidebar from './components/LeftSidebar'
import NavigationSidebar from './components/NavigationSidebar'
import MainContent from './components/MainContent'
import RightSidebar from './components/RightSidebar'
import { useAuth } from './store/AuthContext'
import AuthModal from './components/AuthModal'
import SettingsModal from './components/modals/SettingsModal'
import MemoryModal from './components/modals/MemoryModal'
import MetricsModal from './components/modals/MetricsModal'
import DoctorModal from './components/modals/DoctorModal'
import EvolveModal from './components/modals/EvolveModal'
import FilesModal from './components/modals/FilesModal'
import SearchModal from './components/modals/SearchModal'
import WorkflowsModal from './components/modals/WorkflowsModal'
import CanvasModal from './components/modals/CanvasModal'
import type { ChatAttachment } from './services/api'
import { useLanguage } from './store/LanguageContext'
import { X } from 'lucide-react'

function App() {
  const { user, loading, checking, authNotice } = useAuth()
  const { lang, setLang } = useLanguage()

  const [activeModal, setActiveModal] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [treeId, setTreeId] = useState<string | null>(null)
  const [chatRunning, setChatRunning] = useState(false)
  const [memoryReviewId, setMemoryReviewId] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [setupMode, setSetupMode] = useState(false)
  const [navigationOpen, setNavigationOpen] = useState(() => localStorage.getItem('navigation_drawer_open') === 'true')
  const [workbenchOpen, setWorkbenchOpen] = useState(false)

  const closeModal = () => setActiveModal(null)
  const toggleNavigation = () => {
    setNavigationOpen((current) => {
      const next = !current
      localStorage.setItem('navigation_drawer_open', String(next))
      return next
    })
  }
  const requireAuth = (modal: string) => {
    if (!user && modal !== 'doctor' && modal !== 'metrics') {
      setActiveModal('auth')
      return
    }
    setActiveModal(modal)
  }

  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-bg-page">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand-100 border-b-brand-500" />
      </div>
    )
  }

  return (
    <div className="flex h-screen w-screen gap-2 overflow-hidden p-2 box-border sm:gap-3 sm:p-3 xl:gap-5 xl:p-5">
      {activeModal === 'auth' && !user && (
        <AuthModal
          onClose={closeModal}
          onEnterSetup={() => {
            setSetupMode(true)
            setActiveModal('doctor')
          }}
        />
      )}
      {!user && setupMode && (
        <div className="fixed left-1/2 top-6 z-[70] -translate-x-1/2 rounded-full border border-brand-200 bg-bg-card/90 px-4 py-2 text-xs font-medium text-text-normal shadow-sm backdrop-blur">
          {lang === 'zh' ? '设置 / 诊断模式' : 'Setup / diagnostics mode'}
          <button type="button" onClick={() => setSetupMode(false)} className="ml-3 font-semibold text-brand-600 underline underline-offset-2">
            {lang === 'zh' ? '返回登录' : 'Back to sign in'}
          </button>
        </div>
      )}
      {!user && !setupMode && activeModal !== 'auth' && (
        <div className="fixed left-1/2 top-6 z-[70] hidden -translate-x-1/2 items-center gap-3 rounded-full border border-brand-100 bg-bg-card/90 px-4 py-2 text-xs font-medium text-text-normal shadow-sm backdrop-blur sm:flex">
          <span>
            {checking
              ? (lang === 'zh' ? '正在校验登录状态...' : 'Checking sign-in...')
              : authNotice || (lang === 'zh' ? '访客模式' : 'Guest mode')}
          </span>
          <button type="button" onClick={() => setActiveModal('auth')} className="font-semibold text-brand-600 underline underline-offset-2">
            {lang === 'zh' ? '登录' : 'Sign in'}
          </button>
        </div>
      )}
      <button
        type="button"
        onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        className="fixed right-6 top-6 z-[60] hidden rounded-full border border-white/70 bg-bg-card/82 px-3 py-1.5 text-[11px] font-semibold tracking-wide text-text-muted shadow-sm backdrop-blur hover:text-brand-600 sm:block"
      >
        {lang === 'zh' ? 'EN' : '中文'}
      </button>

      <NavigationSidebar
        onOpenModal={requireAuth}
        onSelectSession={setSessionId}
        open={navigationOpen}
        onToggle={toggleNavigation}
      />
      <div className="hidden h-full w-[282px] shrink-0 lg:block">
        <LeftSidebar onSignIn={() => setActiveModal('auth')} chatRunning={chatRunning} />
      </div>
      <MainContent
        sessionId={sessionId}
        setSessionId={setSessionId}
        setTreeId={setTreeId}
        setChatRunning={setChatRunning}
        onRequireAuth={() => setActiveModal('auth')}
        onOpenFiles={() => requireAuth('files')}
        onOpenSearch={() => requireAuth('search')}
        onOpenMemory={() => requireAuth('memory')}
        onOpenWorkbench={() => setWorkbenchOpen(true)}
        memoryReviewId={memoryReviewId}
        attachments={attachments}
        onRemoveAttachment={(fileId) => setAttachments((prev) => prev.filter((item) => item.file_id !== fileId))}
        onClearAttachments={() => setAttachments([])}
      />
      <div className="hidden h-full w-[322px] shrink-0 xl:block">
        <RightSidebar
          sessionId={sessionId}
          treeId={treeId}
          chatRunning={chatRunning}
          onMemoryReviewChange={setMemoryReviewId}
        />
      </div>
      {workbenchOpen && (
        <div className="fixed inset-0 z-[75] xl:hidden">
          <button type="button" aria-label={lang === 'zh' ? '关闭工作台' : 'Close workbench'} onClick={() => setWorkbenchOpen(false)} className="absolute inset-0 bg-black/20 backdrop-blur-[1px]" />
          <button type="button" title={lang === 'zh' ? '关闭工作台' : 'Close workbench'} onClick={() => setWorkbenchOpen(false)} className="absolute left-3 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-xl border border-white/70 bg-bg-card/95 text-text-muted shadow-sm">
            <X size={17} />
          </button>
          <div className="absolute bottom-2 right-2 top-2 w-[calc(100%-3.5rem)] max-w-[322px]">
            <RightSidebar
              sessionId={sessionId}
              treeId={treeId}
              chatRunning={chatRunning}
              onMemoryReviewChange={setMemoryReviewId}
            />
          </div>
        </div>
      )}

      {activeModal === 'settings' && <SettingsModal onClose={closeModal} />}
      {activeModal === 'memory' && <MemoryModal onClose={closeModal} />}
      {activeModal === 'metrics' && <MetricsModal onClose={closeModal} />}
      {activeModal === 'doctor' && <DoctorModal onClose={closeModal} />}
      {activeModal === 'evolve' && <EvolveModal onClose={closeModal} />}
      {activeModal === 'files' && (
        <FilesModal
          sessionId={sessionId}
          onClose={closeModal}
          onAttach={(file) => {
            setAttachments((prev) => (prev.some((item) => item.file_id === file.file_id) ? prev : [...prev, file]))
          }}
        />
      )}
      {activeModal === 'search' && <SearchModal onClose={closeModal} onSelectSession={setSessionId} />}
      {activeModal === 'workflows' && <WorkflowsModal onClose={closeModal} />}
      {activeModal === 'canvas' && <CanvasModal workspaceId={sessionId} onClose={closeModal} />}
    </div>
  )
}

export default App
