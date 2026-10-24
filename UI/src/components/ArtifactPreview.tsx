import { useEffect, useState } from 'react'
import { ArrowLeft, Download, FileText, RefreshCw } from 'lucide-react'
import { getWorkbenchArtifact } from '../services/api'
import type { WorkbenchReference } from '../services/api'
import { useLanguage } from '../store/LanguageContext'
import { useEnvironmentObservation } from '../hooks/useEnvironmentObservation'

export default function ArtifactPreview({ reference, workspaceId, onClose }: { reference: WorkbenchReference; workspaceId: string; onClose: () => void }) {
  const { t } = useLanguage()
  const [preview, setPreview] = useState<{ url: string; type: string; text?: string } | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEnvironmentObservation('artifact', [{ kind: 'artifact', id: reference.target, workspace_id: workspaceId }])
  useEffect(() => {
    const controller = new AbortController()
    let url = ''
    setPreview(null); setError('')
    const load = async () => {
      try {
        const blob = await getWorkbenchArtifact(workspaceId, reference.target, controller.signal)
        const type = blob.type.split(';')[0].toLowerCase()
        const text = type.startsWith('text/') || ['application/json', 'image/svg+xml'].includes(type) ? (await blob.slice(0, 256_000).text()) : undefined
        if (controller.signal.aborted) return
        url = URL.createObjectURL(blob)
        setPreview({ url, type, text })
      } catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause)) }
    }
    void load()
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [workspaceId, reference.target, revision])
  const image = preview && ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif'].includes(preview.type)
  const name = reference.label || reference.target.split(/[\\/]/).pop() || 'artifact'
  return <section className="artifact-preview"><header><button type="button" className="icon-button" onClick={onClose} title={t('返回工作', 'Back to work')} aria-label={t('返回工作', 'Back to work')}><ArrowLeft size={16} /></button><strong>{name}</strong>{preview && <a className="icon-button" href={preview.url} download={name} title={t('下载', 'Download')} aria-label={t('下载', 'Download')}><Download size={16} /></a>}</header>{error ? <div role="alert" className="empty-state"><span>{error}</span><button type="button" className="secondary-button" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={14} />{t('重试', 'Retry')}</button></div> : !preview ? <div className="empty-state">{t('正在加载', 'Loading')}</div> : image ? <div className="artifact-image"><img src={preview.url} alt={name} /></div> : preview.text !== undefined ? <pre className="artifact-text">{preview.text}</pre> : <div className="empty-state"><FileText size={32} /><span>{name}</span><a className="primary-button" href={preview.url} download={name}><Download size={14} />{t('下载文件', 'Download file')}</a></div>}</section>
}
