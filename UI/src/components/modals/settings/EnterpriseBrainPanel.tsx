import { useCallback, useEffect, useRef, useState } from 'react'
import {
  exportOrgBrain,
  getOrgBrainStatus,
  importOrgBrain,
  ingestOrgBrainFile,
  listOrgBrainDocuments,
  reviewOrgBrainRevision,
  readApiResponse,
} from '../../../services/api'
import { downloadBlob } from '../../../services/downloads'
import { useLanguage } from '../../../store/LanguageContext'

type OrgDocument = {
  document_id: string
  title?: string
  source_name?: string
  revision_id?: string
  revision_status?: string
  current_revision?: number
}

export default function EnterpriseBrainPanel({ orgId }: { orgId?: string }) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const importRef = useRef<HTMLInputElement | null>(null)
  const [status, setStatus] = useState<Record<string, unknown> | null>(null)
  const [documents, setDocuments] = useState<OrgDocument[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const { t } = useLanguage()

  const refresh = useCallback(async () => {
    const statusResponse = await getOrgBrainStatus()
    const statusPayload = await statusResponse.json()
    if (!statusResponse.ok) throw new Error(statusPayload?.detail || 'Status request failed')
    setStatus(statusPayload?.org_brain || null)
    if (statusPayload?.org_brain?.installed === false) {
      setDocuments([])
      return
    }
    const documentsResponse = await listOrgBrainDocuments()
    const documentsPayload = await documentsResponse.json()
    if (!documentsResponse.ok) throw new Error(documentsPayload?.detail || 'Document request failed')
    setDocuments(Array.isArray(documentsPayload?.documents) ? documentsPayload.documents : [])
  }, [])

  useEffect(() => {
    refresh().catch((cause) => setError(String(cause instanceof Error ? cause.message : cause))).finally(() => setLoading(false))
  }, [refresh])

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('use_llm', 'true')
    if (orgId) form.append('org_id', orgId)
    setBusy(true)
    setError('')
    try {
      const response = await ingestOrgBrainFile(form)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload?.detail || 'Upload failed')
      await refresh()
      if (fileRef.current) fileRef.current.value = ''
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause))
    } finally {
      setBusy(false)
    }
  }

  const review = async (revisionId: string, approve: boolean) => {
    setBusy(true)
    setError('')
    try {
      const response = await reviewOrgBrainRevision(revisionId, approve)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload?.detail || 'Review failed')
      await refresh()
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause))
    } finally {
      setBusy(false)
    }
  }

  const downloadBundle = async () => {
    if (busy) return
    setBusy(true); setError('')
    try {
      const payload = await exportOrgBrain().then(readApiResponse)
      downloadBlob(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }), `${orgId || 'organization'}-brain.json`)
    } catch { setError(t('组织知识导出失败', 'Could not export organization knowledge')) }
    finally { setBusy(false) }
  }

  const uploadBundle = async (file?: File) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const bundle = JSON.parse(await file.text())
      const response = await importOrgBrain(bundle)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload?.detail || 'Import failed')
      await refresh()
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause))
    } finally {
      setBusy(false)
      if (importRef.current) importRef.current.value = ''
    }
  }

  return (
    <section className="mt-4 flex flex-col gap-3 border-t border-black/5 pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-text-strong">{t('组织知识', 'Organization Knowledge')}</h3>
        <span className="inline-flex items-center gap-2 text-xs text-text-muted"><span className={`h-2 w-2 rounded-full ${loading || !status ? 'bg-gray-300' : status.ready ? 'bg-emerald-500' : 'bg-amber-400'}`} />{loading ? t('正在加载', 'Loading') : !status ? t('状态未知', 'Status unknown') : status.ready ? t('就绪', 'Ready') : t('未就绪', 'Not ready')}</span>
      </div>
      <input ref={fileRef} type="file" disabled={busy} aria-label={t('选择组织文档', 'Choose organization document')} accept=".txt,.md,.markdown,.csv,.json,.docx,.pdf" className="min-w-0 max-w-full text-sm" />
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={upload} className="rounded-lg bg-brand-50 px-3 py-1.5 text-sm text-brand-600 disabled:opacity-50">{t('上传并抽取', 'Upload & Ingest')}</button>
        <button type="button" disabled={busy} onClick={downloadBundle} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('导出', 'Export')}</button>
        <button type="button" disabled={busy} onClick={() => importRef.current?.click()} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('导入', 'Import')}</button>
        <button type="button" disabled={busy} className="secondary-button" onClick={async () => { setBusy(true); setError(''); try { await refresh() } catch { setError(t('刷新失败', 'Could not refresh organization knowledge')) } finally { setBusy(false) } }}>{t('刷新', 'Refresh')}</button>
        <input ref={importRef} type="file" accept="application/json,.json" className="hidden" onChange={(event) => uploadBundle(event.target.files?.[0])} />
      </div>
      {documents.length > 0 && (
        <div className="divide-y divide-black/5 overflow-hidden rounded-lg border border-black/5">
          {documents.map((item) => (
            <div key={item.document_id} className="flex items-center gap-3 bg-white px-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-text-strong">{item.title || item.source_name || item.document_id}</div>
                <div className="text-xs text-text-muted">v{item.current_revision || 1} · {item.revision_status || 'active'}</div>
              </div>
              {item.revision_status === 'pending' && item.revision_id && (
                <div className="flex gap-1">
                  <button type="button" disabled={busy} onClick={() => review(item.revision_id!, true)} className="rounded-md bg-emerald-50 px-2 py-1 text-xs text-emerald-700 disabled:opacity-50">{t('通过', 'Approve')}</button>
                  <button type="button" disabled={busy} onClick={() => review(item.revision_id!, false)} className="rounded-md bg-red-50 px-2 py-1 text-xs text-red-700 disabled:opacity-50">{t('拒绝', 'Reject')}</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {error && <div role="alert" className="text-xs text-red-600">{error}</div>}
    </section>
  )
}
