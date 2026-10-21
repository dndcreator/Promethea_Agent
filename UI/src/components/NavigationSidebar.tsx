import { Activity, Beaker, Database, FileText, GitBranch, Languages, ListTodo, MessageSquare, MonitorPlay, Search, Settings, Stethoscope } from 'lucide-react'
import { useLanguage } from '../store/LanguageContext'
import { useWorkbench } from '../store/WorkbenchContext'

export type WorkspaceView = 'chat' | 'tasks' | 'memory' | 'canvas' | 'files' | 'workflows' | 'search' | 'settings' | 'metrics' | 'evolve' | 'doctor'

export default function NavigationSidebar({ activeView, onNavigate, reviewCount, account, onAccount }: {
  activeView: WorkspaceView; onNavigate: (view: WorkspaceView) => void; reviewCount?: number; account: string; onAccount: () => void
}) {
  const { lang, setLang, t } = useLanguage()
  const { snapshot } = useWorkbench()
  const pendingCount = reviewCount ?? snapshot?.memory_proposals?.length ?? 0
  const main = [
    { id: 'chat', icon: MessageSquare, label: t('对话', 'Chat') },
    { id: 'tasks', icon: ListTodo, label: t('任务', 'Tasks') },
    { id: 'memory', icon: Database, label: t('认知与记忆', 'Cognition & Memory') },
    { id: 'canvas', icon: MonitorPlay, label: t('画布', 'Canvas') },
    { id: 'files', icon: FileText, label: t('文件', 'Files') },
    { id: 'workflows', icon: GitBranch, label: t('工作流', 'Workflows') },
    { id: 'search', icon: Search, label: t('搜索', 'Search') },
  ] as const
  const secondary = [
    { id: 'evolve', icon: Beaker, label: t('自我进化', 'Self Evolve') },
    { id: 'metrics', icon: Activity, label: t('系统指标', 'Metrics') },
    { id: 'doctor', icon: Stethoscope, label: t('诊断', 'Diagnostics') },
    { id: 'settings', icon: Settings, label: t('设置', 'Settings') },
  ] as const
  const item = ({ id, icon: Icon, label }: typeof main[number] | typeof secondary[number]) => <button type="button" key={id} className={`rail-action ${activeView === id ? 'is-selected' : ''}`} aria-label={label} aria-current={activeView === id ? 'page' : undefined} data-tooltip={label} onClick={() => onNavigate(id)}>
    <Icon size={18} strokeWidth={1.65} />{id === 'memory' && pendingCount > 0 && <span className="rail-notice" />}
  </button>
  return <nav className="navigation-rail" aria-label={t('主导航', 'Main navigation')}>
    <button type="button" className="brand-mark" title="Promethea" aria-label="Promethea" onClick={() => onNavigate('chat')}>P<span /></button>
    <div className="rail-main">{main.map(item)}</div>
    <div className="rail-secondary">{secondary.map(item)}<button type="button" className="rail-action" aria-label={t('切换语言', 'Switch language')} data-tooltip={lang === 'zh' ? 'English' : '中文'} onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}><Languages size={17} /></button>
      <button type="button" className="rail-account" title={account} aria-label={account} onClick={onAccount}>{account.charAt(0).toUpperCase()}</button>
    </div>
  </nav>
}
