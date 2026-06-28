import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { deleteCurrentUserAccount, getConfig, getRuntimeSecrets, updateConfig, updateRuntimeSecrets } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import { useAuth } from '../../store/AuthContext'
import EnterpriseBrainPanel from './settings/EnterpriseBrainPanel'
import PersonalWorkspacePanel from './settings/PersonalWorkspacePanel'
import PluginCapabilitiesPanel from './settings/PluginCapabilitiesPanel'
import SoulReadOnlyPanel from './settings/SoulReadOnlyPanel'
import AvatarSettingsPanel from '../avatar/AvatarSettingsPanel'

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [config, setConfig] = useState<any>({})
  const [loading, setLoading] = useState(true)
  const [saveNotice, setSaveNotice] = useState('')
  const [secrets, setSecrets] = useState<any>({})
  const [secretDraft, setSecretDraft] = useState<Record<string, string>>({})
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [accountBusy, setAccountBusy] = useState(false)
  const { t } = useLanguage()
  const { user, logout } = useAuth()
  const orgBrainEnabled = Boolean(config?.org_brain?.enabled)

  useEffect(() => {
    Promise.all([
      getConfig().then((res) => res.json()),
      getRuntimeSecrets().then((res) => res.json()).catch(() => ({})),
    ])
      .then(([configData, secretData]) => {
        setConfig(configData.config || configData)
        setSecrets(secretData.secrets || {})
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await updateConfig(config)
      setSaveNotice(t(
        '设置已保存。企业大脑开关属于运行时模块配置，建议重启后再验证前端入口和后端召回状态。',
        'Settings saved. Enterprise Brain is a runtime module setting; restart before validating UI entrypoints and backend recall state.',
      ))
    } catch {
      alert(t('保存设置失败', 'Failed to save settings'))
    }
  }

  const handleSaveSecrets = async () => {
    try {
      const res = await updateRuntimeSecrets(secretDraft)
      const data = await res.json().catch(() => ({}))
      setSecrets(data.secrets || secrets)
      setSecretDraft({})
      setSaveNotice(t(
        '敏感配置已保存到当前账号的 secrets.env。',
        'Sensitive settings were saved to this account secrets.env.',
      ))
    } catch {
      alert(t('保存敏感配置失败', 'Failed to save sensitive settings'))
    }
  }

  const handleDeleteAccount = async () => {
    if (!user?.username || deleteConfirm.trim() !== user.username) {
      setSaveNotice(t('请输入当前用户名以确认注销账户。', 'Enter the current username to confirm account deletion.'))
      return
    }
    setAccountBusy(true)
    try {
      const res = await deleteCurrentUserAccount()
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(String(data.detail || data.message || `HTTP ${res.status}`))
      }
      await logout()
      onClose()
    } catch (error) {
      setSaveNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setAccountBusy(false)
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
              <h3 className="font-semibold text-text-strong">{t('账户', 'Account')}</h3>
              <div className="rounded-xl border border-black/5 bg-gray-50/70 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-text-strong">{user?.username || t('未登录', 'Not signed in')}</div>
                    <div className="mt-1 text-xs text-text-muted">
                      {user?.user_id ? `${t('用户 ID', 'User ID')}: ${user.user_id}` : t('登录后可管理个人配置、记忆、文件和会话。', 'Sign in to manage personal config, memory, files, and sessions.')}
                    </div>
                  </div>
                  {user && (
                    <button
                      type="button"
                      onClick={logout}
                      disabled={accountBusy}
                      className="rounded-lg border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-text-normal hover:bg-gray-100 disabled:opacity-50"
                    >
                      {t('登出', 'Sign out')}
                    </button>
                  )}
                </div>
              </div>

              {user && (
                <details className="rounded-xl border border-red-100 bg-red-50/55 p-4">
                  <summary className="cursor-pointer text-sm font-semibold text-red-700">{t('危险区：注销账户', 'Danger zone: delete account')}</summary>
                  <div className="mt-3 flex flex-col gap-3">
                    <p className="text-xs leading-relaxed text-red-700">
                      {t(
                        '注销会删除当前账户，并尽力清理该账户的会话缓存。这个操作不可恢复。请输入当前用户名确认。',
                        'Deleting the account removes the current account and best-effort clears its session cache. This cannot be undone. Enter the current username to confirm.',
                      )}
                    </p>
                    <input
                      type="text"
                      value={deleteConfirm}
                      onChange={(e) => setDeleteConfirm(e.target.value)}
                      placeholder={user.username}
                      className="w-full rounded-lg border border-red-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-red-100"
                    />
                    <button
                      type="button"
                      onClick={handleDeleteAccount}
                      disabled={accountBusy || deleteConfirm.trim() !== user.username}
                      className="self-end rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {accountBusy ? t('处理中...', 'Processing...') : t('注销账户', 'Delete account')}
                    </button>
                  </div>
                </details>
              )}
            </section>

            <section className="flex flex-col gap-4">
              <h3 className="font-semibold text-text-strong">{t('快速配置', 'Quick Setup')}</h3>
              <Field label={t('温度', 'Temperature')}>
                <input
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={config?.api?.temperature ?? 0.7}
                  onChange={(e) => setConfig({ ...config, api: { ...config.api, temperature: Number(e.target.value) } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
              <Field label={t('最大输出 tokens', 'Max Tokens')}>
                <input
                  type="number"
                  min="1"
                  value={config?.api?.max_tokens ?? 2000}
                  onChange={(e) => setConfig({ ...config, api: { ...config.api, max_tokens: Number(e.target.value) } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
            </section>

            <section className="flex flex-col gap-4 mt-4 pt-4 border-t border-black/5">
              <h3 className="font-semibold text-text-strong">{t('敏感运行配置', 'Sensitive Runtime Settings')}</h3>
              <p className="text-xs leading-relaxed text-text-muted">
                {t(
                  'API Key、模型、供应商 URL、记忆后端和 Neo4j 账号密码都保存在当前账号的 secrets.env，不进入普通 config。已有值不会回显；留空表示不修改。',
                  'API keys, model routing, provider URL, memory backend, and Neo4j credentials are stored in this account secrets.env, not normal config. Existing values are not shown; leave blank to keep them unchanged.',
                )}
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
                <StatusPill label="API Key" active={Boolean(secrets?.api?.api_key_configured)} />
                <StatusPill label="Base URL" active={Boolean(secrets?.api?.base_url_configured)} />
                <StatusPill label="Model" active={Boolean(secrets?.api?.model_configured)} />
                <StatusPill label="Search" active={Boolean(secrets?.search?.brave_configured || secrets?.search?.tavily_configured || secrets?.search?.serpapi_configured || secrets?.search?.searxng_configured || secrets?.search?.provider === 'duckduckgo')} />
                <StatusPill label="Neo4j Password" active={Boolean(secrets?.memory?.neo4j_password_configured)} />
              </div>
              <Field label="API__API_KEY">
                <input type="password" value={secretDraft.API__API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__API_KEY: e.target.value })} placeholder={t('留空则不修改', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <Field label="API__BASE_URL">
                <input type="text" value={secretDraft.API__BASE_URL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__BASE_URL: e.target.value })} placeholder={secrets?.api?.base_url || 'https://api.openai.com/v1'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <Field label="API__MODEL">
                <input type="text" value={secretDraft.API__MODEL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__MODEL: e.target.value })} placeholder={secrets?.api?.model || 'gpt-4.1-mini'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <details className="rounded-xl border border-black/5 bg-gray-50/60 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-text-strong">{t('Web Search Provider', 'Web Search Provider')}</summary>
                <div className="mt-3 flex flex-col gap-3">
                  <p className="text-xs leading-relaxed text-text-muted">
                    {t('Configure the provider behind web.search. Auto uses the first configured provider and falls back to DuckDuckGo.', 'Configure the provider behind web.search. Auto uses the first configured provider and falls back to DuckDuckGo.')}
                  </p>
                  <Field label="SEARCH__PROVIDER">
                    <select value={secretDraft.SEARCH__PROVIDER || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__PROVIDER: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                      <option value="">{`${t('Keep unchanged', 'Keep unchanged')} (${secrets?.search?.provider || 'auto'})`}</option>
                      <option value="auto">auto</option>
                      <option value="brave">brave</option>
                      <option value="tavily">tavily</option>
                      <option value="serpapi">serpapi</option>
                      <option value="searxng">searxng</option>
                      <option value="duckduckgo">duckduckgo</option>
                    </select>
                  </Field>
                  <Field label="SEARCH__BRAVE_API_KEY">
                    <input type="password" value={secretDraft.SEARCH__BRAVE_API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__BRAVE_API_KEY: e.target.value })} placeholder={t('Leave blank to keep unchanged', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="SEARCH__TAVILY_API_KEY">
                    <input type="password" value={secretDraft.SEARCH__TAVILY_API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__TAVILY_API_KEY: e.target.value })} placeholder={t('Leave blank to keep unchanged', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="SEARCH__SERPAPI_API_KEY">
                    <input type="password" value={secretDraft.SEARCH__SERPAPI_API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__SERPAPI_API_KEY: e.target.value })} placeholder={t('Leave blank to keep unchanged', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="SEARCH__SEARXNG_URL">
                    <input type="text" value={secretDraft.SEARCH__SEARXNG_URL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__SEARXNG_URL: e.target.value })} placeholder={secrets?.search?.searxng_url || 'http://127.0.0.1:8888'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                </div>
              </details>
              <details className="rounded-xl border border-black/5 bg-gray-50/60 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-text-strong">{t('高级敏感配置', 'Advanced Sensitive Settings')}</summary>
                <div className="mt-3 flex flex-col gap-3">
                  <Field label="MEMORY__STORE_BACKEND">
                    <select value={secretDraft.MEMORY__STORE_BACKEND || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__STORE_BACKEND: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                      <option value="">{t('不修改', 'Keep unchanged')}</option>
                      <option value="neo4j">neo4j</option>
                      <option value="sqlite_graph">sqlite_graph</option>
                      <option value="flat_memory">flat_memory</option>
                    </select>
                  </Field>
                  <Field label="MEMORY__API__USE_MAIN_API">
                    <select value={secretDraft.MEMORY__API__USE_MAIN_API || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__API__USE_MAIN_API: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                      <option value="">{t('不修改', 'Keep unchanged')}</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </Field>
                  <Field label="MEMORY__NEO4J__ENABLED">
                    <select value={secretDraft.MEMORY__NEO4J__ENABLED || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__NEO4J__ENABLED: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                      <option value="">{t('不修改', 'Keep unchanged')}</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </Field>
                  <Field label="MEMORY__NEO4J__URI">
                    <input type="text" value={secretDraft.MEMORY__NEO4J__URI || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__NEO4J__URI: e.target.value })} placeholder="bolt://127.0.0.1:7687" className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="MEMORY__NEO4J__USERNAME">
                    <input type="text" value={secretDraft.MEMORY__NEO4J__USERNAME || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__NEO4J__USERNAME: e.target.value })} placeholder="neo4j" className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="MEMORY__NEO4J__PASSWORD">
                    <input type="password" value={secretDraft.MEMORY__NEO4J__PASSWORD || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MEMORY__NEO4J__PASSWORD: e.target.value })} placeholder={t('留空则不修改', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                </div>
              </details>
              <button type="button" onClick={handleSaveSecrets} className="self-end px-4 py-2 text-sm font-medium text-white bg-slate-800 hover:bg-slate-900 rounded-lg transition-colors">{t('保存敏感配置', 'Save Sensitive Settings')}</button>
            </section>

            <section className="flex flex-col gap-4 mt-4 pt-4 border-t border-black/5">
              <h3 className="font-semibold text-text-strong">{t('个性化', 'Personalization')}</h3>
              <AvatarSettingsPanel />
              <Field label={t('Agent 名称', 'Agent Name')}>
                <input
                  type="text"
                  value={config?.user?.agent_name || ''}
                  onChange={(e) => setConfig({ ...config, user: { ...config.user, agent_name: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
              <Field label={t('自定义表现', 'Custom Presentation')}>
                <textarea
                  rows={4}
                  value={config?.user?.system_prompt || ''}
                  onChange={(e) => setConfig({ ...config, user: { ...config.user, system_prompt: e.target.value } })}
                  placeholder={t(
                    '可选。用于长期调整称呼、语气和互动偏好；不会覆盖 Promethea 的核心身份。',
                    'Optional. Adjusts long-term address, tone, and interaction preferences; it does not override Promethea core identity.',
                  )}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 resize-none"
                />
              </Field>
            </section>

            <section className="flex flex-col gap-4 mt-4 pt-4 border-t border-black/5">
              <h3 className="font-semibold text-text-strong">{t('企业配置', 'Enterprise Config')}</h3>
              <label className="flex items-start gap-3 rounded-xl border border-black/5 bg-gray-50/70 p-3">
                <input
                  type="checkbox"
                  checked={orgBrainEnabled}
                  onChange={(e) => setConfig({ ...config, org_brain: { ...config.org_brain, enabled: e.target.checked } })}
                  className="mt-1"
                />
                <span className="flex flex-col gap-1">
                  <span className="text-sm font-semibold text-text-strong">{t('开启企业大脑', 'Enable Enterprise Brain')}</span>
                  <span className="text-xs text-text-muted">
                    {t(
                      '关闭后前端不展示企业知识入口；保存后请重启服务，让后端模块和提示词注入状态完全一致。',
                      'When disabled, enterprise knowledge entrypoints are hidden; restart after saving so backend modules and prompt injection state are consistent.',
                    )}
                  </span>
                </span>
              </label>
              <Field label={t('组织 ID', 'Organization ID')}>
                <input
                  type="text"
                  value={config?.org_brain?.org_id || ''}
                  disabled={!orgBrainEnabled}
                  onChange={(e) => setConfig({ ...config, org_brain: { ...config.org_brain, org_id: e.target.value } })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-gray-100 disabled:text-text-muted"
                />
              </Field>
            </section>

            <details className="rounded-xl border border-black/5 bg-white/70 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-text-strong">
                {t('??????', 'Enterprise Brain Details')}
              </summary>
              <div className="mt-3">
                {orgBrainEnabled ? (
                  <EnterpriseBrainPanel orgId={config?.org_brain?.org_id} />
                ) : (
                  <div className="rounded-xl border border-dashed border-black/10 bg-gray-50 p-4 text-sm text-text-muted">
                    {t(
                      '???????????????????????????????????????????',
                      'Enterprise Brain is disabled, so enterprise upload, recall, and graph entrypoints are hidden. Enable, save, and restart the service.',
                    )}
                  </div>
                )}
              </div>
            </details>
            <details className="mt-4 rounded-xl border border-black/5 bg-white/70 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-text-strong">
                {t('高级能力与可见性', 'Advanced Capabilities & Visibility')}
              </summary>
              <p className="mt-2 text-xs text-text-muted">
                {t(
                  '这些能力默认折叠，避免把高阶内部机制变成日常配置负担。',
                  'These controls stay folded to keep advanced internals out of the default setup path.',
                )}
              </p>
              <SoulReadOnlyPanel />
              <PersonalWorkspacePanel />
              <PluginCapabilitiesPanel />
            </details>

            <div className="mt-6 flex justify-end gap-3 shrink-0">
              {saveNotice && <div className="mr-auto max-w-[320px] text-xs leading-relaxed text-amber-700">{saveNotice}</div>}
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-text-normal bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors">{t('取消', 'Cancel')}</button>
              <button type="submit" className="px-4 py-2 text-sm font-medium text-white bg-brand-500 hover:bg-brand-600 rounded-lg shadow-sm transition-colors">{t('保存更改', 'Save Changes')}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-semibold text-text-strong">{label}</span>
      {children}
    </label>
  )
}

function StatusPill({ label, active }: { label: string; active: boolean }) {
  const { t } = useLanguage()
  return (
    <div className={`rounded-lg border px-3 py-2 ${active ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
      <span className="font-semibold">{label}</span>
      <span className="ml-2">{active ? t('已配置', 'configured') : t('缺失', 'missing')}</span>
    </div>
  )
}
