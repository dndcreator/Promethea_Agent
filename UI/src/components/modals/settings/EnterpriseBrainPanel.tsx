import { useRef, useState } from 'react'
import { getOrgBrainStatus, ingestOrgBrainFile } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'
import ResultCard from './ResultCard'

export default function EnterpriseBrainPanel({ orgId }: { orgId?: string }) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [result, setResult] = useState<unknown>(null)
  const { t } = useLanguage()

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('use_llm', 'true')
    if (orgId) form.append('org_id', orgId)
    setResult(await ingestOrgBrainFile(form).then((res) => res.json()))
  }

  return (
    <section className="mt-4 flex flex-col gap-4 border-t border-black/5 pt-4">
      <h3 className="font-semibold text-text-strong">{t('企业大脑', 'Enterprise Brain')}</h3>
      <input ref={fileRef} type="file" accept=".txt,.md,.markdown,.csv,.json,.docx,.pdf" className="text-sm" />
      <div className="flex gap-2">
        <button type="button" onClick={() => getOrgBrainStatus().then((res) => res.json()).then(setResult)} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">
          {t('检查状态', 'Check Status')}
        </button>
        <button type="button" onClick={upload} className="rounded-lg bg-brand-50 px-3 py-1.5 text-sm text-brand-600">
          {t('上传并抽取', 'Upload & Ingest')}
        </button>
      </div>
      <ResultCard payload={result} />
    </section>
  )
}
