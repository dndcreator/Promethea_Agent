type ResultCardProps = {
  payload: unknown
  empty?: string
}

export default function ResultCard({ payload, empty = 'No result yet.' }: ResultCardProps) {
  if (!payload) return null
  const data = normalizePayload(payload)

  return (
    <div className="rounded-xl border border-black/5 bg-white p-3 text-xs shadow-sm">
      {data.title && <div className="mb-2 font-semibold text-text-strong">{data.title}</div>}
      {data.description && <p className="mb-3 whitespace-pre-wrap leading-5 text-text-normal">{data.description}</p>}
      {data.rows.length > 0 ? (
        <dl className="grid grid-cols-2 gap-2">
          {data.rows.map((row) => (
            <div key={row.label} className="rounded-lg bg-bg-page px-2.5 py-2">
              <dt className="mb-1 text-text-muted">{row.label}</dt>
              <dd className="break-words font-medium text-text-strong">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="text-text-muted">{empty}</div>
      )}
    </div>
  )
}

function normalizePayload(payload: unknown) {
  if (typeof payload === 'string') return { title: '', description: payload, rows: [] }
  if (!payload || typeof payload !== 'object') return { title: '', description: String(payload ?? ''), rows: [] }

  const record = payload as Record<string, unknown>
  const title = stringValue(record.status || record.result || record.kind || record.name)
  const description = stringValue(record.message || record.summary || record.description || record.error)
  const rows = Object.entries(record)
    .filter(([key]) => !['message', 'summary', 'description', 'error'].includes(key))
    .slice(0, 12)
    .map(([key, value]) => ({ label: humanize(key), value: compact(value) }))

  return { title, description, rows }
}

function compact(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`
  if (typeof value === 'object') return `${Object.keys(value as Record<string, unknown>).length} fields`
  return String(value)
}

function stringValue(value: unknown): string {
  if (!value || typeof value === 'object') return ''
  return String(value)
}

function humanize(key: string) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}
