import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { authFetch, getBootstrap } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'

type BootstrapStatus = {
  configured_backend?: string
  auth_backend?: string
  neo4j_available?: boolean
  neo4j_error?: { code?: string; message?: string }
  can_register?: boolean
  reason?: string
  fallback_backends?: string[]
}

type NoticeKind = 'error' | 'success'

function parseErrorDetail(payload: unknown): { code: string; message: string } {
  const detail = (payload as { detail?: unknown })?.detail
  if (typeof detail === 'string') return { code: '', message: detail }
  if (detail && typeof detail === 'object') {
    const record = detail as { code?: unknown; message?: unknown }
    return {
      code: typeof record.code === 'string' ? record.code : '',
      message: typeof record.message === 'string' ? record.message : '',
    }
  }
  return { code: '', message: '' }
}

export default function AuthModal({ onEnterSetup, onClose }: { onEnterSetup?: () => void; onClose?: () => void }) {
  const { login } = useAuth()
  const { t } = useLanguage()
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [agentName, setAgentName] = useState('')
  const [remember, setRemember] = useState(true)
  const [notice, setNotice] = useState('')
  const [noticeKind, setNoticeKind] = useState<NoticeKind>('error')
  const [bootstrap, setBootstrap] = useState<BootstrapStatus | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getBootstrap()
      .then((res) => res.json())
      .then((data) => setBootstrap(data))
      .catch(() => setBootstrap(null))
  }, [])

  const backendLabel = bootstrap?.configured_backend || 'neo4j'
  const neo4jReason = bootstrap?.reason || bootstrap?.neo4j_error?.code || ''
  const registerBlockedByNeo4j = isRegister && (
    neo4jReason === 'neo4j_user_backend_unavailable'
    || neo4jReason === 'neo4j_unavailable'
    || neo4jReason === 'neo4j_authentication_failed'
  )
  const neo4jAuthFailed = neo4jReason === 'neo4j_authentication_failed'

  function getLocalizedFailure(resStatus: number, code: string, message: string): string {
    if (code === 'neo4j_authentication_failed') {
      return t(
        'Neo4j 已启动，但 Neo4j 用户名或密码认证失败。请检查 .env 里的 Neo4j 配置，然后重启 Promethea。',
        'Neo4j is running, but its username or password authentication failed. Check the Neo4j settings in .env, then restart Promethea.',
      )
    }
    if (code === 'neo4j_user_backend_unavailable' || code === 'neo4j_unavailable') {
      return t(
        '当前用户后端是 Neo4j，但无法连接到 Neo4j。请先启动 Neo4j，或切换到 sqlite_graph / flat_memory 后重启再注册。',
        'The current user backend is Neo4j, but Neo4j is unavailable. Start Neo4j first, or switch to sqlite_graph / flat_memory and restart before registering.',
      )
    }
    if (code === 'username_exists_or_system_error') {
      return t('用户名已存在，或注册服务暂时不可用。', 'The username already exists, or the registration service is temporarily unavailable.')
    }
    if (resStatus === 401) {
      return t('用户名或密码错误。', 'Invalid username or password.')
    }
    if (message) return message
    return isRegister
      ? t('注册失败，请检查启动状态和后端配置。', 'Registration failed. Check startup status and backend configuration.')
      : t('登录失败，请检查用户名、密码和后端状态。', 'Sign-in failed. Check username, password, and backend status.')
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setNotice('')
    setNoticeKind('error')
    setLoading(true)

    try {
      const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login'
      const body = isRegister
        ? { username, password, agent_name: agentName || 'Promethea' }
        : { username, password, remember_me: remember }

      const res = await authFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        const { code, message } = parseErrorDetail(errorData)
        throw new Error(getLocalizedFailure(res.status, code, message))
      }

      if (isRegister) {
        setIsRegister(false)
        setNoticeKind('success')
        setNotice(t('注册成功，请登录。', 'Registration successful. Please sign in.'))
      } else {
        const data = await res.json()
        login(
          data.access_token,
          {
            username: data.username,
            user_id: data.user_id,
            agent_name: data.agent_name,
          },
          { remember },
        )
        onClose?.()
      }
    } catch (err: unknown) {
      setNotice(err instanceof Error ? err.message : String(err))
      setNoticeKind('error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-xl w-[400px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5">
          <h2 className="text-xl font-bold text-text-strong">
            {isRegister ? t('注册', 'Sign Up') : t('登录', 'Sign In')}
          </h2>
        </div>
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          {notice && (
            <div className={`text-xs p-3 rounded-lg ${noticeKind === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
              {notice}
            </div>
          )}

          <div className={`text-xs p-3 rounded-lg border ${registerBlockedByNeo4j ? 'bg-amber-50 text-amber-800 border-amber-100' : 'bg-gray-50 text-text-muted border-black/5'}`}>
            <div className="font-semibold text-text-strong mb-1">
              {t('启动状态', 'Startup status')}
            </div>
            <div>
              {t('当前后端', 'Current backend')}: <span className="font-mono">{backendLabel}</span>
              {bootstrap?.neo4j_available === false && backendLabel === 'neo4j' ? ` · ${t('Neo4j 未就绪', 'Neo4j not ready')}` : ''}
            </div>
            {registerBlockedByNeo4j && (
              <div className="mt-2 leading-relaxed">
                {neo4jAuthFailed
                  ? t(
                    'Neo4j 已响应，但账号或密码认证失败。Promethea 不会静默注册到 fallback，请修正 Neo4j 配置或进入设置/诊断模式切换后端后重启。',
                    'Neo4j responded, but authentication failed. Promethea will not silently register into a fallback backend. Fix Neo4j settings, or enter setup/diagnostics mode, switch backend, then restart.',
                  )
                  : t(
                    'Neo4j 是默认和核心图结构后端。当前没有连接到 Neo4j，因此不会静默注册到 fallback。你可以启动 Neo4j 后重试，或进入设置/诊断模式切换到其他后端后重启。',
                    'Neo4j is the default and core graph backend. It is currently unavailable, so Promethea will not silently register into a fallback backend. Start Neo4j and retry, or enter setup/diagnostics mode, switch backend, then restart.',
                  )}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-text-strong">{t('用户名', 'Username')}</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition-shadow"
              placeholder={t('输入用户名', 'Enter username')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-text-strong">{t('密码', 'Password')}</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition-shadow"
              placeholder={t('输入密码', 'Enter password')}
            />
          </div>

          {!isRegister && (
            <label className="flex items-start gap-2 rounded-xl border border-black/5 bg-gray-50 px-3 py-2 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="mt-0.5"
              />
              <span>{t('保持登录：只保存登录令牌，不保存密码。', 'Stay signed in: store a sign-in token, never the password.')}</span>
            </label>
          )}

          {isRegister && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-text-strong">{t('Agent 名称（可选）', 'Agent Name (Optional)')}</label>
              <input
                type="text"
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition-shadow"
                placeholder={t('默认：Promethea', 'Default: Promethea')}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 mt-2 bg-brand-500 hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            {loading ? t('处理中...', 'Processing...') : (isRegister ? t('注册', 'Sign Up') : t('登录', 'Sign In'))}
          </button>

          <div className="text-center mt-2">
            <button
              type="button"
              onClick={() => { setIsRegister(!isRegister); setNotice('') }}
              className="text-xs text-brand-600 hover:underline"
            >
              {isRegister ? t('已有账号？登录', 'Already have an account? Sign in') : t('还没有账号？注册', "Don't have an account? Sign up")}
            </button>
          </div>

          {registerBlockedByNeo4j && (
            <button
              type="button"
              onClick={onEnterSetup}
              className="text-xs px-3 py-2 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
            >
              {t('进入设置 / 诊断模式', 'Enter setup / diagnostics mode')}
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
