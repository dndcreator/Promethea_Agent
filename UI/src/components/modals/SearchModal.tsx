import { useState } from 'react'
import { unifiedSearch } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'

type SearchSession = {
  session_id: string
  title?: string
  last_message?: string
  search_hit?: { snippet?: string }
}

type SearchFile = {
  file_id?: string
  filename?: string
  preview?: string
  content_type?: string
}

type SearchResult = {
  results?: {
    sessions?: SearchSession[]
    files?: SearchFile[]
  }
}

export default function SearchModal({ onClose, onSelectSession }: { onClose: () => void; onSelectSession: (id: string) => void }) {
  const { t } = useLanguage()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)

  const runSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      setResult(await unifiedSearch(query.trim()).then((res) => res.json()))
    } finally {
      setLoading(false)
    }
  }

  const sessions = result?.results?.sessions || []
  const files = result?.results?.files || []

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[1000px] h-[76vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('全局搜索', 'Global Search')}</h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>

        <div className="p-4 border-b border-black/5 flex gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && runSearch()}
            placeholder={t('搜索会话和文件...', 'Search sessions and files...')}
            className="flex-1 px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
          />
          <button type="button" onClick={runSearch} disabled={loading || !query.trim()} className="px-4 py-2 bg-brand-500 text-white rounded-lg text-sm font-medium disabled:opacity-50">
            {loading ? t('搜索中...', 'Searching...') : t('搜索', 'Search')}
          </button>
        </div>

        <div className="flex-1 overflow-hidden grid grid-cols-2 bg-bg-page">
          <section className="p-4 overflow-y-auto border-r border-black/5">
            <h3 className="font-semibold text-text-strong mb-3">{t('会话', 'Sessions')} ({sessions.length})</h3>
            <div className="flex flex-col gap-2">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => {
                    onSelectSession(session.session_id)
                    onClose()
                  }}
                  className="p-3 text-left bg-white border border-black/5 rounded-xl hover:border-brand-300"
                >
                  <div className="text-sm font-semibold text-text-strong truncate">{session.title || session.session_id}</div>
                  <div className="text-xs text-text-muted truncate">{session.last_message || session.search_hit?.snippet || session.session_id}</div>
                </button>
              ))}
              {result && sessions.length === 0 && <div className="text-sm text-text-muted">{t('没有匹配会话。', 'No matching sessions.')}</div>}
            </div>
          </section>

          <section className="p-4 overflow-y-auto">
            <h3 className="font-semibold text-text-strong mb-3">{t('文件', 'Files')} ({files.length})</h3>
            <div className="flex flex-col gap-2">
              {files.map((file) => (
                <div key={file.file_id || file.filename} className="p-3 bg-white border border-black/5 rounded-xl">
                  <div className="text-sm font-semibold text-text-strong truncate">{file.filename || file.file_id}</div>
                  <div className="text-xs text-text-muted truncate">{file.preview || file.content_type || 'file'}</div>
                </div>
              ))}
              {result && files.length === 0 && <div className="text-sm text-text-muted">{t('没有匹配文件。', 'No matching files.')}</div>}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
