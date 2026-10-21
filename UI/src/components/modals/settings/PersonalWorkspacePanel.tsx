import { useRef, useState } from 'react'
import { Download, RefreshCw, Upload } from 'lucide-react'
import { applyPersonalTemplate, exportPersonalWorkspaceArchive, getPersonalTemplates, readApiResponse, restorePersonalWorkspaceArchive } from '../../../services/api'
import { downloadBlob } from '../../../services/downloads'
import { useLanguage } from '../../../store/LanguageContext'

export default function PersonalWorkspacePanel({ onRestored }: { onRestored?: () => void | Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [templates, setTemplates] = useState<any[]>([])
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState<unknown>(null)
  const { t } = useLanguage()

  const perform = async (operation: () => Promise<void>) => {
    if (busy) return
    setBusy(true); setError(''); setNotice(''); setReceipt(null)
    try { await operation() }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const loadTemplates = () => perform(async () => {
    const data = await getPersonalTemplates().then(readApiResponse)
    setTemplates(data.templates || [])
    setLoaded(true)
  })
  const download = () => perform(async () => {
    const response = await exportPersonalWorkspaceArchive()
    if (!response.ok) { await readApiResponse(response); return }
    downloadBlob(await response.blob(), `promethea-workspace-${new Date().toISOString().replace(/[:.]/g, '-')}.promethea-workspace`)
    setNotice(t('工作区已导出', 'Workspace exported'))
  })
  const restore = async () => {
    if (!file || busy || !window.confirm(t('恢复会替换当前用户的工作区数据。继续吗？', 'Restoring replaces the current user\'s workspace data. Continue?'))) return
    await perform(async () => {
      const data = await restorePersonalWorkspaceArchive(file, false).then(readApiResponse)
      setReceipt(data)
      const incomplete = Object.values(data.applied || {}).some((section) => section && typeof section === 'object' && ((section as { ok?: boolean }).ok === false || (section as { success?: boolean }).success === false))
      if (incomplete) setError(t('部分内容未恢复，请查看返回结果', 'Some records were not restored. Review the result.'))
      else setNotice(t('工作区已恢复', 'Workspace restored'))
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      await onRestored?.()
    })
  }
  const apply = (id: string) => perform(async () => {
    const data = await applyPersonalTemplate(id).then(readApiResponse)
    setReceipt(data)
    setNotice(t('模板已应用', 'Template applied'))
  })

  return <section className="settings-section">
    <header className="settings-section-heading"><h3>{t('个人工作区', 'Personal Workspace')}</h3></header>
    <div className="settings-actions">
      <button type="button" disabled={busy} className="secondary-button" onClick={() => void loadTemplates()}><RefreshCw size={14} />{t('加载模板', 'Load templates')}</button>
      <button type="button" disabled={busy} className="secondary-button" onClick={() => void download()}><Download size={14} />{t('导出包', 'Export bundle')}</button>
    </div>
    {templates.map((template) => <button key={template.template_id} type="button" disabled={busy} className="template-row" onClick={() => void apply(template.template_id)}>
      <span>{template.name || template.template_id}</span><small>{template.kind}</small>
    </button>)}
    {loaded && !templates.length && <p className="text-xs text-text-muted">{t('暂无模板', 'No templates')}</p>}
    <div className="settings-actions">
      <label className="secondary-button file-picker"><Upload size={14} />{t('选择恢复包', 'Choose archive')}
        <input ref={fileRef} type="file" className="sr-only" disabled={busy} accept=".promethea-workspace,application/vnd.promethea.workspace+zip,application/zip" onChange={(event) => setFile(event.target.files?.[0] || null)} />
      </label>
      {file && <span className="file-upload-name" title={file.name}>{file.name}</span>}
      <button type="button" disabled={busy || !file} className="secondary-button" onClick={() => void restore()}>{t('恢复个人工作区', 'Restore workspace')}</button>
    </div>
    {notice && <p role="status" className="text-xs text-emerald-700">{notice}</p>}
    {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
    {receipt !== null && <details className="operation-details"><summary>{t('返回结果', 'Result details')}</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details>}
  </section>
}
