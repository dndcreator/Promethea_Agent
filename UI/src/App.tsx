import { useState } from 'react'
import LeftSidebar from './components/LeftSidebar'
import MainContent from './components/MainContent'
import RightSidebar from './components/RightSidebar'
import { useAuth } from './store/AuthContext'
import AuthModal from './components/AuthModal'
import SettingsModal from './components/modals/SettingsModal'
import MemoryModal from './components/modals/MemoryModal'
import MetricsModal from './components/modals/MetricsModal'
import DoctorModal from './components/modals/DoctorModal'
import EvolveModal from './components/modals/EvolveModal'
import ShowcaseModal from './components/modals/ShowcaseModal'
import { useLanguage } from './store/LanguageContext'

function App() {
  const { user, loading } = useAuth()
  const { lang, setLang } = useLanguage()
  
  const [activeModal, setActiveModal] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [treeId, setTreeId] = useState<string | null>(null)

  const closeModal = () => setActiveModal(null)

  if (loading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-bg-page">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-500"></div>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden p-4 gap-4 box-border">
      {!user && <AuthModal />}
      <button
        type="button"
        onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        className="fixed right-5 top-5 z-[60] rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-xs font-semibold text-text-muted shadow-sm backdrop-blur hover:text-brand-600"
      >
        {lang === 'zh' ? 'EN' : '中'}
      </button>
      
      <LeftSidebar onOpenModal={setActiveModal} onSelectSession={setSessionId} />
      <MainContent sessionId={sessionId} setSessionId={setSessionId} setTreeId={setTreeId} />
      <RightSidebar sessionId={sessionId} treeId={treeId} />

      {activeModal === 'settings' && <SettingsModal onClose={closeModal} />}
      {activeModal === 'memory' && <MemoryModal onClose={closeModal} />}
      {activeModal === 'metrics' && <MetricsModal onClose={closeModal} />}
      {activeModal === 'doctor' && <DoctorModal onClose={closeModal} />}
      {activeModal === 'evolve' && <EvolveModal onClose={closeModal} />}
      {activeModal === 'showcase' && <ShowcaseModal onClose={closeModal} />}
    </div>
  )
}

export default App
