import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  decideMemoryWriteProposal,
  deleteMemoryEntry,
  getMemoryEntries,
  getMemoryGraph,
  getMemoryRecallRun,
  getMemoryRecallRuns,
  getMemoryWriteDecisions,
  getMemoryWriteProposals,
  searchMemoryEntries,
  searchMemoryGraph,
  updateMemoryEntry,
} from '../../services/api'
import type { MemoryProposalAction } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import JsonListView from './memory/JsonListView'
import MemoryAtlas from './memory/MemoryAtlas'
import MemoryStat from './memory/MemoryStat'

type Tab = 'entries' | 'proposals' | 'decisions' | 'recall' | 'graph'

type DetailRow = {
  label: string
  value: ReactNode
}

export default function MemoryModal({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<Tab>('entries')
  const [entries, setEntries] = useState<any[]>([])
  const [proposals, setProposals] = useState<any[]>([])
  const [decisions, setDecisions] = useState<any[]>([])
  const [recalls, setRecalls] = useState<any[]>([])
  const [graph, setGraph] = useState<any>(null)
  const [graphViewMode, setGraphViewMode] = useState<'atlas' | 'layer'>('atlas')
  const [selected, setSelected] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const { t } = useLanguage()

  useEffect(() => {
    void refresh(activeTab)
  }, [activeTab])

  const filteredEntries = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return entries
    return entries.filter((entry) => {
      const semanticKeys = Array.isArray(entry.semantic_keys) ? entry.semantic_keys.join(' ') : ''
      return `${entry.content || ''} ${semanticKeys}`.toLowerCase().includes(q)
    })
  }, [entries, query])

  const refresh = async (tab = activeTab) => {
    setLoading(true)
    try {
      if (tab === 'entries') {
        const data = await getMemoryEntries(query).then((res) => res.json())
        setEntries(data.entries || [])
      } else if (tab === 'proposals') {
        const data = await getMemoryWriteProposals('pending').then((res) => res.json())
        setProposals(data.proposals || [])
      } else if (tab === 'decisions') {
        const data = await getMemoryWriteDecisions().then((res) => res.json())
        setDecisions(data.events || [])
      } else if (tab === 'recall') {
        const data = await getMemoryRecallRuns().then((res) => res.json())
        setRecalls(data.runs || [])
      } else {
        const data = await getMemoryGraph().then((res) => res.json())
        setGraph(data)
      }
    } finally {
      setLoading(false)
    }
  }

  const editSelected = async () => {
    if (!selected?.memory_id) return
    const next = window.prompt(t('编辑记忆内容', 'Edit memory content'), selected.content || '')
    if (next === null) return
    await updateMemoryEntry(selected.memory_id, next)
    setSelected({ ...selected, content: next })
    await refresh('entries')
  }

  const deleteSelected = async () => {
    if (!selected?.memory_id || !window.confirm(t('删除这条记忆？', 'Delete this memory entry?'))) return
    await deleteMemoryEntry(selected.memory_id)
    setSelected(null)
    await refresh('entries')
  }

  const openRecall = async (requestId: string) => {
    setDetail(null)
    const data = await getMemoryRecallRun(requestId).then((res) => res.json())
    setDetail(data.run || data)
  }

  const runEntrySearch = async () => {
    setLoading(true)
    try {
      const q = query.trim()
      const data = q
        ? await searchMemoryEntries(q, 100).then((res) => res.json())
        : await getMemoryEntries().then((res) => res.json())
      setEntries(data.entries || [])
    } finally {
      setLoading(false)
    }
  }

  const focusGraph = async (nextQuery: string) => {
    const data = await searchMemoryGraph(nextQuery, 2, 90, 180).then((res) => res.json())
    setGraph(data)
    return data
  }

  const decideProposal = async (proposalId: string, action: MemoryProposalAction) => {
    await decideMemoryWriteProposal(proposalId, action)
    await refresh('proposals')
    await refresh('decisions')
    if (action === 'confirm_write' || action === 'confirm_write_keep_existing') {
      await refresh('entries')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[1200px] h-[80vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('记忆工作台', 'Memory Workbench')}</h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>

        <div className="flex border-b border-black/5 bg-white px-4 pt-2 gap-4">
          <TabButton active={activeTab === 'entries'} onClick={() => setActiveTab('entries')}>{t('记忆条目', 'Entries')}</TabButton>
          <TabButton active={activeTab === 'proposals'} onClick={() => setActiveTab('proposals')}>{t('待确认', 'Pending Review')}</TabButton>
          <TabButton active={activeTab === 'decisions'} onClick={() => setActiveTab('decisions')}>{t('写入审计', 'Write Audit')}</TabButton>
          <TabButton active={activeTab === 'recall'} onClick={() => setActiveTab('recall')}>{t('召回记录', 'Recall Runs')}</TabButton>
          <TabButton active={activeTab === 'graph'} onClick={() => setActiveTab('graph')}>{t('图结构', 'Graph')}</TabButton>
          <button type="button" onClick={() => refresh()} className="ml-auto px-3 py-2 text-sm text-brand-600 hover:text-brand-700">
            {loading ? t('加载中...', 'Loading...') : t('刷新', 'Refresh')}
          </button>
        </div>

        <div className="flex-1 overflow-hidden bg-bg-page">
          {activeTab === 'entries' && (
            <div className="grid grid-cols-[360px_1fr] h-full">
              <aside className="border-r border-black/5 p-4 overflow-y-auto bg-white/60">
                <div className="mb-4 flex gap-2">
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && runEntrySearch()}
                    type="search"
                    placeholder={t('搜索记忆内容...', 'Search memory...')}
                    className="min-w-0 flex-1 rounded border p-2 text-sm"
                  />
                  <button type="button" onClick={runEntrySearch} className="rounded bg-gray-100 px-3 text-sm text-text-normal">
                    {t('搜索', 'Search')}
                  </button>
                </div>
                <div className="flex flex-col gap-2">
                  {filteredEntries.map((entry) => (
                    <button key={entry.memory_id || entry.id} type="button" onClick={() => setSelected(entry)} className="p-3 bg-white border rounded shadow-sm text-xs cursor-pointer hover:border-brand-300 text-left">
                      <div className="font-semibold text-brand-600 mb-1">{entry.memory_type || entry.type || 'memory'}</div>
                      <div className="truncate text-text-normal">{entry.content}</div>
                    </button>
                  ))}
                  {filteredEntries.length === 0 && <div className="text-text-muted text-sm text-center mt-10">{t('未找到记忆条目。', 'No entries found.')}</div>}
                </div>
              </aside>
              <section className="p-6 overflow-y-auto">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold text-text-strong">{t('条目详情', 'Entry Detail')}</h3>
                  <div className="flex gap-2">
                    <button type="button" disabled={!selected} onClick={editSelected} className="px-3 py-1.5 bg-gray-100 rounded text-sm disabled:opacity-50">{t('编辑', 'Edit')}</button>
                    <button type="button" disabled={!selected} onClick={deleteSelected} className="px-3 py-1.5 bg-red-50 text-red-600 rounded text-sm disabled:opacity-50">{t('删除', 'Delete')}</button>
                  </div>
                </div>
                {selected ? <EntryDetail entry={selected} /> : <EmptyState>{t('选择一条记忆查看详情。', 'Select an entry to view details.')}</EmptyState>}
              </section>
            </div>
          )}

          {activeTab === 'proposals' && (
            <ProposalReview
              proposals={proposals.slice().reverse()}
              onDecide={decideProposal}
              empty={t('暂无待确认的记忆冲突。', 'No pending memory conflicts.')}
            />
          )}

          {activeTab === 'decisions' && (
            <JsonListView rows={decisions.slice().reverse()} empty={t('暂无写入决策。', 'No write decisions.')} />
          )}

          {activeTab === 'recall' && (
            <div className="grid grid-cols-[380px_1fr] h-full">
              <JsonListView
                rows={recalls.slice().reverse()}
                empty={t('暂无召回记录。', 'No recall runs.')}
                onSelect={(row) => openRecall(row.request_id)}
              />
              <div className="m-4 overflow-auto rounded border bg-white p-4">
                {detail ? <RecallDetail detail={detail} /> : <EmptyState>{t('选择一次召回查看上下文。', 'Select a recall run to view context.')}</EmptyState>}
              </div>
            </div>
          )}

          {activeTab === 'graph' && (
            <div className="h-full p-6 overflow-auto">
              <div className="grid grid-cols-5 gap-3 mb-4">
                <MemoryStat label={t('节点', 'Nodes')} value={graph?.stats?.total_nodes || graph?.nodes?.length || 0} />
                <MemoryStat label={t('边', 'Edges')} value={graph?.stats?.total_edges || graph?.edges?.length || 0} />
                <MemoryStat label="Hot" value={graph?.stats?.layers?.hot || 0} />
                <MemoryStat label="Warm" value={graph?.stats?.layers?.warm || 0} />
                <MemoryStat label="Cold" value={graph?.stats?.layers?.cold || 0} />
              </div>
              <div className="mb-3 flex justify-end gap-2">
                <button type="button" onClick={() => setGraphViewMode('atlas')} className={`rounded px-3 py-1.5 text-xs font-semibold ${graphViewMode === 'atlas' ? 'bg-brand-600 text-white' : 'bg-white text-text-muted'}`}>
                  Atlas
                </button>
                <button type="button" onClick={() => setGraphViewMode('layer')} className={`rounded px-3 py-1.5 text-xs font-semibold ${graphViewMode === 'layer' ? 'bg-brand-600 text-white' : 'bg-white text-text-muted'}`}>
                  Layer
                </button>
              </div>
              {graphViewMode === 'atlas' ? <MemoryAtlas graph={graph} onSearch={focusGraph} /> : <MemoryGraphView graph={graph} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ProposalReview({
  proposals,
  onDecide,
  empty,
}: {
  proposals: any[]
  onDecide: (proposalId: string, action: MemoryProposalAction) => Promise<void>
  empty: string
}) {
  const { t } = useLanguage()
  const [busyId, setBusyId] = useState('')

  if (proposals.length === 0) {
    return <div className="p-6"><EmptyState>{empty}</EmptyState></div>
  }

  const handleDecision = async (proposalId: string, action: MemoryProposalAction) => {
    setBusyId(`${proposalId}:${action}`)
    try {
      await onDecide(proposalId, action)
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="grid gap-3">
        {proposals.map((proposal) => {
          const proposalId = String(proposal.proposal_id || '')
          const conflicts = Array.isArray(proposal.conflict_candidates) ? proposal.conflict_candidates : []
          return (
            <article key={proposalId} className="rounded-xl border border-amber-100 bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div>
                  <div className="mb-1 flex items-center gap-2 text-xs text-text-muted">
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-700">{proposal.memory_type || 'memory'}</span>
                    <span>{formatTime(proposal.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-7 text-text-strong">{proposal.content || '-'}</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <DecisionButton disabled={!proposalId || Boolean(busyId)} onClick={() => handleDecision(proposalId, 'confirm_write')}>
                    {busyId === `${proposalId}:confirm_write` ? t('写入中...', 'Writing...') : t('写入并替代', 'Write & Replace')}
                  </DecisionButton>
                  <DecisionButton disabled={!proposalId || Boolean(busyId)} tone="muted" onClick={() => handleDecision(proposalId, 'confirm_write_keep_existing')}>
                    {busyId === `${proposalId}:confirm_write_keep_existing` ? t('写入中...', 'Writing...') : t('仅写入', 'Write Only')}
                  </DecisionButton>
                  <DecisionButton disabled={!proposalId || Boolean(busyId)} tone="muted" onClick={() => handleDecision(proposalId, 'ignore_once')}>
                    {t('忽略本次', 'Ignore')}
                  </DecisionButton>
                  <DecisionButton disabled={!proposalId || Boolean(busyId)} tone="muted" onClick={() => handleDecision(proposalId, 'reduce_similar')}>
                    {t('减少类似', 'Reduce Similar')}
                  </DecisionButton>
                </div>
              </div>
              {conflicts.length > 0 && (
                <section className="rounded-lg bg-amber-50/70 p-3">
                  <h4 className="mb-2 text-xs font-semibold text-amber-800">{t('冲突候选', 'Conflicting memories')}</h4>
                  <div className="grid gap-2">
                    {conflicts.map((conflict: unknown, index: number) => (
                      <p key={`${proposalId}-conflict-${index}`} className="text-xs leading-6 text-text-normal">{String(conflict || '-')}</p>
                    ))}
                  </div>
                </section>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}

function DecisionButton({
  children,
  disabled,
  onClick,
  tone = 'primary',
}: {
  children: ReactNode
  disabled?: boolean
  onClick: () => void
  tone?: 'primary' | 'muted'
}) {
  const classes =
    tone === 'primary'
      ? 'bg-brand-600 text-white hover:bg-brand-700'
      : 'bg-gray-100 text-text-normal hover:bg-gray-200'

  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${classes}`}>
      {children}
    </button>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        active ? 'border-brand-500 text-brand-600' : 'border-transparent text-text-muted hover:text-text-strong'
      }`}
    >
      {children}
    </button>
  )
}

function EntryDetail({ entry }: { entry: any }) {
  const { t } = useLanguage()
  const rows: DetailRow[] = [
    { label: t('类型', 'Type'), value: entry.memory_type || entry.type || 'memory' },
    { label: t('层级', 'Layer'), value: entry.source_layer || entry.layer || '-' },
    { label: t('分数', 'Score'), value: entry.score ?? entry.confidence ?? '-' },
    { label: t('创建时间', 'Created'), value: formatTime(entry.created_at || entry.timestamp) },
    { label: 'ID', value: entry.memory_id || entry.id || '-' },
  ]

  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <p className="mb-5 whitespace-pre-wrap text-sm leading-7 text-text-strong">{entry.content || '-'}</p>
      <DetailGrid rows={rows} />
      {Array.isArray(entry.semantic_keys) && entry.semantic_keys.length > 0 && (
        <TagGroup title={t('语义键', 'Semantic keys')} tags={entry.semantic_keys} />
      )}
    </div>
  )
}

function RecallDetail({ detail }: { detail: any }) {
  const { t } = useLanguage()
  const records = Array.isArray(detail.memory_records) ? detail.memory_records : []
  return (
    <div className="space-y-4">
      <DetailGrid
        rows={[
          { label: t('请求', 'Request'), value: detail.request_id || '-' },
          { label: t('会话', 'Session'), value: detail.session_id || '-' },
          { label: t('策略', 'Policy'), value: detail.policy || '-' },
          { label: t('召回数量', 'Records'), value: records.length },
          { label: t('丢弃数量', 'Dropped'), value: detail.dropped_count ?? 0 },
        ]}
      />
      {(detail.formatted_context || detail.summary) && (
        <section>
          <h4 className="mb-2 text-sm font-semibold text-text-strong">{t('召回上下文', 'Recall context')}</h4>
          <p className="whitespace-pre-wrap rounded-xl bg-bg-page p-3 text-sm leading-7 text-text-normal">{detail.formatted_context || detail.summary}</p>
        </section>
      )}
      <section>
        <h4 className="mb-2 text-sm font-semibold text-text-strong">{t('命中的记忆', 'Matched memories')}</h4>
        <div className="space-y-2">
          {records.map((record: any, index: number) => (
            <div key={record.memory_id || record.id || index} className="rounded-xl border border-black/5 bg-bg-card p-3">
              <div className="mb-1 flex items-center justify-between text-xs text-text-muted">
                <span>{record.memory_type || record.type || 'memory'}</span>
                <span>{record.score ?? record.confidence ?? ''}</span>
              </div>
              <p className="text-sm leading-6 text-text-normal">{record.content || record.text || '-'}</p>
            </div>
          ))}
          {records.length === 0 && <EmptyState>{t('本次没有命中记忆。', 'No memories matched this run.')}</EmptyState>}
        </div>
      </section>
    </div>
  )
}

function MemoryGraphView({ graph }: { graph: any }) {
  const { t } = useLanguage()
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const edges = Array.isArray(graph?.edges) ? graph.edges : []
  const [visibleLayers, setVisibleLayers] = useState<string[]>(['hot', 'warm', 'cold', 'other'])
  const [nodeLimit, setNodeLimit] = useState(24)
  const [showEdges, setShowEdges] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const layout = useMemo(() => buildMemoryGraphLayout(nodes, edges, visibleLayers, nodeLimit), [nodes, edges, visibleLayers, nodeLimit])
  const semanticMode = String(graph?.graph_semantics || (graph?.graph_mode === 'neo4j' ? 'semantic' : graph?.graph_mode === 'sqlite_graph' ? 'lightweight' : 'none'))
  const selectedNode = layout.nodes.find((node) => node.id === selectedNodeId) || null
  const toggleLayer = (layer: string) => {
    setVisibleLayers((current) => current.includes(layer) ? current.filter((item) => item !== layer) : [...current, layer])
  }

  if (!graph) return <EmptyState>{t('暂无图数据。', 'No graph data.')}</EmptyState>

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-black/5 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-text-strong">{t('分层记忆图', 'Layered memory graph')}</h3>
            <p className="mt-1 text-xs text-text-muted">
              {semanticMode === 'semantic'
                ? t('Neo4j 语义图：按持久化层级拆分，按需查看关系。', 'Neo4j semantic graph: separated by persistence layer with optional relationships.')
                : semanticMode === 'lightweight'
                  ? t('SQLite 轻量图：展示 token/MEF 关系，不等同 Neo4j 语义图。', 'SQLite lightweight graph: token/MEF relationships, not the Neo4j semantic graph.')
                  : t('当前后端没有可展示的图结构。', 'The current backend has no graph structure to display.')}
            </p>
          </div>
          <span className="inline-flex items-center rounded-full bg-bg-page px-2 py-1 text-[11px] font-semibold text-text-muted">
            {graph?.graph_mode || 'none'} · {semanticMode}
          </span>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-3 border-y border-black/5 py-3 text-xs">
          <div className="flex items-center gap-1">
            {layout.lanes.map((lane) => (
              <button
                key={lane.key}
                type="button"
                onClick={() => toggleLayer(lane.key)}
                className={`rounded px-2 py-1 font-semibold transition-colors ${visibleLayers.includes(lane.key) ? 'text-white' : 'bg-bg-page text-text-muted'}`}
                style={visibleLayers.includes(lane.key) ? { backgroundColor: lane.color } : undefined}
              >
                {lane.label} {lane.total}
              </button>
            ))}
          </div>
          <label className="ml-auto inline-flex items-center gap-2 text-text-normal">
            <input type="checkbox" checked={showEdges} onChange={(event) => setShowEdges(event.target.checked)} />
            {t('显示关系', 'Show edges')}
          </label>
          <label className="inline-flex items-center gap-2 text-text-normal">
            {t('节点密度', 'Node density')}
            <select value={nodeLimit} onChange={(event) => setNodeLimit(Number(event.target.value))} className="rounded border border-black/10 bg-white px-2 py-1">
              <option value={12}>12</option>
              <option value={24}>24</option>
              <option value={48}>48</option>
              <option value={96}>96</option>
            </select>
          </label>
        </div>
        {layout.nodes.length > 0 ? (
          <div className="overflow-auto rounded-lg border border-black/5 bg-bg-page">
            <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="min-w-[920px]" style={{ width: '100%', height: Math.max(420, layout.height) }}>
              {layout.lanes.filter((lane) => lane.visible).map((lane) => (
                <g key={lane.key}>
                  <rect x="0" y={lane.y} width={layout.width} height={lane.height} fill={lane.background} />
                  <line x1="0" y1={lane.y + lane.height} x2={layout.width} y2={lane.y + lane.height} stroke={lane.color} strokeOpacity="0.18" />
                  <text x="24" y={lane.y + 30} className="fill-text-strong text-[13px] font-bold">{lane.label}</text>
                  <text x="24" y={lane.y + 49} className="fill-text-muted text-[10px]">{lane.description}</text>
                  <text x="24" y={lane.y + 67} className="fill-text-muted text-[10px]">{lane.visibleCount} / {lane.total}</text>
                </g>
              ))}
              {showEdges && layout.edges.map((edge) => (
                <path key={edge.id} d={`M ${edge.source.x} ${edge.source.y} C ${edge.source.x + 48} ${edge.source.y}, ${edge.target.x - 48} ${edge.target.y}, ${edge.target.x} ${edge.target.y}`} fill="none" stroke={edge.color} strokeWidth={edge.width} strokeOpacity="0.35" />
              ))}
              {layout.nodes.map((node) => (
                <g key={node.id} onClick={() => setSelectedNodeId(node.id)} className="cursor-pointer">
                  <rect x={node.x - 62} y={node.y - 24} width="124" height="48" rx="6" fill={selectedNodeId === node.id ? node.color : '#ffffff'} stroke={node.color} strokeWidth={selectedNodeId === node.id ? 2.5 : 1.5} />
                  <text x={node.x - 52} y={node.y - 6} className={selectedNodeId === node.id ? 'fill-white text-[10px] font-bold' : 'fill-text-strong text-[10px] font-bold'}>{node.shortType}</text>
                  <text x={node.x - 52} y={node.y + 12} className={selectedNodeId === node.id ? 'fill-white/90 text-[10px]' : 'fill-text-muted text-[10px]'}>{node.label}</text>
                </g>
              ))}
            </svg>
          </div>
        ) : (
          <EmptyState>{t('没有节点。', 'No nodes.')}</EmptyState>
        )}
      </section>
      <div className="grid grid-cols-[1fr_360px] gap-4">
        <section className="rounded-lg border border-black/5 bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-text-strong">{t('当前视图', 'Current view')}</h3>
          <div className="grid grid-cols-3 gap-3 text-xs">
            <MemoryStat label={t('可见节点', 'Visible nodes')} value={layout.nodes.length} />
            <MemoryStat label={t('可见关系', 'Visible edges')} value={layout.edges.length} />
            <MemoryStat label={t('隐藏节点', 'Hidden nodes')} value={Math.max(0, nodes.length - layout.nodes.length)} />
          </div>
        </section>
        <section className="rounded-lg border border-black/5 bg-white p-4 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-text-strong">{t('节点详情', 'Node detail')}</h3>
          {selectedNode ? (
            <div className="space-y-2 text-xs">
              <div className="font-semibold text-brand-700">{selectedNode.layer.toUpperCase()} · {selectedNode.type}</div>
              <p className="break-words leading-6 text-text-normal">{selectedNode.content || '-'}</p>
              <div className="break-all font-mono text-[10px] text-text-muted">{selectedNode.id}</div>
            </div>
          ) : (
            <p className="text-xs leading-6 text-text-muted">{t('点击图中的节点查看完整内容。', 'Select a node in the graph to inspect its full content.')}</p>
          )}
        </section>
      </div>
    </div>
  )
}

function buildMemoryGraphLayout(nodes: any[], edges: any[], visibleLayers: string[], nodeLimit: number) {
  const width = 920
  const palette: Record<string, string> = {
    hot: '#ef4444',
    warm: '#f59e0b',
    cold: '#2563eb',
    other: '#64748b',
    preference: '#7c3aed',
    project_state: '#059669',
    concept: '#0891b2',
    message: '#475569',
    summary: '#16a34a',
    token: '#f97316',
    identity: '#111827',
    memory: '#64748b',
  }
  const edgePalette: Record<string, string> = {
    from_message: '#7c3aed',
    summarizes: '#16a34a',
    cooccurs: '#f97316',
    related: '#2563eb',
    semantic_link: '#0891b2',
    supersedes: '#dc2626',
  }
  const laneMeta = [
    { key: 'hot', label: 'HOT', description: 'L1 · recent / direct', color: palette.hot, background: '#fef2f2' },
    { key: 'warm', label: 'WARM', description: 'L2 · concept / related', color: palette.warm, background: '#fffbeb' },
    { key: 'cold', label: 'COLD', description: 'L3 · summary / archive', color: palette.cold, background: '#eff6ff' },
    { key: 'other', label: 'OTHER', description: 'unclassified nodes', color: palette.other, background: '#f8fafc' },
  ]
  const normalized = nodes.map((node, index) => {
    const id = String(node.id || node.memory_id || node.node_id || `node-${index + 1}`)
    const layer = normalizeMemoryLayer(node) || 'other'
    const type = normalizeNodeType(node)
    return {
      raw: node,
      id,
      layer,
      type,
      label: compactLabel(node.label || node.title || node.content || node.text || id, 18),
      shortType: compactLabel(type, 14).toUpperCase(),
      content: node.label || node.title || node.content || node.text || id,
      color: palette[type] || palette[layer] || palette.memory,
    }
  })
  const filtered = normalized.filter((node) => visibleLayers.includes(node.layer))
  const perLaneLimit = Math.max(1, Math.ceil(nodeLimit / Math.max(1, visibleLayers.length)))
  const visibleNodes = laneMeta.flatMap((lane) => filtered.filter((node) => node.layer === lane.key).slice(0, perLaneLimit))
  const visibleLaneMeta = laneMeta.filter((lane) => visibleLayers.includes(lane.key))
  const positioned = visibleNodes.map((node) => {
    const laneIndex = visibleLaneMeta.findIndex((lane) => lane.key === node.layer)
    const laneNodes = visibleNodes.filter((item) => item.layer === node.layer)
    const index = laneNodes.findIndex((item) => item.id === node.id)
    return {
      ...node,
      x: 212 + (index % 5) * 140,
      y: laneIndex * 120 + 58 + Math.floor(index / 5) * 62,
    }
  })
  const laneHeights = visibleLaneMeta.map((lane) => {
    const count = positioned.filter((node) => node.layer === lane.key).length
    return Math.max(120, 40 + Math.ceil(count / 5) * 62)
  })
  let laneOffset = 0
  const lanes = laneMeta.map((lane) => {
    const visibleIndex = visibleLaneMeta.findIndex((item) => item.key === lane.key)
    const visible = visibleIndex >= 0
    const height = visible ? laneHeights[visibleIndex] : 0
    const y = visible ? laneOffset : 0
    if (visible) laneOffset += height
    return {
      ...lane,
      visible,
      y,
      height,
      total: normalized.filter((node) => node.layer === lane.key).length,
      visibleCount: positioned.filter((node) => node.layer === lane.key).length,
    }
  })
  positioned.forEach((node) => {
    const lane = lanes.find((item) => item.key === node.layer)
    if (lane) node.y += lane.y - visibleLaneMeta.findIndex((item) => item.key === node.layer) * 120
  })
  const byId = new Map(positioned.map((node) => [node.id, node]))
  const drawnEdges = edges.map((edge, index) => {
    const sourceId = String(edge.source || edge.from || edge.source_id || '')
    const targetId = String(edge.target || edge.to || edge.target_id || '')
    const source = byId.get(sourceId)
    const target = byId.get(targetId)
    if (!source || !target) return null
    const edgeType = normalizeEdgeType(edge)
    const label = compactLabel(edgeType, 12)
    return {
      id: String(edge.id || `${sourceId}-${targetId}-${index}`),
      source,
      target,
      label,
      color: edgePalette[edgeType] || source.color,
      width: 1.5 + Math.min(2.5, Math.max(0, Number(edge.weight || edge.score || 0))),
    }
  }).filter(Boolean) as Array<any>
  return {
    nodes: positioned,
    edges: drawnEdges,
    lanes,
    width,
    height: Math.max(420, laneOffset),
  }
}

function normalizeMemoryLayer(node: any) {
  const raw = node?.layer ?? node?.source_layer ?? node?.memory_layer ?? ''
  if (raw === 0 || raw === '0') return 'hot'
  if (raw === 1 || raw === '1') return 'warm'
  if (raw === 2 || raw === '2') return 'cold'
  const text = String(raw || '').trim().toLowerCase()
  if (['hot', 'warm', 'cold'].includes(text)) return text
  if (['direct', 'recent', 'raw_log', 'message'].includes(text)) return 'hot'
  if (['concept', 'related', 'semantic', 'token'].includes(text)) return 'warm'
  if (['summary', 'archive', 'long_term'].includes(text)) return 'cold'
  return ''
}

function normalizeNodeType(node: any) {
  const raw = String(node?.memory_type || node?.type || node?.node_type || node?.role || 'memory').trim().toLowerCase()
  if (raw.includes('project')) return 'project_state'
  if (raw.includes('prefer')) return 'preference'
  if (raw.includes('identity')) return 'identity'
  if (raw.includes('concept')) return 'concept'
  if (raw.includes('summary')) return 'summary'
  if (raw.includes('message')) return 'message'
  if (raw.includes('token')) return 'token'
  return raw || 'memory'
}

function normalizeEdgeType(edge: any) {
  return String(edge?.relation || edge?.type || edge?.edge_type || edge?.label || 'related').trim().toLowerCase()
}

function compactLabel(value: unknown, maxLength: number) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text || '-'
  return `${text.slice(0, Math.max(1, maxLength - 1))}…`
}

function DetailGrid({ rows }: { rows: DetailRow[] }) {
  return (
    <dl className="grid grid-cols-2 gap-3 text-xs">
      {rows.map((row) => (
        <div key={row.label} className="rounded-lg bg-bg-page px-3 py-2">
          <dt className="mb-1 text-text-muted">{row.label}</dt>
          <dd className="break-words font-medium text-text-strong">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function TagGroup({ title, tags }: { title: string; tags: string[] }) {
  return (
    <section className="mt-4">
      <h4 className="mb-2 text-xs font-semibold text-text-muted">{title}</h4>
      <div className="flex flex-wrap gap-2">
        {tags.map((tag) => (
          <span key={tag} className="rounded-full bg-brand-100 px-2 py-1 text-xs font-medium text-brand-700">{tag}</span>
        ))}
      </div>
    </section>
  )
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-black/10 bg-white/70 p-6 text-center text-sm text-text-muted">{children}</div>
}

function formatTime(value: unknown) {
  if (!value) return '-'
  const numeric = Number(value)
  if (Number.isFinite(numeric)) {
    return new Date(numeric * (numeric < 10000000000 ? 1000 : 1)).toLocaleString()
  }
  return String(value)
}
