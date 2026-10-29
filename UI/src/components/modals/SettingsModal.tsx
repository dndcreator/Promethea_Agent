import { cloneElement, useEffect, useId, useState } from 'react'
import type { FormEvent, ReactElement } from 'react'
import { deleteCurrentUserAccount, getConfig, getRuntimeSecrets, readApiResponse, updateConfig, updateRuntimeSecrets } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import { useAuth } from '../../store/AuthContext'
import EnterpriseBrainPanel from './settings/EnterpriseBrainPanel'
import PersonalWorkspacePanel from './settings/PersonalWorkspacePanel'
import PluginCapabilitiesPanel from './settings/PluginCapabilitiesPanel'
import PersonalAccountsPanel from './settings/PersonalAccountsPanel'
import ChannelAccountsPanel from './settings/ChannelAccountsPanel'
import SoulReadOnlyPanel from './settings/SoulReadOnlyPanel'
import MemoryEmbeddingPanel from './settings/MemoryEmbeddingPanel'
import AvatarSettingsPanel from '../avatar/AvatarSettingsPanel'
import FeatureSurface from '../FeatureSurface'
import { X } from 'lucide-react'

export default function SettingsModal({ onClose, embedded = false, onWorkspaceRestored }: { onClose: () => void; embedded?: boolean; onWorkspaceRestored?: () => void }) {
  const [config, setConfig] = useState<any>({})
  const [loading, setLoading] = useState(true)
  const [saveNotice, setSaveNotice] = useState('')
  const [saveError, setSaveError] = useState('')
  const [loadError, setLoadError] = useState(false)
  const [secretsError, setSecretsError] = useState(false)
  const [loadRevision, setLoadRevision] = useState(0)
  const [saving, setSaving] = useState(false)
  const [secrets, setSecrets] = useState<any>({})
  const [secretDraft, setSecretDraft] = useState<Record<string, string>>({})
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [accountBusy, setAccountBusy] = useState(false)
  const { t } = useLanguage()
  const { user, logout, verifySession } = useAuth()
  const orgBrainEnabled = Boolean(config?.org_brain?.enabled)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setLoadError(false)
    Promise.allSettled([
      getConfig(controller.signal).then(readApiResponse),
      getRuntimeSecrets(controller.signal).then(readApiResponse),
    ])
      .then(([configData, secretData]) => {
        if (controller.signal.aborted) return
        if (configData.status === 'fulfilled' && configData.value && typeof configData.value === 'object') setConfig(configData.value.config || configData.value)
        else setLoadError(true)
        if (secretData.status === 'fulfilled') { setSecrets(secretData.value?.secrets || {}); setSecretsError(false) }
        else setSecretsError(true)
        setLoading(false)
      })
    return () => controller.abort()
  }, [loadRevision])

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    if (saving || loadError || loading) return
    setSaving(true); setSaveError(''); setSaveNotice('')
    try {
      const result = await updateConfig(config).then(readApiResponse)
      await verifySession()
      setSaveNotice(result?.hot_apply?.requested && !result.hot_apply.success
        ? t('设置已保存，运行时重载未完成。', 'Settings saved; runtime reload did not complete.')
        : t('设置已保存。', 'Settings saved.'))
    } catch {
      setSaveError(t('保存设置失败', 'Failed to save settings'))
    } finally { setSaving(false) }
  }

  const handleSaveSecrets = async () => {
    if (saving || secretsError) return
    setSaving(true); setSaveError(''); setSaveNotice('')
    try {
      const res = await updateRuntimeSecrets(secretDraft)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.error_detail?.message || data.detail || `HTTP ${res.status}`)
      setSecrets(data.secrets || secrets)
      setSecretDraft({})
      setSaveNotice(t('敏感配置已保存。', 'Sensitive settings saved.'))
    } catch {
      setSaveError(t('保存敏感配置失败', 'Failed to save sensitive settings'))
    } finally { setSaving(false) }
  }

  const handleDeleteAccount = async () => {
    if (!user?.username || deleteConfirm.trim() !== user.username) {
      setSaveNotice(t('请输入当前用户名以确认注销账户。', 'Enter the current username to confirm account deletion.'))
      return
    }
    setAccountBusy(true); setSaveError(''); setSaveNotice('')
    try {
      const res = await deleteCurrentUserAccount()
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(String(data.detail || data.message || `HTTP ${res.status}`))
      }
      await logout()
      onClose()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error))
    } finally {
      setAccountBusy(false)
    }
  }

  const handleDisconnect = async (keys: string[]) => {
    if (saving || !window.confirm(t('移除此账号的本地连接配置？', 'Remove this account\'s local connection settings?'))) return
    setSaving(true); setSaveError(''); setSaveNotice('')
    try {
      const data = await updateRuntimeSecrets({}, keys).then(readApiResponse)
      setSecrets(data.secrets || {})
      setSecretDraft((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !keys.includes(key))))
      setSaveNotice(t('账号配置已移除', 'Account settings removed'))
    } catch { setSaveError(t('移除账号配置失败', 'Could not remove account settings')) }
    finally { setSaving(false) }
  }

  const handleWorkspaceRestored = async () => {
    onWorkspaceRestored?.()
    setSaving(true)
    try {
      const data = await getConfig().then(readApiResponse)
      setConfig(data.config || data)
    } catch { setLoadError(true) }
    finally { setSaving(false) }
  }

  return (
    <FeatureSurface embedded={embedded} onClose={onClose} label={t('设置', 'Settings')} size="compact">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50 shrink-0">
          <h2 className="text-lg font-bold text-text-strong">{t('设置', 'Settings')}</h2>
          <button type="button" onClick={onClose} className="icon-button" title={t('关闭', 'Close')} aria-label={t('关闭', 'Close')}><X size={17} /></button>
        </div>

        {saveError && <div role="alert" className="page-error">{saveError}</div>}
        {saveNotice && <div role="status" className="operation-notice">{saveNotice}</div>}
        {loading ? (
          <div className="p-10 text-center text-text-muted">{t('正在加载配置...', 'Loading configuration...')}</div>
        ) : loadError ? <div role="alert" className="page-error"><span>{t('设置加载失败', 'Could not load settings')}</span><button type="button" onClick={() => setLoadRevision((value) => value + 1)}>{t('重试', 'Retry')}</button></div> : (
          <form onSubmit={handleSave} className="settings-form flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-6">
            <section className="flex flex-col gap-4">
              <h3 className="font-semibold text-text-strong">{t('账户', 'Account')}</h3>
              <div className="rounded-xl border border-black/5 bg-gray-50/70 p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-text-strong">{user?.username || t('未登录', 'Not signed in')}</div>
                    <div className="mt-1 text-xs text-text-muted">
                      {user?.user_id ? `${t('用户 ID', 'User ID')}: ${user.user_id}` : t('未登录', 'Not signed in')}
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
              {secretsError && <div role="alert" className="page-error"><span>{t('敏感配置加载失败', 'Could not load sensitive settings')}</span><button type="button" onClick={async () => {
                try { const data = await getRuntimeSecrets().then(readApiResponse); setSecrets(data.secrets || {}); setSecretsError(false) } catch { setSecretsError(true) }
              }}>{t('重试', 'Retry')}</button></div>}
              <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
                <StatusPill label="API Key" active={secretsError ? undefined : secrets?.api?.api_key_configured} />
                <StatusPill label={t('接口地址', 'Base URL')} active={secretsError ? undefined : secrets?.api?.base_url_configured} />
                <StatusPill label={t('模型', 'Model')} active={secretsError ? undefined : secrets?.api?.model_configured} />
                <div className="rounded-lg border border-black/10 px-3 py-2 text-text-muted">{t('搜索来源', 'Search provider')} · {secretsError ? '-' : secrets?.search?.provider || 'auto'}</div>
                <StatusPill label={t('Neo4j 密码', 'Neo4j password')} active={secretsError ? undefined : secrets?.memory?.neo4j_password_configured} />
              </div>
              <Field label="API Key">
                <input type="password" value={secretDraft.API__API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__API_KEY: e.target.value })} placeholder={t('留空则不修改', 'Leave blank to keep unchanged')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <Field label={t('接口地址', 'Base URL')}>
                <input type="text" value={secretDraft.API__BASE_URL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__BASE_URL: e.target.value })} placeholder={secrets?.api?.base_url || 'https://api.openai.com/v1'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <Field label={t('主模型', 'Main model')}>
                <input type="text" value={secretDraft.API__MODEL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, API__MODEL: e.target.value })} placeholder={secrets?.api?.model || 'gpt-4.1-mini'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
              </Field>
              <details className="rounded-xl border border-black/5 bg-gray-50/60 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-text-strong">{t('多模态模型', 'Multimodal Model')}</summary>
                <div className="mt-3 flex flex-col gap-3">
                  <StatusPill label={t('独立多模态模型', 'Dedicated multimodal model')} active={secretsError ? undefined : secrets?.multimodal?.configured} />
                  <Field label="MULTIMODAL__MODEL">
                    <input type="text" value={secretDraft.MULTIMODAL__MODEL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MULTIMODAL__MODEL: e.target.value })} placeholder={secrets?.multimodal?.model || 'gpt-4.1-mini'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="MULTIMODAL__BASE_URL">
                    <input type="text" value={secretDraft.MULTIMODAL__BASE_URL || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MULTIMODAL__BASE_URL: e.target.value })} placeholder={secrets?.multimodal?.base_url || t('留空继承主模型', 'Leave blank to inherit main model')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                  <Field label="MULTIMODAL__API_KEY">
                    <input type="password" value={secretDraft.MULTIMODAL__API_KEY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, MULTIMODAL__API_KEY: e.target.value })} placeholder={t('留空继承主模型', 'Leave blank to inherit main model')} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
                  </Field>
                </div>
              </details>
              <details className="rounded-xl border border-black/5 bg-gray-50/60 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-text-strong">{t('Web Search Provider', 'Web Search Provider')}</summary>
                <div className="mt-3 flex flex-col gap-3">
                  <Field label="SEARCH__PROVIDER">
                    <select value={secretDraft.SEARCH__PROVIDER || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__PROVIDER: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                    <option value="">{`${t('保持不变', 'Keep unchanged')} (${secrets?.search?.provider || 'auto'})`}</option>
                      <option value="auto">auto</option>
                      <option value="brave">brave</option>
                      <option value="tavily">tavily</option>
                      <option value="serpapi">serpapi</option>
                      <option value="searxng">searxng</option>
                      <option value="duckduckgo">duckduckgo</option>
                    </select>
                  </Field>
                  <Field label="SEARCH__FALLBACK_POLICY">
                    <select value={secretDraft.SEARCH__FALLBACK_POLICY || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__FALLBACK_POLICY: e.target.value })} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100">
                      <option value="">{`${t('保持不变', 'Keep unchanged')} (${secrets?.search?.fallback_policy || 'fallback'})`}</option>
                      <option value="fallback">fallback</option>
                      <option value="strict">strict</option>
                    </select>
                  </Field>
                  <Field label="SEARCH__PROVIDER_ORDER">
                    <input type="text" value={secretDraft.SEARCH__PROVIDER_ORDER || ''} onChange={(e) => setSecretDraft({ ...secretDraft, SEARCH__PROVIDER_ORDER: e.target.value })} placeholder={secrets?.search?.provider_order || 'brave,tavily,serpapi,searxng,duckduckgo'} className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100" />
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
              <PersonalAccountsPanel status={secrets?.personal_accounts} draft={secretDraft} busy={saving || secretsError} onChange={(key, value) => setSecretDraft((current) => ({ ...current, [key]: value }))} onDisconnect={(keys) => void handleDisconnect(keys)} />
              <button type="button" disabled={saving || secretsError} onClick={handleSaveSecrets} className="self-end px-4 py-2 text-sm font-medium text-white bg-slate-800 hover:bg-slate-900 rounded-lg transition-colors">{t('保存敏感配置', 'Save Sensitive Settings')}</button>
            </section>

            <ChannelAccountsPanel />

            <section className="flex flex-col gap-4 mt-4 pt-4 border-t border-black/5">
              <h3 className="font-semibold text-text-strong">{t('个性化', 'Personalization')}</h3>
              <AvatarSettingsPanel />
              <Field label={t('Agent 名称', 'Agent Name')}>
                <input
                  type="text"
                  value={config?.agent_name || ''}
                  onChange={(e) => setConfig({ ...config, agent_name: e.target.value })}
                  className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100"
                />
              </Field>
              <Field label={t('自定义表现', 'Custom Presentation')}>
                <textarea
                  rows={4}
                  value={config?.system_prompt || ''}
                  onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })}
                  placeholder={t('称呼、语气和互动偏好（可选）', 'Address, tone, and interaction preferences (optional)')}
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
              <Field label={t('个人记忆协作', 'Personal Memory Collaboration')}>
                <select
                  value={config?.org_brain?.personal_memory_collaboration || 'context_only'}
                  disabled={!orgBrainEnabled}
                  onChange={(e) => setConfig({ ...config, org_brain: { ...config.org_brain, personal_memory_collaboration: e.target.value } })}
                  className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm disabled:bg-gray-100 disabled:text-text-muted"
                >
                  <option value="context_only">{t('仅上下文协作', 'Context only')}</option>
                  <option value="off">{t('隔离', 'Isolated')}</option>
                </select>
              </Field>
            </section>

            <MemoryEmbeddingPanel value={config?.memory?.embedding || {}} endpoint={secrets?.memory?.embedding_base_url || config?.memory?.embedding?.base_url || ''} onChange={(embedding) => setConfig({ ...config, memory: { ...config.memory, embedding } })} />
            <details className="rounded-xl border border-black/5 bg-white/70 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-text-strong">
                {t('企业大脑', 'Enterprise Brain')}
              </summary>
              <div className="mt-3">
                {orgBrainEnabled ? (
                  <EnterpriseBrainPanel orgId={config?.org_brain?.org_id} />
                ) : (
                  <div className="rounded-xl border border-dashed border-black/10 bg-gray-50 p-4 text-sm text-text-muted">
                    {t(
                      '企业大脑未开启。',
                      'Enterprise Brain is disabled.',
                    )}
                  </div>
                )}
              </div>
            </details>
            <details className="mt-4 rounded-xl border border-black/5 bg-white/70 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-text-strong">
                {t('高级能力与可见性', 'Advanced Capabilities & Visibility')}
              </summary>
              <div className="my-4 space-y-3 border-b border-black/5 pb-4">
                <label className="flex items-center gap-2 text-sm text-text-strong">
                  <input type="checkbox" checked={Boolean(config?.self_evolve?.enabled)} onChange={(event) => setConfig({ ...config, self_evolve: { ...config.self_evolve, enabled: event.target.checked } })} />
                  {t('应用与工具创作', 'Application and tool authoring')}
                </label>
                <Field label={t('画布验证浏览器', 'Canvas verification browser')}>
                  <select aria-label={t('画布验证浏览器', 'Canvas verification browser')} value={config?.self_evolve?.browser_channel || ''} onChange={(event) => setConfig({ ...config, self_evolve: { ...config.self_evolve, browser_channel: event.target.value } })} className="rounded-lg border border-black/10 bg-white px-3 py-2 text-sm">
                    <option value="">{t('自动', 'Automatic')}</option>
                    <option value="msedge">Microsoft Edge</option>
                    <option value="chrome">Google Chrome</option>
                    {config?.self_evolve?.browser_channel && !['msedge', 'chrome'].includes(config.self_evolve.browser_channel) && <option value={config.self_evolve.browser_channel}>{config.self_evolve.browser_channel}</option>}
                  </select>
                </Field>
              </div>
              <SoulReadOnlyPanel />
              <PersonalWorkspacePanel onRestored={handleWorkspaceRestored} />
              <PluginCapabilitiesPanel />
            </details>

            <div className="mt-6 flex justify-end gap-3 shrink-0">
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-text-normal bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors">{t('取消', 'Cancel')}</button>
              <button type="submit" disabled={saving} className="px-4 py-2 text-sm font-medium text-white bg-brand-500 hover:bg-brand-600 rounded-lg shadow-sm transition-colors">{t('保存更改', 'Save Changes')}</button>
            </div>
          </form>
        )}
    </FeatureSurface>
  )
}

function Field({ label, children }: { label: string; children: ReactElement<{ id?: string }> }) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-semibold text-text-strong">{label}</label>
      {cloneElement(children, { id })}
    </div>
  )
}

function StatusPill({ label, active }: { label: string; active?: boolean }) {
  const { t } = useLanguage()
  return (
    <div className={`rounded-lg border px-3 py-2 ${active === undefined ? 'border-black/10 text-text-muted' : active ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
      <span className="font-semibold">{label}</span>
      <span className="ml-2">{active === undefined ? t('未知', 'unknown') : active ? t('已配置', 'configured') : t('缺失', 'missing')}</span>
    </div>
  )
}
