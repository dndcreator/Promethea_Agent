import { useRef, useState } from 'react'
import { applyPersonalTemplate, exportPersonalBundle, getPersonalTemplates, importPersonalBundle } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'
import ResultCard from './ResultCard'

export default function PersonalWorkspacePanel() {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [templates, setTemplates] = useState<any[]>([])
  const [result, setResult] = useState<unknown>(null)
  const { t } = useLanguage()

  const loadTemplates = async () => {
    const data = await getPersonalTemplates().then((res) => res.json())
    setTemplates(data.templates || [])
    setResult({ status: 'loaded', templates: data.templates || [] })
  }

  const downloadBundle = async () => {
    const data = await exportPersonalBundle().then((res) => res.json())
    const bundle = data.bundle || data
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `personal_bundle_${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    setResult({ status: 'exported', bundle_version: bundle.bundle_version })
  }

  const uploadBundle = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setResult(await importPersonalBundle(JSON.parse(await file.text()), true).then((res) => res.json()))
  }

  return (
    <section className="mt-4 flex flex-col gap-4 border-t border-black/5 pt-4">
      <h3 className="font-semibold text-text-strong">{t('个人工作区', 'Personal Workspace')}</h3>
      <div className="flex gap-2">
        <button type="button" onClick={loadTemplates} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('加载模板', 'Load Templates')}</button>
        <button type="button" onClick={downloadBundle} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('导出包', 'Export Bundle')}</button>
      </div>
      {templates.map((template) => (
        <button key={template.template_id} type="button" onClick={() => applyPersonalTemplate(template.template_id).then((res) => res.json()).then(setResult)} className="rounded border bg-white p-2 text-left text-xs hover:border-brand-300">
          {template.kind || 'template'} :: {template.name || template.template_id}
        </button>
      ))}
      <input ref={fileRef} type="file" accept=".json,application/json" className="text-sm" />
      <button type="button" onClick={uploadBundle} className="self-start rounded-lg bg-brand-50 px-3 py-1.5 text-sm text-brand-600">{t('导入包', 'Import Bundle')}</button>
      <ResultCard payload={result} />
    </section>
  )
}
