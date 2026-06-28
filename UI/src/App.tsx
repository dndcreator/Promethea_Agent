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
import type { ChatAttachment } from './services/api'
import { useLanguage } from './store/LanguageContext'

function App() {
  const { user, loading, checking, authNotice } = useAuth()
  const { lang, setLang } = useLanguage()

  const [activeModal, setActiveModal] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [treeId, setTreeId] = useState<string | null>(null)
  const [chatRunning, setChatRunning] = useState(false)
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [setupMode, setSetupMode] = useState(false)
  const [navigationOpen, setNavigationOpen] = useState(() => localStorage.getItem('navigation_drawer_open') === 'true')

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
    <div className="flex h-screen w-screen overflow-hidden p-5 gap-5 box-border">
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
          {lang === 'zh'
            ? '设置 / 诊断模式：当前未登录。建议先查看诊断，按提示修复配置后重启；聊天和个人数据功能需要登录。'
            : 'Setup / diagnostics mode: you are not signed in. Inspect diagnostics, fix configuration, then restart. Chat and personal data require sign-in.'}
          <button type="button" onClick={() => setSetupMode(false)} className="ml-3 font-semibold text-brand-600 underline underline-offset-2">
            {lang === 'zh' ? '返回登录' : 'Back to sign in'}
          </button>
        </div>
      )}
      {!user && !setupMode && activeModal !== 'auth' && (
        <div className="fixed left-1/2 top-6 z-[70] flex -translate-x-1/2 items-center gap-3 rounded-full border border-brand-100 bg-bg-card/90 px-4 py-2 text-xs font-medium text-text-normal shadow-sm backdrop-blur">
          <span>
            {checking
              ? (lang === 'zh' ? '正在校验登录状态...' : 'Checking sign-in...')
              : authNotice || (lang === 'zh' ? '访客模式：登录后可使用对话、记忆、文件和工具。' : 'Guest mode: sign in to use chat, memory, files, and tools.')}
          </span>
          <button type="button" onClick={() => setActiveModal('auth')} className="font-semibold text-brand-600 underline underline-offset-2">
            {lang === 'zh' ? '登录' : 'Sign in'}
          </button>
        </div>
      )}
      <button
        type="button"
        onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        className="fixed right-6 top-6 z-[60] rounded-full border border-white/70 bg-bg-card/82 px-3 py-1.5 text-[11px] font-semibold tracking-wide text-text-muted shadow-sm backdrop-blur hover:text-brand-600"
      >
        {lang === 'zh' ? 'EN' : '中文'}
      </button>

      <NavigationSidebar
        onOpenModal={requireAuth}
        onSelectSession={setSessionId}
        open={navigationOpen}
        onToggle={toggleNavigation}
      />
      <LeftSidebar onSignIn={() => setActiveModal('auth')} chatRunning={chatRunning} />
      <MainContent
        sessionId={sessionId}
        setSessionId={setSessionId}
        setTreeId={setTreeId}
        setChatRunning={setChatRunning}
        onRequireAuth={() => setActiveModal('auth')}
        onOpenFiles={() => requireAuth('files')}
        onOpenSearch={() => requireAuth('search')}
        onOpenMemory={() => requireAuth('memory')}
        attachments={attachments}
        onRemoveAttachment={(fileId) => setAttachments((prev) => prev.filter((item) => item.file_id !== fileId))}
        onClearAttachments={() => setAttachments([])}
      />
      <RightSidebar sessionId={sessionId} treeId={treeId} chatRunning={chatRunning} />

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
    </div>
  )
}

export default App
