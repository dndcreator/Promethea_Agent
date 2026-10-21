import { useRef, useState } from 'react'
import { RefreshCw, RotateCw } from 'lucide-react'
import { applyPluginConfig, getExtensionCatalog, getPluginCatalog, readApiResponse, reloadExtensions } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'

export default function PluginCapabilitiesPanel() {
  const [plugins, setPlugins] = useState<any[]>([])
  const [extensions, setExtensions] = useState<any[]>([])
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [receipt, setReceipt] = useState<unknown>(null)
  const submitting = useRef(false)
  const { t } = useLanguage()

  const load = async () => {
    const [pluginData, extensionData] = await Promise.allSettled([
      getPluginCatalog().then(readApiResponse), getExtensionCatalog().then(readApiResponse),
    ])
    if (pluginData.status === 'fulfilled') setPlugins(pluginData.value.plugins || [])
    if (extensionData.status === 'fulfilled') setExtensions(extensionData.value.extensions || [])
    setLoaded(true)
    if (pluginData.status === 'rejected' || extensionData.status === 'rejected') setError(t('部分目录加载失败，请重试', 'Some catalogs could not be loaded. Retry.'))
  }
  const perform = async (operation: () => Promise<void>) => {
    if (submitting.current) return
    submitting.current = true
    setBusy(true); setError(''); setNotice(''); setReceipt(null)
    try { await operation() }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { submitting.current = false; setBusy(false) }
  }
  const reload = () => perform(async () => {
    const data = await reloadExtensions().then(readApiResponse)
    setReceipt(data)
    await load()
    setNotice(t('重载请求已完成', 'Reload request completed'))
  })
  const apply = (plugin: any, enabled: boolean) => perform(async () => {
    const data = await applyPluginConfig(plugin.id, enabled, plugin.config || {}).then(readApiResponse)
    setPlugins((rows) => rows.map((row) => row.id === plugin.id ? { ...row, enabled: data.enabled } : row))
    setReceipt(data)
    await load()
  })

  return <section className="settings-section">
    <header className="settings-section-heading">
      <h3>{t('扩展与工具', 'Extensions & Tools')}</h3>
      <div className="settings-actions">
        <button type="button" disabled={busy} onClick={() => void perform(load)} className="icon-button" title={t('刷新', 'Refresh')} aria-label={t('刷新工具目录', 'Refresh tool catalog')}><RefreshCw size={15} className={busy ? 'animate-spin' : ''} /></button>
        <button type="button" disabled={busy} onClick={() => void reload()} className="secondary-button"><RotateCw size={14} />{t('热重载', 'Hot reload')}</button>
      </div>
    </header>
    <div className="extension-list">
      {extensions.map((extension) => <details key={extension.id} className="extension-item">
        <summary><span><strong>{extension.name || extension.id}</strong><small>{extension.provider || ''}</small></span>
          <span>{extension.callable_count ?? '-'} / {extension.tool_count ?? '-'} {t('可调用', 'callable')}</span>
        </summary>
        {extension.description && <p className="extension-description">{extension.description}</p>}
        {(extension.tools || []).map((tool: any) => <div key={tool.tool_id} className="extension-tool">
          <div><strong>{tool.tool_id}</strong><span className={tool.callable_now ? 'text-emerald-700' : 'text-amber-700'}>{tool.callable_now ? t('可调用', 'Callable') : t('不可用', 'Unavailable')}</span></div>
          {tool.description && <p>{tool.description}</p>}
          {!tool.callable_now && tool.callable_reason && <p>{tool.callable_reason}</p>}
        </div>)}
      </details>)}
      {loaded && !extensions.length && !error && <p className="text-xs text-text-muted">{t('暂无扩展', 'No extensions')}</p>}
    </div>
    {!!plugins.length && <div className="plugin-settings-list">
      <h4>{t('配置插件', 'Config plugins')}</h4>
      {plugins.map((plugin) => <label key={plugin.id} className="plugin-setting-row">
        <span>{plugin.name || plugin.id}</span><input type="checkbox" disabled={busy} checked={Boolean(plugin.enabled)} aria-label={t(`启用 ${plugin.name || plugin.id}`, `Enable ${plugin.name || plugin.id}`)} onChange={(event) => void apply(plugin, event.target.checked)} />
      </label>)}
    </div>}
    {notice && <p role="status" className="text-xs text-emerald-700">{notice}</p>}
    {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
    {receipt !== null && <details className="operation-details"><summary>{t('技术详情', 'Technical details')}</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details>}
  </section>
}
