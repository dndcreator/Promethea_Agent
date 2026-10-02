import { useState } from 'react'
import { getSoulConfig } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'
import ResultCard from './ResultCard'

export default function SoulReadOnlyPanel() {
  const { t } = useLanguage()
  const [soul, setSoul] = useState<any>(null)

  const load = async () => {
    const data = await getSoulConfig().then((res) => res.json())
    setSoul(data.soul || data)
  }

  return (
    <section className="mt-4 flex flex-col gap-3 border-t border-black/5 pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-text-strong">{t('灵魂风格（只读）', 'Soul Style (Read-only)')}</h3>
        <button type="button" onClick={load} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('查看', 'View')}</button>
      </div>
      <ResultCard payload={soul} />
    </section>
  )
}
