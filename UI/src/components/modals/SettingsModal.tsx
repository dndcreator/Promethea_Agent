import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { getConfig, updateConfig } from '../../lib/api'
import { useLanguage } from '../../store/LanguageContext'

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [config, setConfig] = useState<any>({})
  const [loading, setLoading] = useState(true)
  const { t } = useLanguage()

  useEffect(() => {
    getConfig()
      .then((res) => res.json())
      .then((data) => {
        setConfig(data.config || data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await updateConfig(config)
      onClose()
    } catch {
      alert(t('保存设置失败', 'Failed to save settings'))
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[600px] max-h-[80vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50 shrink-0">
          <h2 className="text-lg font-bold text-text-strong">{t('设置', 'Settings')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>

        {loading ? (
          <div className="p-10 text-center text-text-muted">{t('正在加载配置...', 'Loading configuration...')}</div>
        ) : (
          <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
            <section className="flex flex-col gap-4">
              <h3 className="font-semibold text-text-strong">{t('快速设置', 'Quick Setup')}</h3>
              <Field label={t('模型', 'Model')}>
                <input
                  type="text"
                  value={config?.api?.model || ''}
                  onChange={(e) => setConfig({ ...config, api: { ...config.api, model: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
              <Field label={t('记忆后端', 'Memory Backend')}>
                <select
                  value={config?.memory?.store_backend || 'neo4j'}
                  onChange={(e) => setConfig({ ...config, memory: { ...config.memory, store_backend: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                >
                  <option value="neo4j">Neo4j (Graph)</option>
                  <option value="sqlite_graph">SQLite Graph (Lightweight)</option>
                  <option value="flat_memory">Flat Memory (Fallback)</option>
                </select>
              </Field>
              <Field label="Neo4j URI">
                <input
                  type="text"
                  value={config?.memory?.neo4j?.uri || ''}
                  onChange={(e) => setConfig({ ...config, memory: { ...config.memory, neo4j: { ...config.memory?.neo4j, uri: e.target.value } } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
            </section>

            <section className="flex flex-col gap-4 mt-4 pt-4 border-t border-black/5">
              <h3 className="font-semibold text-text-strong">{t('个性化', 'Personalization')}</h3>
              <Field label={t('Agent 名称', 'Agent Name')}>
                <input
                  type="text"
                  value={config?.user?.agent_name || ''}
                  onChange={(e) => setConfig({ ...config, user: { ...config.user, agent_name: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
              <Field label={t('自定义 System Prompt', 'Custom System Prompt')}>
                <textarea
                  rows={4}
                  value={config?.user?.system_prompt || ''}
                  onChange={(e) => setConfig({ ...config, user: { ...config.user, system_prompt: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 resize-none"
                />
              </Field>
            </section>

            <div className="mt-6 flex justify-end gap-3 shrink-0">
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-text-normal bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors">{t('取消', 'Cancel')}</button>
              <button type="submit" className="px-4 py-2 text-sm font-medium text-white bg-brand-500 hover:bg-brand-600 rounded-lg shadow-sm transition-colors">{t('保存更改', 'Save Changes')}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-semibold text-text-strong">{label}</span>
      {children}
    </label>
  )
}
