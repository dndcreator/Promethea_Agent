import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowLeft, Brain, CircleAlert, Database, Pencil, RefreshCw, Search, Trash2, X } from 'lucide-react'
import {
  decideMemoryWriteProposal,
  deleteMemoryEntry,
  getCognitionBundle,
  getMemoryEntries,
  getMemoryWriteProposals,
  searchMemoryEntries,
  updateMemoryEntry,
} from '../../services/api'
import type { CognitionBundle, MemoryProposalAction } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import CognitionSpace from './memory/CognitionSpace'

type Tab = 'cognition' | 'entries' | 'proposals'

export default function MemoryModal({ onClose }: { onClose: () => void }) {
  const { t } = useLanguage()
  const [activeTab, setActiveTab] = useState<Tab>('cognition')
  const [cognition, setCognition] = useState<CognitionBundle | null>(null)
  const [entries, setEntries] = useState<any[]>([])
  const [proposals, setProposals] = useState<any[]>([])
  const [selectedEntry, setSelectedEntry] = useState<any>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    void refresh(activeTab)
  }, [activeTab])

  const refresh = async (tab = activeTab) => {
    setLoading(true)
    try {
      if (tab === 'cognition') {
        const [bundle, proposalData] = await Promise.all([
          getCognitionBundle(),
          getMemoryWriteProposals('pending').then((response) => response.json()),
        ])
        setCognition(bundle)
        setProposals(proposalData.proposals || [])
      } else if (tab === 'entries') {
        const response = query.trim() ? await searchMemoryEntries(query, 200) : await getMemoryEntries()
        const data = await response.json()
        setEntries(data.entries || [])
      } else {
        const data = await getMemoryWriteProposals('pending').then((response) => response.json())
        setProposals(data.proposals || [])
      }
    } finally {
      setLoading(false)
    }
  }

  const editSelected = async () => {
    if (!selectedEntry?.memory_id) return
    const next = window.prompt(t('编辑记忆内容', 'Edit memory content'), selectedEntry.content || '')
    if (next === null || !next.trim()) return
    await updateMemoryEntry(selectedEntry.memory_id, next.trim())
    setSelectedEntry({ ...selectedEntry, content: next.trim() })
    await refresh('entries')
  }

  const deleteSelected = async () => {
    if (!selectedEntry?.memory_id || !window.confirm(t('删除这条记忆？', 'Delete this memory entry?'))) return
    await deleteMemoryEntry(selectedEntry.memory_id)
    setSelectedEntry(null)
    await refresh('entries')
  }

  const decideProposal = async (proposalId: string, action: MemoryProposalAction) => {
    await decideMemoryWriteProposal(proposalId, action)
    await refresh('proposals')
    setCognition(await getCognitionBundle())
    if (action === 'confirm_write' || action === 'confirm_write_keep_existing') {
      const data = await getMemoryEntries().then((response) => response.json())
      setEntries(data.entries || [])
    }
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/35 p-2 backdrop-blur-sm sm:p-6">
      <div className="flex h-[94vh] w-full max-w-[1280px] flex-col overflow-hidden rounded-lg border border-white/70 bg-[#f7f8f5] shadow-[0_28px_90px_rgba(31,33,31,0.22)] sm:h-[84vh]">
        <header className="flex min-h-[64px] items-center border-b border-black/5 bg-white/85 px-3 sm:px-5">
          <div className="hidden shrink-0 sm:block">
            <div className="text-[10px] font-semibold uppercase text-text-muted">Self Model</div>
            <h2 className="mt-0.5 text-base font-semibold text-text-strong">{t('认知工作台', 'Cognition Workbench')}</h2>
          </div>
          <nav className="flex h-16 min-w-0 items-stretch overflow-x-auto sm:ml-10" aria-label={t('认知工作台视图', 'Cognition workbench views')}>
            <TabButton active={activeTab === 'cognition'} onClick={() => setActiveTab('cognition')} icon={<Brain size={15} />}>
              {t('认知', 'Cognition')}
            </TabButton>
            <TabButton active={activeTab === 'entries'} onClick={() => setActiveTab('entries')} icon={<Database size={15} />}>
              {t('记忆', 'Memory')}
            </TabButton>
            <TabButton active={activeTab === 'proposals'} onClick={() => setActiveTab('proposals')} icon={<CircleAlert size={15} />} count={proposals.length}>
              {t('待确认', 'Review')}
            </TabButton>
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <button type="button" onClick={() => void refresh()} title={t('刷新', 'Refresh')} aria-label={t('刷新', 'Refresh')} className="grid h-9 w-9 place-items-center text-text-muted hover:text-text-strong disabled:opacity-40" disabled={loading}>
              <RefreshCw size={17} className={loading ? 'animate-spin' : ''} />
            </button>
            <button type="button" onClick={onClose} title={t('关闭', 'Close')} aria-label={t('关闭', 'Close')} className="grid h-9 w-9 place-items-center text-text-muted hover:text-text-strong">
              <X size={19} />
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1">
          {activeTab === 'cognition' && (
            <CognitionSpace
              bundle={cognition}
              loading={loading}
              onOpenReview={() => setActiveTab('proposals')}
            />
          )}
          {activeTab === 'entries' && (
            <MemoryEntries
              entries={entries}
              selected={selectedEntry}
              query={query}
              loading={loading}
              onQueryChange={setQuery}
              onSearch={() => void refresh('entries')}
              onSelect={setSelectedEntry}
              onEdit={editSelected}
              onDelete={deleteSelected}
            />
          )}
          {activeTab === 'proposals' && (
            <ProposalReview proposals={proposals.slice().reverse()} onDecide={decideProposal} />
          )}
        </main>
      </div>
    </div>
  )
}

function MemoryEntries({
  entries,
  selected,
  query,
  loading,
  onQueryChange,
  onSearch,
  onSelect,
  onEdit,
  onDelete,
}: {
  entries: any[]
  selected: any
  query: string
  loading: boolean
  onQueryChange: (value: string) => void
  onSearch: () => void
  onSelect: (entry: any) => void
  onEdit: () => void
  onDelete: () => void
}) {
  const { t } = useLanguage()
  return (
    <div className="grid h-full grid-cols-1 bg-[#f1f2ef] md:grid-cols-[360px_1fr]">
      <aside className={`min-h-0 border-r border-black/5 bg-white/65 ${selected ? 'hidden md:block' : 'block'}`}>
        <label className="m-4 flex h-10 items-center gap-2 border-b border-black/15 px-1 text-text-muted focus-within:border-black/40">
          <Search size={15} />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && onSearch()}
            type="search"
            placeholder={t('搜索记忆', 'Search memory')}
            className="min-w-0 flex-1 bg-transparent text-sm text-text-strong outline-none"
          />
        </label>
        <div className="h-[calc(100%-72px)] overflow-y-auto px-3 pb-4">
          {entries.map((entry) => (
            <button
              key={entry.memory_id || entry.id}
              type="button"
              onClick={() => onSelect(entry)}
              className={`w-full border-b border-black/5 px-2 py-3 text-left hover:bg-white/75 ${selected?.memory_id === entry.memory_id ? 'bg-white' : ''}`}
            >
              <div className="mb-1 text-[10px] font-semibold uppercase text-text-muted">{entry.memory_type || entry.type || 'memory'}</div>
              <div className="line-clamp-2 text-sm leading-6 text-text-normal">{entry.content}</div>
            </button>
          ))}
          {!loading && entries.length === 0 && <EmptyState>{t('没有记忆。', 'No memory entries.')}</EmptyState>}
        </div>
      </aside>
      <section className={`min-h-0 overflow-y-auto p-4 sm:p-7 ${selected ? 'block' : 'hidden md:block'}`}>
        {selected ? (
          <div className="mx-auto max-w-2xl">
            <div className="mb-7 flex items-center justify-between border-b border-black/5 pb-4">
              <div className="flex min-w-0 items-center gap-2">
                <button type="button" onClick={() => onSelect(null)} title={t('返回记忆列表', 'Back to memory list')} aria-label={t('返回记忆列表', 'Back to memory list')} className="grid h-9 w-9 shrink-0 place-items-center text-text-muted hover:text-text-strong md:hidden">
                  <ArrowLeft size={17} />
                </button>
                <div className="truncate text-xs font-semibold uppercase text-text-muted">{selected.memory_type || selected.type || 'memory'}</div>
              </div>
              <div className="flex gap-1">
                <IconButton label={t('编辑', 'Edit')} onClick={onEdit}><Pencil size={16} /></IconButton>
                <IconButton label={t('删除', 'Delete')} onClick={onDelete} danger><Trash2 size={16} /></IconButton>
              </div>
            </div>
            <p className="whitespace-pre-wrap text-base leading-8 text-text-strong">{selected.content || '-'}</p>
            <dl className="mt-8 grid grid-cols-1 gap-x-8 gap-y-4 border-t border-black/5 pt-5 text-xs sm:grid-cols-2">
              <DetailRow label={t('层级', 'Layer')} value={selected.source_layer || selected.layer || '-'} />
              <DetailRow label={t('更新时间', 'Updated')} value={formatTime(selected.updated_at || selected.created_at)} />
              <DetailRow label={t('状态', 'Status')} value={selected.status || 'active'} />
              <DetailRow label="ID" value={selected.memory_id || selected.id || '-'} />
            </dl>
          </div>
        ) : (
          <EmptyState>{t('选择一条记忆查看详情。', 'Select a memory to inspect.')}</EmptyState>
        )}
      </section>
    </div>
  )
}

function ProposalReview({ proposals, onDecide }: { proposals: any[]; onDecide: (proposalId: string, action: MemoryProposalAction) => Promise<void> }) {
  const { t } = useLanguage()
  const [busyId, setBusyId] = useState('')
  if (proposals.length === 0) return <div className="h-full bg-[#f1f2ef] p-8"><EmptyState>{t('暂无待确认认知。', 'No cognition requires review.')}</EmptyState></div>

  const decide = async (proposalId: string, action: MemoryProposalAction) => {
    setBusyId(`${proposalId}:${action}`)
    try {
      await onDecide(proposalId, action)
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f1f2ef] px-6 py-5">
      <div className="mx-auto max-w-4xl divide-y divide-black/5 border-y border-black/5 bg-white/55">
        {proposals.map((proposal) => {
          const proposalId = String(proposal.proposal_id || '')
          const conflicts = Array.isArray(proposal.conflict_candidates) ? proposal.conflict_candidates : []
          return (
            <article key={proposalId} className="px-5 py-5">
              <div className="flex items-start justify-between gap-6">
                <div className="min-w-0 flex-1">
                  <div className="mb-2 flex gap-3 text-[11px] text-text-muted">
                    <span className="font-semibold uppercase">{proposal.memory_type || 'memory'}</span>
                    <span>{formatTime(proposal.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-7 text-text-strong">{proposal.content || '-'}</p>
                  {conflicts.length > 0 && (
                    <div className="mt-4 border-l-2 border-amber-300 pl-4">
                      <div className="mb-1 text-xs font-semibold text-amber-800">{t('现有认知', 'Existing cognition')}</div>
                      {conflicts.map((conflict: unknown, index: number) => <p key={index} className="text-xs leading-6 text-text-normal">{String(conflict || '-')}</p>)}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <button type="button" disabled={!proposalId || Boolean(busyId)} onClick={() => void decide(proposalId, 'confirm_write')} className="border-b border-[#356c68] pb-1 text-xs font-semibold text-[#285956] disabled:opacity-40">
                    {t('确认并更新', 'Confirm & update')}
                  </button>
                  <button type="button" disabled={!proposalId || Boolean(busyId)} onClick={() => void decide(proposalId, 'confirm_write_keep_existing')} className="text-xs text-text-normal disabled:opacity-40">
                    {t('同时保留', 'Keep both')}
                  </button>
                  <button type="button" disabled={!proposalId || Boolean(busyId)} onClick={() => void decide(proposalId, 'ignore_once')} className="text-xs text-text-muted disabled:opacity-40">
                    {t('忽略', 'Ignore')}
                  </button>
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}

function TabButton({ active, onClick, icon, count, children }: { active: boolean; onClick: () => void; icon: ReactNode; count?: number; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={`flex shrink-0 items-center gap-2 border-b-2 px-2 text-sm font-medium sm:px-4 ${active ? 'border-[#356c68] text-[#285956]' : 'border-transparent text-text-muted hover:text-text-strong'}`}>
      {icon}<span>{children}</span>{Boolean(count) && <span className="text-[10px] text-amber-700">{count}</span>}
    </button>
  )
}

function IconButton({ label, onClick, danger = false, children }: { label: string; onClick: () => void; danger?: boolean; children: ReactNode }) {
  return <button type="button" title={label} aria-label={label} onClick={onClick} className={`grid h-9 w-9 place-items-center ${danger ? 'text-red-500 hover:text-red-700' : 'text-text-muted hover:text-text-strong'}`}>{children}</button>
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return <div><dt className="mb-1 text-text-muted">{label}</dt><dd className="break-all font-medium text-text-strong">{value}</dd></div>
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="grid min-h-[160px] place-items-center border border-dashed border-black/10 bg-white/45 px-6 text-center text-sm text-text-muted">{children}</div>
}

function formatTime(value: unknown) {
  if (!value) return '-'
  const numeric = Number(value)
  if (Number.isFinite(numeric)) return new Date(numeric * (numeric < 10000000000 ? 1000 : 1)).toLocaleString()
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}
