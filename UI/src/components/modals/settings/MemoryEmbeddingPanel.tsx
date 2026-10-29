import { useEffect, useState } from 'react'
import { Download, RefreshCw, Save } from 'lucide-react'
import { controlMemoryEmbedding, getMemoryEmbedding, readApiResponse, updateConfig, updateRuntimeSecrets, type MemoryEmbeddingStatus } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'

type Settings = { provider?: string; model?: string; revision?: string }

export default function MemoryEmbeddingPanel({ value, onChange, endpoint = '' }: {
  value: Settings; onChange: (settings: Settings) => void; endpoint?: string
}) {
  const { t } = useLanguage()
  const [status, setStatus] = useState<MemoryEmbeddingStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState(endpoint)
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      let state: MemoryEmbeddingStatus | null = null
      try {
        state = await getMemoryEmbedding(controller.signal)
        if (!controller.signal.aborted) setStatus(state)
      } catch {
        if (!controller.signal.aborted) { setStatus(null); setError('status_unavailable') }
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void load(), state?.model_state === 'downloading' || state?.index_state === 'indexing' ? 1500 : 10000)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [revision])

  const perform = async (action?: 'download' | 'reindex') => {
    if (busy) return
    setBusy(true); setError(''); setNotice(false)
    try {
      if (value.provider === 'openai-compatible') {
        const values: Record<string, string> = {}
        if (baseUrl.trim()) values.MEMORY__EMBEDDING__BASE_URL = baseUrl.trim()
        if (apiKey.trim()) values.MEMORY__EMBEDDING__API_KEY = apiKey.trim()
        if (Object.keys(values).length) await updateRuntimeSecrets(values).then(readApiResponse)
      }
      await updateConfig({ memory: { embedding: value } }).then(readApiResponse)
      if (action) setStatus(await controlMemoryEmbedding({ action }))
      else setStatus(await getMemoryEmbedding())
      setApiKey(''); setNotice(true); setRevision((current) => current + 1)
    } catch { setError('operation_failed') }
    finally { setBusy(false) }
  }

  const labels: Record<string, string> = {
    disabled: t('未启用', 'Disabled'), missing_dependencies: t('本地编码依赖未安装', 'Local embedding dependencies missing'),
    missing_model: t('模型未下载', 'Model not downloaded'), downloading: t('正在下载', 'Downloading'),
    ready: t('就绪', 'Ready'), configured: t('已配置', 'Configured'), idle: t('等待建立索引', 'Awaiting indexing'),
    indexing: t('正在建立索引', 'Indexing'), failed: t('增强暂不可用', 'Enhancement unavailable'),
    unsupported: t('当前后端不支持向量索引', 'Vector index unavailable on this backend'),
    embedding_unavailable: t('编码或索引失败', 'Encoding or indexing failed'),
    encoder_busy: t('编码器忙碌', 'Encoder busy'), invalid_provider_url: t('接口地址无效', 'Invalid endpoint'),
    pinned_model_revision_required: t('请填写模型仓库与完整提交版本', 'Enter a model repository and full commit revision'),
    safetensors_required: t('模型缺少安全权重文件', 'Safe tensor weights missing'),
    download_limit_exceeded: t('模型超过下载大小限制', 'Model exceeds download limit'),
    invalid_embedding_response: t('编码结果无效', 'Invalid embedding response'),
    status_unavailable: t('状态获取失败', 'Could not load status'), operation_failed: t('操作失败，请刷新状态后重试', 'Operation failed. Refresh status and retry.'),
  }
  const inputClass = 'w-full min-w-0 rounded-lg border border-black/10 bg-white px-3 py-2 text-sm'
  return <section className="settings-section" aria-label={t('记忆检索', 'Memory retrieval')}>
    <header className="settings-section-heading">
      <h3>{t('记忆检索', 'Memory retrieval')}</h3>
      <button type="button" className="icon-button" title={t('刷新检索状态', 'Refresh retrieval status')} aria-label={t('刷新检索状态', 'Refresh retrieval status')} onClick={() => { setError(''); setRevision((current) => current + 1) }}><RefreshCw size={15} /></button>
    </header>
    <div className="grid grid-cols-1 gap-3">
      <label className="flex flex-col gap-1.5 text-xs font-semibold">{t('语义增强', 'Semantic enhancement')}
        <select aria-label={t('语义增强', 'Semantic enhancement')} className={inputClass} value={value.provider || 'disabled'} disabled={busy} onChange={(event) => { onChange({ ...value, provider: event.target.value }); setNotice(false) }}>
          <option value="disabled">{t('关闭', 'Off')}</option>
          <option value="local">{t('本地模型 · CPU', 'Local model · CPU')}</option>
          <option value="openai-compatible">{t('外部接口 / Ollama', 'External endpoint / Ollama')}</option>
        </select>
      </label>
      {value.provider && value.provider !== 'disabled' && <>
        <label className="flex flex-col gap-1.5 text-xs font-semibold">{t('Embedding 模型', 'Embedding model')}
          <input className={inputClass} value={value.model || ''} disabled={busy} onChange={(event) => onChange({ ...value, model: event.target.value })} />
        </label>
        {value.provider === 'local' ? <details>
          <summary className="cursor-pointer text-xs text-text-muted">{t('模型版本', 'Model revision')}</summary>
          <label className="mt-2 flex flex-col gap-1.5 text-xs font-semibold">{t('提交版本', 'Commit revision')}
            <input className={inputClass} value={value.revision || ''} disabled={busy} onChange={(event) => onChange({ ...value, revision: event.target.value })} />
          </label>
        </details> : <>
          <label className="flex flex-col gap-1.5 text-xs font-semibold">{t('接口地址', 'Endpoint')}<input type="url" className={inputClass} value={baseUrl} disabled={busy} onChange={(event) => setBaseUrl(event.target.value)} /></label>
          <label className="flex flex-col gap-1.5 text-xs font-semibold">API Key<input type="password" autoComplete="off" className={inputClass} value={apiKey} disabled={busy} placeholder={t('留空则不修改', 'Leave blank to keep unchanged')} onChange={(event) => setApiKey(event.target.value)} /></label>
        </>}
      </>}
    </div>
    {status && <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs" aria-live="polite">
      <dt className="text-text-muted">{t('编码器', 'Encoder')}</dt><dd className="break-words">{status.model_state === 'ready' ? t('模型已下载', 'Model downloaded') : labels[status.model_state]}</dd>
      <dt className="text-text-muted">{t('索引', 'Index')}</dt><dd>{labels[status.index_state]} · {status.indexed}/{status.total}</dd>
      <dt className="text-text-muted">{t('基础检索', 'Base retrieval')}</dt><dd>{t('关键词与图关系', 'Keywords and graph relations')}</dd>
    </dl>}
    {status?.index_state === 'indexing' && (status.total || 0) > 0 && <progress className="mt-3 h-1 w-full appearance-none overflow-hidden rounded bg-gray-100 [&::-webkit-progress-bar]:bg-gray-100 [&::-webkit-progress-value]:bg-brand-500 [&::-moz-progress-bar]:bg-brand-500" value={status.indexed} max={status.total} aria-label={t('索引进度', 'Index progress')} />}
    {status?.reason && <div role="status" className="operation-notice">{labels[status.reason] || t('语义增强暂不可用', 'Semantic enhancement unavailable')}</div>}
    {error && <div role="alert" className="page-error">{labels[error]}</div>}
    {notice && <div role="status" className="operation-notice">{t('已保存', 'Saved')}</div>}
    <div className="settings-actions mt-3 flex flex-wrap gap-2">
      <button type="button" className="secondary-button" disabled={busy} onClick={() => void perform()}><Save size={14} />{t('保存检索设置', 'Save retrieval settings')}</button>
      {value.provider === 'local' && <button type="button" className="secondary-button" disabled={busy || !status?.supported || status.model_state === 'downloading' || status.model_state === 'missing_dependencies'} onClick={() => void perform('download')}><Download size={14} />{t('下载模型', 'Download model')}</button>}
      {value.provider && value.provider !== 'disabled' && <button type="button" className="secondary-button" disabled={busy || !status?.supported || status.index_state === 'indexing'} onClick={() => void perform('reindex')}><RefreshCw size={14} />{t('更新索引', 'Update index')}</button>}
    </div>
  </section>
}
