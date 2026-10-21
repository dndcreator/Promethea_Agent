import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { X } from 'lucide-react'
import { authFetch } from '../services/api'
import { useAuth } from '../store/AuthContext'
import { useLanguage } from '../store/LanguageContext'
import FeatureSurface from './FeatureSurface'

type NoticeKind = 'error' | 'success'

function parseErrorDetail(payload: unknown): { code: string; message: string } {
  const record = payload as { error_detail?: unknown; detail?: unknown; error?: unknown }
  const detail = record?.error_detail || record?.detail || record?.error
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

export default function AuthModal({ onClose, onEnterSetup }: { onEnterSetup?: () => void; onClose?: () => void }) {
  const { login } = useAuth()
  const { t } = useLanguage()
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [agentName, setAgentName] = useState('')
  const [remember, setRemember] = useState(true)
  const [notice, setNotice] = useState('')
  const [noticeKind, setNoticeKind] = useState<NoticeKind>('error')
  const [loading, setLoading] = useState(false)
  const request = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => { request.current?.abort() }
  }, [])
  const close = () => { request.current?.abort(); onClose?.() }

  function getLocalizedFailure(resStatus: number, code: string, message: string): string {
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
    if (loading) return
    const controller = new AbortController()
    request.current = controller
    setNotice('')
    setNoticeKind('error')
    setLoading(true)

    try {
      const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login'
      const body = isRegister
        ? { username, password, agent_name: agentName || 'Promethea' }
        : { username, password, remember_me: remember }

      const res = await authFetch(endpoint, {
        signal: controller.signal,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (controller.signal.aborted) return

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
        if (controller.signal.aborted) return
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
      if (controller.signal.aborted) return
      setNotice(err instanceof Error ? err.message : String(err))
      setNoticeKind('error')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return (
    <FeatureSurface onClose={close} label={isRegister ? t('注册', 'Sign Up') : t('登录', 'Sign In')} size="compact">
      <div className="auth-form overflow-y-auto">
        <div className="flex items-center justify-between border-b border-black/5 px-6 py-4">
          <h2 className="text-xl font-bold text-text-strong">
            {isRegister ? t('注册', 'Sign Up') : t('登录', 'Sign In')}
          </h2>
          {onClose && (
            <button type="button" onClick={close} title={t('关闭', 'Close')} aria-label={t('关闭登录', 'Close sign in')} className="icon-button">
              <X size={18} />
            </button>
          )}
        </div>
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          {notice && (
            <div role={noticeKind === 'success' ? 'status' : 'alert'} className={`text-xs p-3 rounded-lg ${noticeKind === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
              {notice}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label htmlFor="auth-username" className="text-xs font-semibold text-text-strong">{t('用户名', 'Username')}</label>
            <input
              id="auth-username" autoComplete="username" disabled={loading}
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition-shadow"
              placeholder={t('输入用户名', 'Enter username')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="auth-password" className="text-xs font-semibold text-text-strong">{t('密码', 'Password')}</label>
            <input
              id="auth-password" autoComplete={isRegister ? 'new-password' : 'current-password'} disabled={loading}
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
              <span>{t('保持登录', 'Stay signed in')}</span>
            </label>
          )}

          {isRegister && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="auth-agent-name" className="text-xs font-semibold text-text-strong">{t('Agent 名称（可选）', 'Agent Name (Optional)')}</label>
              <input
                id="auth-agent-name" disabled={loading}
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
              disabled={loading}
              onClick={() => { setIsRegister(!isRegister); setNotice('') }}
              className="text-xs text-brand-600 hover:underline"
            >
              {isRegister ? t('已有账号？登录', 'Already have an account? Sign in') : t('还没有账号？注册', "Don't have an account? Sign up")}
            </button>
          </div>
          {onEnterSetup && <button type="button" className="text-button self-center" onClick={() => { request.current?.abort(); onEnterSetup() }}>{t('系统诊断', 'Diagnostics')}</button>}
        </form>
      </div>
    </FeatureSurface>
  )
}
