import { useRef, useState } from 'react'
import { applyPersonalTemplate, exportPersonalWorkspaceArchive, getPersonalTemplates, restorePersonalWorkspaceArchive } from '../../../services/api'
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
    const response = await exportPersonalWorkspaceArchive()
    if (!response.ok) throw new Error(`workspace export failed: ${response.status}`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `promethea-workspace-${new Date().toISOString().replace(/[:.]/g, '-')}.promethea-workspace`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    setResult({ status: 'exported', format: 'promethea-workspace.v2' })
  }

  const uploadBundle = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    const response = await restorePersonalWorkspaceArchive(file, false)
    setResult(await response.json())
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
      <input ref={fileRef} type="file" accept=".promethea-workspace,application/vnd.promethea.workspace+zip,application/zip" className="text-sm" />
      <button type="button" onClick={uploadBundle} className="self-start rounded-lg bg-brand-50 px-3 py-1.5 text-sm text-brand-600">{t('恢复个人工作区', 'Restore Workspace')}</button>
      <ResultCard payload={result} />
    </section>
  )
}
