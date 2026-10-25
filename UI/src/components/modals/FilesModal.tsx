import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, File, FileText, Image, Paperclip, RefreshCw, Search, Upload, X } from 'lucide-react'
import { listUserFiles, readApiResponse, uploadUserFile } from '../../services/api'
import type { ChatAttachment } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import FeatureSurface from '../FeatureSurface'
import { useEnvironmentObservation } from '../../hooks/useEnvironmentObservation'

type FileRecord = {
  file_id: string
  filename: string
  bytes?: number
  size?: number
  content_type?: string
  uploaded_at?: number | null
  preview?: string
  snippet?: string
  modality?: string
  text_extraction_status?: string
}
type Props = {
  sessionId: string | null
  onClose: () => void
  onAttach?: (file: ChatAttachment) => void
  embedded?: boolean
  initialQuery?: string
  initialFileId?: string
}

function attachment(file: FileRecord): ChatAttachment {
  return {
    file_id: file.file_id,
    filename: file.filename,
    modality: file.modality,
    content_type: file.content_type,
    size: file.bytes ?? file.size,
    text_extraction_status: file.text_extraction_status,
  }
}

function formatBytes(value?: number): string {
  if (value === undefined) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function FileIcon({ file }: { file: FileRecord }) {
  return file.modality === 'image' ? <Image size={17} /> : file.preview || file.snippet ? <FileText size={17} /> : <File size={17} />
}

export default function FilesModal({ sessionId, onClose, onAttach, embedded = false, initialQuery = '', initialFileId = '' }: Props) {
  const { t, lang } = useLanguage()
  const fileRef = useRef<HTMLInputElement>(null)
  const requestEpoch = useRef(0)
  const lifetime = useRef(0)
  const [query, setQuery] = useState(initialQuery)
  const [files, setFiles] = useState<FileRecord[]>([])
  const [selectedId, setSelectedId] = useState(initialFileId)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selected = files.find((file) => file.file_id === selectedId)
  const observe = useEnvironmentObservation('files', selected ? [{ kind: 'file', id: selected.file_id }] : [])

  const load = async (nextQuery = query) => {
    const epoch = ++requestEpoch.current
    setLoading(true)
    setError('')
    try {
      const data = await listUserFiles(nextQuery).then(readApiResponse<{ files?: FileRecord[] }>)
      if (epoch !== requestEpoch.current) return
      const rows = data.files || []
      setFiles(rows)
      setSelectedId((current) => rows.some((file) => file.file_id === current) ? current : '')
    } catch (cause) {
      if (epoch === requestEpoch.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (epoch === requestEpoch.current) setLoading(false)
    }
  }

  useEffect(() => {
    void load(initialQuery)
    return () => { requestEpoch.current += 1; lifetime.current += 1 }
  }, [])

  const upload = async () => {
    if (!uploadFile || uploading) return
    const epoch = lifetime.current
    setUploading(true)
    setError('')
    setNotice('')
    try {
      const saved = await uploadUserFile(uploadFile, uploadFile.name, sessionId)
      if (epoch !== lifetime.current) return
      setUploadFile(null)
      if (fileRef.current) fileRef.current.value = ''
      if (onAttach) { onAttach(attachment(saved)); return }
      setNotice(t('文件已保存', 'File saved'))
      setQuery('')
      await load('')
    } catch (cause) {
      if (epoch === lifetime.current) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (epoch === lifetime.current) setUploading(false)
    }
  }

  return <FeatureSurface surfaceRef={observe} embedded={embedded} onClose={onClose} label={t('文件', 'Files')}>
    <header className="page-heading">
      <div><FileText size={19} /><h1>{t('文件', 'Files')}</h1><span>{files.length}</span></div>
      <button type="button" className="icon-button" onClick={onClose} aria-label={t('关闭', 'Close')} title={t('关闭', 'Close')}><X size={17} /></button>
    </header>
    <div className="file-toolbar">
      <form className="file-search" onSubmit={(event) => { event.preventDefault(); void load() }}>
        <Search size={15} />
        <input aria-label={t('搜索文件', 'Search files')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('搜索文件', 'Search files')} />
        <button type="submit" className="icon-button" title={t('搜索', 'Search')} aria-label={t('搜索', 'Search')}><Search size={14} /></button>
      </form>
      <button type="button" className="icon-button" onClick={() => void load()} title={t('刷新', 'Refresh')} aria-label={t('刷新', 'Refresh')}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
      <label className="secondary-button file-picker"><Upload size={14} />{t('选择文件', 'Choose file')}
        <input ref={fileRef} type="file" className="sr-only" disabled={uploading}
          accept=".txt,.md,.markdown,.csv,.json,.docx,.pdf,.png,.jpg,.jpeg,.webp,.gif"
          onChange={(event) => setUploadFile(event.target.files?.[0] || null)} />
      </label>
      {uploadFile && <><span className="file-upload-name" title={uploadFile.name}>{uploadFile.name}</span>
        <button type="button" className="primary-button" disabled={uploading} onClick={() => void upload()}><Upload size={14} />
          {uploading ? t('上传中', 'Uploading') : onAttach ? t('上传并附加', 'Upload & attach') : t('上传', 'Upload')}
        </button>
      </>}
    </div>
    {error && <div role="alert" className="page-error"><span>{error}</span></div>}
    {notice && <div role="status" className="operation-notice">{notice}</div>}
    <div className={`file-columns ${selected ? 'has-selection' : ''}`}>
      <div className="file-list">
        {files.map((file) => <button type="button" key={file.file_id} onClick={() => setSelectedId(file.file_id)}
          className={`file-row ${selectedId === file.file_id ? 'is-selected' : ''}`}>
          <FileIcon file={file} /><span><strong>{file.filename}</strong><small>{file.content_type || file.modality || ''} · {formatBytes(file.bytes ?? file.size)}</small></span>
        </button>)}
        {!files.length && !error && <div className="empty-state"><FileText size={24} />
          <span>{loading ? t('正在加载', 'Loading') : query ? t('没有匹配文件', 'No matching files') : t('暂无文件', 'No files')}</span>
        </div>}
      </div>
      <section className="file-detail">
        {selected ? <>
          <div className="file-detail-heading"><button type="button" className="icon-button file-back" title={t('返回文件列表', 'Back to files')} aria-label={t('返回文件列表', 'Back to files')} onClick={() => setSelectedId('')}><ArrowLeft size={16} /></button><FileIcon file={selected} /><h2>{selected.filename}</h2></div>
          <dl className="file-metadata"><div><dt>{t('大小', 'Size')}</dt><dd>{formatBytes(selected.bytes ?? selected.size)}</dd></div>
            <div><dt>{t('类型', 'Type')}</dt><dd>{selected.content_type || '-'}</dd></div>
            {selected.uploaded_at !== undefined && selected.uploaded_at !== null && <div><dt>{t('上传时间', 'Uploaded')}</dt><dd>{new Date(selected.uploaded_at * 1000).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US')}</dd></div>}
          </dl>
          {onAttach && <button type="button" className="primary-button" onClick={() => onAttach(attachment(selected))}><Paperclip size={14} />{t('附加到对话', 'Attach to chat')}</button>}
          <section className="file-text-preview"><h3>{t('文本预览', 'Text preview')}</h3>
            {selected.preview || selected.snippet ? <p>{selected.preview || selected.snippet}</p> : <span>{t('暂无文本预览', 'No text preview')}</span>}
          </section>
        </> : <div className="empty-state"><File size={26} /><span>{t('选择文件', 'Select a file')}</span></div>}
      </section>
    </div>
  </FeatureSurface>
}
