import { useMemo, useState } from 'react'
import { LayoutList, Orbit, Search, X } from 'lucide-react'
import type { CognitionBundle, CognitionItem } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'

type ViewMode = 'space' | 'list'

type Props = {
  bundle: CognitionBundle | null
  loading: boolean
  onOpenReview: () => void
}

const STATE_ORDER = ['current', 'evolving', 'uncertain', 'historical'] as const

export default function CognitionSpace({ bundle, loading, onOpenReview }: Props) {
  const { t } = useLanguage()
  const [mode, setMode] = useState<ViewMode>('space')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<CognitionItem | null>(null)
  const items = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    const rows = Array.isArray(bundle?.items) ? bundle.items : []
    if (!normalized) return rows
    return rows.filter((item) => `${item.content} ${item.kind} ${item.domain}`.toLocaleLowerCase().includes(normalized))
  }, [bundle, query])
  const visibleItems = useMemo(
    () => items.slice().sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0)).slice(0, 12),
    [items],
  )
  const stats = bundle?.stats || {}
  const stateStats = (stats.states || {}) as Record<string, number>

  return (
    <div className="relative h-full overflow-hidden bg-[#f1f2ef] text-text-strong">
      <header className="relative z-20 flex min-h-[58px] items-center gap-2 border-b border-black/5 bg-white/70 px-3 backdrop-blur-md sm:gap-4 sm:px-5">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{t('意识空间', 'Cognition Space')}</div>
          <div className="mt-0.5 hidden flex-wrap gap-x-3 text-[11px] text-text-muted sm:flex">
            <span>{t(`当前 ${stateStats.current || 0}`, `Current ${stateStats.current || 0}`)}</span>
            <span>{t(`演化中 ${stateStats.evolving || 0}`, `Evolving ${stateStats.evolving || 0}`)}</span>
            <span>{t(`待确认 ${stateStats.uncertain || 0}`, `Uncertain ${stateStats.uncertain || 0}`)}</span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {mode === 'list' && (
            <label className="flex h-9 w-[120px] items-center gap-2 border-b border-black/15 px-2 text-text-muted focus-within:border-black/40 sm:w-[240px]">
              <Search size={15} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('搜索认知', 'Search cognition')}
                className="min-w-0 flex-1 bg-transparent text-sm text-text-strong outline-none"
              />
            </label>
          )}
          <div className="flex border border-black/10 bg-white p-0.5">
            <button
              type="button"
              title={t('空间视图', 'Space view')}
              aria-label={t('空间视图', 'Space view')}
              onClick={() => setMode('space')}
              className={`grid h-8 w-8 place-items-center ${mode === 'space' ? 'bg-[#2f3c39] text-white' : 'text-text-muted hover:text-text-strong'}`}
            >
              <Orbit size={16} />
            </button>
            <button
              type="button"
              title={t('列表视图', 'List view')}
              aria-label={t('列表视图', 'List view')}
              onClick={() => setMode('list')}
              className={`grid h-8 w-8 place-items-center ${mode === 'list' ? 'bg-[#2f3c39] text-white' : 'text-text-muted hover:text-text-strong'}`}
            >
              <LayoutList size={16} />
            </button>
          </div>
        </div>
      </header>

      <div className="h-[calc(100%-58px)]">
        {loading ? (
          <div className="grid h-full place-items-center text-sm text-text-muted">{t('正在整理认知…', 'Organizing cognition…')}</div>
        ) : items.length === 0 ? (
          <div className="grid h-full place-items-center px-8 text-center text-sm text-text-muted">
            {t('还没有形成可以展示的认知。', 'No cognition is available yet.')}
          </div>
        ) : mode === 'space' ? (
          <CognitionCanvas items={visibleItems} selectedId={selected?.cognition_id || ''} onSelect={setSelected} />
        ) : (
          <CognitionList items={items} selectedId={selected?.cognition_id || ''} onSelect={setSelected} />
        )}
      </div>

      {selected && (
        <CognitionDetail
          item={selected}
          onClose={() => setSelected(null)}
          onOpenReview={onOpenReview}
        />
      )}
    </div>
  )
}

function CognitionCanvas({
  items,
  selectedId,
  onSelect,
}: {
  items: CognitionItem[]
  selectedId: string
  onSelect: (item: CognitionItem) => void
}) {
  return (
    <div className="relative h-full overflow-hidden cognition-field">
      {items.map((item, index) => {
        const position = cognitionPosition(item.cognition_id, index)
        const selected = selectedId === item.cognition_id
        return (
          <button
            key={item.cognition_id}
            type="button"
            onClick={() => onSelect(item)}
            className={`cognition-thought absolute max-w-[40vw] text-left leading-7 transition-colors focus:outline-none sm:max-w-[260px] ${
              selected ? 'text-[#17201e]' : stateTextColor(item.state || 'current')
            }`}
            style={{
              left: `${position.left}%`,
              top: `${position.top}%`,
              fontSize: `${14 + Math.round(Number(item.importance || 0.5) * 5)}px`,
              animationDelay: `${position.delay}s`,
              animationDuration: `${position.duration}s`,
            }}
          >
            <span className={`mr-2 inline-block h-1.5 w-1.5 rounded-full align-middle ${stateDotColor(item.state || 'current')}`} />
            <span>{item.content}</span>
          </button>
        )
      })}
      <div className="pointer-events-none absolute inset-x-[12%] top-1/2 h-px bg-black/[0.04]" />
      <div className="pointer-events-none absolute bottom-[12%] top-[12%] left-1/2 w-px bg-black/[0.035]" />
    </div>
  )
}

function CognitionList({
  items,
  selectedId,
  onSelect,
}: {
  items: CognitionItem[]
  selectedId: string
  onSelect: (item: CognitionItem) => void
}) {
  const { t } = useLanguage()
  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      {STATE_ORDER.map((state) => {
        const rows = items.filter((item) => item.state === state)
        if (rows.length === 0) return null
        return (
          <section key={state} className="mb-7">
            <div className="mb-2 flex items-center gap-2 border-b border-black/5 pb-2 text-xs font-semibold text-text-muted">
              <span className={`h-1.5 w-1.5 rounded-full ${stateDotColor(state)}`} />
              {stateLabel(state, t)}
              <span className="font-normal">{rows.length}</span>
            </div>
            <div>
              {rows.map((item) => (
                <button
                  key={item.cognition_id}
                  type="button"
                  onClick={() => onSelect(item)}
                  className={`grid w-full grid-cols-[1fr_80px] items-center gap-3 border-b border-black/[0.045] px-2 py-3 text-left text-sm hover:bg-white/60 sm:grid-cols-[1fr_110px_150px] sm:gap-4 ${
                    selectedId === item.cognition_id ? 'bg-white/80' : ''
                  }`}
                >
                  <span className="line-clamp-2 text-text-strong">{item.content}</span>
                  <span className="text-xs text-text-muted">{domainLabel(item.domain || 'world', t)}</span>
                  <span className="hidden text-right text-xs text-text-muted sm:block">{formatTime(item.updated_at)}</span>
                </button>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function CognitionDetail({
  item,
  onClose,
  onOpenReview,
}: {
  item: CognitionItem
  onClose: () => void
  onOpenReview: () => void
}) {
  const { t } = useLanguage()
  return (
    <aside className="absolute inset-y-0 right-0 z-30 w-full border-l border-black/10 bg-white/95 p-6 shadow-[-18px_0_45px_rgba(31,33,31,0.08)] backdrop-blur-md sm:w-[360px]">
      <button type="button" onClick={onClose} aria-label={t('关闭详情', 'Close detail')} title={t('关闭详情', 'Close detail')} className="absolute right-4 top-4 grid h-8 w-8 place-items-center text-text-muted hover:text-text-strong">
        <X size={17} />
      </button>
      <div className="pr-8 text-[11px] font-semibold uppercase text-text-muted">{domainLabel(item.domain || 'world', t)} · {stateLabel(item.state || 'current', t)}</div>
      <p className="mt-6 whitespace-pre-wrap text-base leading-8 text-text-strong">{item.content}</p>
      <dl className="mt-8 space-y-4 border-t border-black/5 pt-5 text-xs">
        <DetailRow label={t('类型', 'Type')} value={item.kind || 'memory'} />
        <DetailRow label={t('状态', 'State')} value={stateLabel(item.state || 'current', t)} />
        <DetailRow label={t('更新时间', 'Updated')} value={formatTime(item.updated_at)} />
      </dl>
      {Array.isArray(item.related) && item.related.length > 0 && (
        <div className="mt-7">
          <div className="mb-2 text-xs font-semibold text-text-muted">{t('相关概念', 'Related concepts')}</div>
          <div className="flex flex-wrap gap-x-3 gap-y-2 text-xs text-text-normal">
            {item.related.map((value) => <span key={value}>#{value}</span>)}
          </div>
        </div>
      )}
      {item.action_required && (
        <button type="button" onClick={onOpenReview} className="mt-8 border-b border-amber-500 pb-1 text-sm font-medium text-amber-700 hover:text-amber-800">
          {t('前往确认', 'Review cognition')}
        </button>
      )}
    </aside>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-right font-medium text-text-strong">{value}</dd>
    </div>
  )
}

function cognitionPosition(id: string, index: number) {
  const hash = Array.from(id).reduce((value, char) => ((value * 31) + char.charCodeAt(0)) >>> 0, 7)
  const column = index % 4
  const row = Math.floor(index / 4)
  return {
    left: 6 + column * 23 + (hash % 5),
    top: 12 + row * 27 + ((hash >>> 3) % 7),
    delay: -((hash % 12) + index),
    duration: 18 + (hash % 9),
  }
}

function stateTextColor(state: string) {
  if (state === 'uncertain') return 'text-amber-700/75'
  if (state === 'historical') return 'text-text-muted/45'
  if (state === 'evolving') return 'text-[#526963]/70'
  return 'text-[#34413e]/75'
}

function stateDotColor(state: string) {
  if (state === 'uncertain') return 'bg-amber-500'
  if (state === 'historical') return 'bg-gray-400'
  if (state === 'evolving') return 'bg-[#6f8c85]'
  return 'bg-[#2f5f58]'
}

function stateLabel(state: string, t: (zh: string, en: string) => string) {
  if (state === 'uncertain') return t('待确认', 'Uncertain')
  if (state === 'historical') return t('历史认知', 'Historical')
  if (state === 'evolving') return t('演化中', 'Evolving')
  return t('当前认知', 'Current')
}

function domainLabel(domain: string, t: (zh: string, en: string) => string) {
  if (domain === 'self') return t('自我', 'Self')
  if (domain === 'user') return t('用户', 'User')
  if (domain === 'projects') return t('项目', 'Projects')
  if (domain === 'active') return t('当前状态', 'Active')
  return t('世界', 'World')
}

function formatTime(value: unknown) {
  if (!value) return '-'
  const numeric = Number(value)
  if (Number.isFinite(numeric)) return new Date(numeric * (numeric < 10000000000 ? 1000 : 1)).toLocaleString()
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}
