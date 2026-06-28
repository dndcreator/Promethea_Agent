import { useEffect, useRef, useState } from 'react'
import { listUserFiles, uploadUserFile } from '../../services/api'
import type { ChatAttachment } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'

type FileRecord = {
  file_id?: string
  filename?: string
  path?: string
  content_type?: string
  size?: number
  bytes?: number
  preview?: string
  modality?: string
  text_extraction_status?: string
}

function apiMessage(data: any, fallback: string): string {
  if (!data) return fallback
  const candidates = [data.message, data.detail, data.error]
  for (const candidate of candidates) {
    if (!candidate) continue
    if (typeof candidate === 'string') return candidate
    if (typeof candidate?.message === 'string') return candidate.message
    if (typeof candidate?.detail === 'string') return candidate.detail
  }
  try {
    return JSON.stringify(data)
  } catch {
    return fallback
  }
}

export default function FilesModal({
  sessionId,
  onClose,
  onAttach,
}: {
  sessionId: string | null
  onClose: () => void
  onAttach?: (file: ChatAttachment) => void
}) {
  const { t } = useLanguage()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<FileRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState<'success' | 'error'>('success')

  const load = async (nextQuery = query) => {
    setLoading(true)
    try {
      const res = await listUserFiles(nextQuery)
      const data = await res.json().catch(() => ({}))
      setFiles(Array.isArray(data.files) ? data.files : [])
      if (!res.ok) {
        setMessageTone('error')
        setMessage(apiMessage(data, t('文件列表加载失败。', 'Failed to load files.')))
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load('')
  }, [])

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    if (sessionId) form.append('session_id', sessionId)
    setLoading(true)
    try {
      const res = await uploadUserFile(form)
      const data = await res.json().catch(() => ({}))
      const saved = data.file as FileRecord | undefined
      if (res.ok && data.status === 'success') {
        setMessageTone('success')
        setMessage(t('文件已保存，可被搜索、导出，也可附加到下一次对话。', 'File saved for search/export and can be attached to the next turn.'))
        if (saved?.file_id && onAttach) {
          onAttach({
            file_id: saved.file_id,
            filename: saved.filename,
            modality: saved.modality,
            text_extraction_status: saved.text_extraction_status,
          })
        }
      } else {
        setMessageTone('error')
        setMessage(apiMessage(data, t('文件上传失败。', 'File upload failed.')))
      }
      if (fileRef.current) fileRef.current.value = ''
      await load('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[900px] h-[72vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('文件', 'Files')}</h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>

        <div className="p-4 border-b border-black/5 flex flex-col gap-3">
          <div className="flex gap-2">
            <input ref={fileRef} type="file" accept=".txt,.md,.markdown,.csv,.json,.docx,.pdf,.png,.jpg,.jpeg,.webp,.gif" className="flex-1 text-sm" />
            <button type="button" onClick={upload} disabled={loading} className="px-4 py-2 bg-brand-500 text-white rounded-lg text-sm font-medium disabled:opacity-50">
              {t('上传', 'Upload')}
            </button>
          </div>
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && load(query)}
              placeholder={t('搜索文件名或文本内容...', 'Search file names or extracted text...')}
              className="flex-1 px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
            />
            <button type="button" onClick={() => load(query)} className="px-4 py-2 bg-gray-100 rounded-lg text-sm">
              {t('搜索', 'Search')}
            </button>
          </div>
          {message && (
            <div className={`text-xs rounded-lg px-3 py-2 border ${messageTone === 'error' ? 'text-rose-700 bg-rose-50 border-rose-100' : 'text-green-700 bg-green-50 border-green-100'}`}>
              {message}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 bg-bg-page">
          {files.length === 0 ? (
            <div className="text-sm text-text-muted text-center mt-20">{loading ? t('加载中...', 'Loading...') : t('暂无文件。', 'No files yet.')}</div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {files.map((file) => (
                <div key={file.file_id || file.path || file.filename} className="bg-white border border-black/5 rounded-xl p-4 text-sm shadow-sm">
                  <div className="font-semibold text-text-strong truncate" title={file.filename}>{file.filename || file.file_id}</div>
                  <div className="text-xs text-text-muted mt-1">{file.content_type || file.modality || 'file'} · {formatBytes(file.size || file.bytes || 0)}</div>
                  {file.text_extraction_status && file.text_extraction_status !== 'ok' && (
                    <div className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-700">
                      {t('已保存，但没有可用文本；没有 OCR/视觉模型时不能作为聊天上下文。', 'Stored, but no text is available; without OCR/vision it cannot be used as chat context.')}
                    </div>
                  )}
                  {file.preview && <p className="text-xs text-text-normal mt-3 line-clamp-3">{file.preview}</p>}
                  {file.file_id && onAttach && (
                    <button
                      type="button"
                      onClick={() => onAttach({
                        file_id: file.file_id || '',
                        filename: file.filename,
                        modality: file.modality,
                        text_extraction_status: file.text_extraction_status,
                      })}
                      className="mt-3 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-600 hover:bg-brand-100"
                    >
                      {t('附加到对话', 'Attach to chat')}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function formatBytes(value: number) {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
