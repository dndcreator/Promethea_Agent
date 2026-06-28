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
        <div>
          <h3 className="font-semibold text-text-strong">{t('灵魂风格（只读）', 'Soul Style (Read-only)')}</h3>
          <p className="mt-1 text-xs text-text-muted">
            {t(
              '这是 Promethea 长期互动中自然演化出的元人格，不是用户自定义表现，也不会覆盖核心身份。',
              'This is Promethea’s long-term evolved temperament, separate from user customization and unable to override core identity.',
            )}
          </p>
        </div>
        <button type="button" onClick={load} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('查看', 'View')}</button>
      </div>
      <ResultCard payload={soul} />
    </section>
  )
}
