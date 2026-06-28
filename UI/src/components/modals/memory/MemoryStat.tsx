export default function MemoryStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white border rounded p-3">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-xl font-bold text-brand-600">{value}</div>
    </div>
  )
}
