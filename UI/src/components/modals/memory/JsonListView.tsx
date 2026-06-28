import type { ReactNode } from 'react'

type JsonListViewProps = {
  rows: any[]
  empty: string
  onSelect?: (row: any) => void
}

export default function JsonListView({ rows, empty, onSelect }: JsonListViewProps) {
  if (!rows.length) return <div className="mt-20 text-center text-text-muted">{empty}</div>

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-4">
      {rows.map((row, index) => {
        const summary = summarizeRow(row, index)
        return (
          <button
            key={row.request_id || row.id || row.event_id || index}
            type="button"
            onClick={() => onSelect?.(row)}
            className="rounded-xl border border-black/5 bg-white p-3 text-left text-xs shadow-sm transition-colors hover:border-brand-300"
          >
            <div className="mb-1 flex items-center justify-between gap-3">
              <span className="truncate font-semibold text-text-strong">{summary.title}</span>
              {summary.badge && <span className="shrink-0 rounded-full bg-brand-100 px-2 py-0.5 font-medium text-brand-700">{summary.badge}</span>}
            </div>
            <p className="line-clamp-2 text-[12px] leading-5 text-text-normal">{summary.description}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-text-muted">
              {summary.meta.map((item) => (
                <span key={item.label} className="rounded bg-bg-page px-2 py-1">
                  {item.label}: {item.value}
                </span>
              ))}
            </div>
          </button>
        )
      })}
    </div>
  )
}

function summarizeRow(row: any, index: number): { title: string; description: string; badge?: ReactNode; meta: Array<{ label: string; value: ReactNode }> } {
  const title =
    row.title ||
    row.request_id ||
    row.event_id ||
    row.memory_id ||
    row.id ||
    `Record ${index + 1}`

  const description =
    row.reason ||
    row.summary ||
    row.query ||
    row.input ||
    row.content ||
    row.formatted_context ||
    row.decision ||
    row.status ||
    'No summary available.'

  const badge = row.decision || row.status || row.policy || row.type || row.memory_type
  const meta = [
    { label: 'time', value: formatTime(row.created_at || row.timestamp || row.time) },
    { label: 'session', value: short(row.session_id) },
    { label: 'records', value: Array.isArray(row.memory_records) ? row.memory_records.length : row.records_count ?? row.count ?? '-' },
  ].filter((item) => item.value !== '-' && item.value !== '')

  return { title: String(title), description: String(description), badge, meta }
}

function short(value: unknown) {
  if (!value) return '-'
  const text = String(value)
  return text.length > 12 ? `${text.slice(0, 12)}...` : text
}

function formatTime(value: unknown) {
  if (!value) return '-'
  const numeric = Number(value)
  if (Number.isFinite(numeric)) {
    return new Date(numeric * (numeric < 10000000000 ? 1000 : 1)).toLocaleString()
  }
  return String(value)
}
