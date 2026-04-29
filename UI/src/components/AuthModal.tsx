import { useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../store/AuthContext';
import { authFetch } from '../lib/api';
import { useLanguage } from '../store/LanguageContext';

export default function AuthModal() {
  const { login } = useAuth();
  const { t } = useLanguage();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [agentName, setAgentName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login';
      const body = isRegister 
        ? { username, password, agent_name: agentName || 'Promethea' }
        : { username, password };

      const res = await authFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Authentication failed');
      }

      if (isRegister) {
        setIsRegister(false);
        setError(t('注册成功，请登录。', 'Registration successful. Please login.'));
      } else {
        const data = await res.json();
        // data contains: access_token, user_id, agent_name, username
        login(data.access_token, {
          username: data.username,
          user_id: data.user_id,
          agent_name: data.agent_name
        });
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-xl w-[400px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5">
          <h2 className="text-xl font-bold text-text-strong">
            {isRegister ? t('注册', 'Sign Up') : t('登录', 'Sign In')}
          </h2>
        </div>
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          {error && (
            <div className={`text-xs p-3 rounded-lg ${isRegister && error.includes('successful') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
              {error}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-text-strong">{t('用户名', 'Username')}</label>
            <input 
              type="text" 
              required
              value={username}
              onChange={e => setUsername(e.target.value)}
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
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-black/10 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-300 transition-shadow"
              placeholder={t('输入密码', 'Enter password')}
            />
          </div>

          {isRegister && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-text-strong">{t('Agent 名称（可选）', 'Agent Name (Optional)')}</label>
              <input 
                type="text" 
                value={agentName}
                onChange={e => setAgentName(e.target.value)}
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
              onClick={() => { setIsRegister(!isRegister); setError(''); }}
              className="text-xs text-brand-600 hover:underline"
            >
              {isRegister ? t('已有账号？去登录', 'Already have an account? Sign in') : t('还没有账号？去注册', "Don't have an account? Sign up")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
