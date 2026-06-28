import { useState } from 'react'
import { applyPluginConfig, getExtensionCatalog, getPluginCatalog, reloadExtensions } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'
import ResultCard from './ResultCard'

export default function PluginCapabilitiesPanel() {
  const [plugins, setPlugins] = useState<any[]>([])
  const [extensions, setExtensions] = useState<any[]>([])
  const [result, setResult] = useState<unknown>(null)
  const { t } = useLanguage()

  const load = async () => {
    const [pluginData, extensionData] = await Promise.all([
      getPluginCatalog().then((res) => res.json()).catch(() => ({ plugins: [] })),
      getExtensionCatalog().then((res) => res.json()).catch(() => ({ extensions: [] })),
    ])
    setPlugins(pluginData.plugins || [])
    setExtensions(extensionData.extensions || [])
    setResult({ status: 'loaded', plugins: pluginData.plugins || [], extensions: extensionData.extensions || [] })
  }

  const reload = async () => {
    const data = await reloadExtensions().then((res) => res.json())
    setResult(data)
    await load()
  }

  return (
    <section className="mt-4 flex flex-col gap-4 border-t border-black/5 pt-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-text-strong">{t('扩展与工具', 'Extensions & Tools')}</h3>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">
            {t(
              'Official 和 Community 扩展使用同一张能力表。Community 扩展放入后端 extensions/community 后可热重载。',
              'Official and Community extensions share one capability catalog. Drop Community extensions into backend extensions/community and hot-reload them.',
            )}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button type="button" onClick={load} className="rounded-lg bg-gray-100 px-3 py-1.5 text-sm">{t('刷新', 'Refresh')}</button>
          <button type="button" onClick={reload} className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-white">{t('热重载', 'Hot Reload')}</button>
        </div>
      </div>

      <div className="grid gap-2">
        {extensions.map((extension) => (
          <details key={extension.id} className="rounded-xl border border-black/5 bg-white p-3 text-xs">
            <summary className="cursor-pointer list-none">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-text-strong">{extension.name || extension.id}</span>
                    <span className={`rounded-full px-2 py-0.5 ${extension.provider === 'official' ? 'bg-slate-100 text-slate-700' : 'bg-emerald-50 text-emerald-700'}`}>
                      {extension.provider || 'community'}
                    </span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-text-muted">{extension.source_type || 'unknown'}</span>
                  </div>
                  <p className="mt-1 truncate text-text-muted">{extension.description || extension.id}</p>
                </div>
                <span className="shrink-0 text-text-muted">{extension.callable_count || 0}/{extension.tool_count || 0}</span>
              </div>
            </summary>
            <div className="mt-3 grid gap-2">
              {(extension.tools || []).map((tool: any) => (
                <div key={tool.tool_id} className="rounded-lg bg-gray-50 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-text-strong">{tool.tool_id}</span>
                    <span className={tool.callable_now ? 'text-emerald-700' : 'text-amber-700'}>
                      {tool.callable_now ? t('可调用', 'Callable') : tool.callable_reason || t('不可用', 'Unavailable')}
                    </span>
                  </div>
                  {tool.description && <p className="mt-1 text-text-muted">{tool.description}</p>}
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>

      <div className="flex flex-col gap-2 border-t border-dashed border-black/10 pt-3">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-text-muted">{t('配置插件', 'Config Plugins')}</div>
        {plugins.map((plugin) => (
          <div key={plugin.id} className="flex items-center justify-between gap-3 rounded border bg-white p-3 text-xs">
            <span>{plugin.name || plugin.id} ({plugin.status || 'unknown'})</span>
            <button type="button" onClick={() => applyPluginConfig(plugin.id, !plugin.enabled, plugin.config || {}).then((res) => res.json()).then(setResult)} className="rounded bg-brand-50 px-2 py-1 text-brand-600">
              {plugin.enabled ? t('停用', 'Disable') : t('启用', 'Enable')}
            </button>
          </div>
        ))}
      </div>
      <ResultCard payload={result} />
    </section>
  )
}
