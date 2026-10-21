import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { authFetch, getAuthToken, setAuthToken, clearAuthToken } from '../services/api';
import { useLanguage } from './LanguageContext';

interface UserProfile {
  username: string;
  user_id: string;
  agent_name?: string;
}

interface AuthContextType {
  user: UserProfile | null;
  loading: boolean;
  checking: boolean;
  authNotice: string;
  login: (token: string, profile: UserProfile, options?: { remember?: boolean }) => void;
  logout: () => Promise<void>;
  verifySession: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
const PROFILE_VERIFY_TIMEOUT_MS = 5000;
const PASSIVE_RECHECK_INTERVAL_MS = 5 * 60 * 1000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const { t } = useLanguage();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(() => Boolean(getAuthToken()));
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState<'' | 'expired' | 'unavailable'>('');
  const lastVerifiedAtRef = useRef(0);
  const profileRequestRef = useRef<AbortController | null>(null);
  const identityEpochRef = useRef(0);

  const invalidateProfile = useCallback(() => {
    identityEpochRef.current += 1;
    profileRequestRef.current?.abort();
    profileRequestRef.current = null;
    setChecking(false);
    setLoading(false);
  }, []);

  const fetchProfile = useCallback(async (options: { showChecking?: boolean } = {}) => {
    const showChecking = options.showChecking ?? false;
    const token = getAuthToken();
    if (!token) return false;
    profileRequestRef.current?.abort();
    const controller = new AbortController();
    profileRequestRef.current = controller;
    const epoch = ++identityEpochRef.current;
    const isCurrent = () => epoch === identityEpochRef.current && token === getAuthToken();
    const timeout = window.setTimeout(() => controller.abort(), PROFILE_VERIFY_TIMEOUT_MS);
    if (showChecking) setChecking(true);
    try {
      const res = await authFetch('/api/user/profile', { signal: controller.signal, suppressAuthExpired: true });
      if (!isCurrent()) return false;
      if (res.ok) {
        const data = await res.json();
        if (!isCurrent()) return false;
        setUser(data);
        setNotice('');
        lastVerifiedAtRef.current = Date.now();
        return true;
      } else if (res.status === 401 || res.status === 403) {
        clearAuthToken();
        setUser(null);
        setNotice('expired');
        return false;
      } else {
        setNotice('unavailable');
        return Boolean(getAuthToken());
      }
    } catch {
      if (!isCurrent()) return false;
      setNotice('unavailable');
      return Boolean(getAuthToken());
    } finally {
      window.clearTimeout(timeout);
      if (epoch === identityEpochRef.current) {
        profileRequestRef.current = null;
        setLoading(false);
        setChecking(false);
      }
    }
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      invalidateProfile();
      setUser(null);
      lastVerifiedAtRef.current = 0;
      setNotice('expired');
    };
    window.addEventListener('auth-expired', handleAuthExpired);

    if (getAuthToken() && lastVerifiedAtRef.current === 0) {
      fetchProfile({ showChecking: true });
    }

    const recheck = () => {
      if (!getAuthToken()) return;
      if (Date.now() - lastVerifiedAtRef.current < PASSIVE_RECHECK_INTERVAL_MS) return;
      fetchProfile({ showChecking: false });
    };
    window.addEventListener('focus', recheck);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') recheck();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      identityEpochRef.current += 1;
      profileRequestRef.current?.abort();
      profileRequestRef.current = null;
      window.removeEventListener('auth-expired', handleAuthExpired);
      window.removeEventListener('focus', recheck);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchProfile, invalidateProfile]);

  const login = (token: string, profile: UserProfile, options: { remember?: boolean } = {}) => {
    invalidateProfile();
    setAuthToken(token, options.remember ?? true);
    setUser(profile);
    setNotice('');
    lastVerifiedAtRef.current = Date.now();
  };

  const logout = async () => {
    const request = authFetch('/api/auth/logout', { method: 'POST', suppressAuthExpired: true });
    invalidateProfile();
    clearAuthToken();
    setUser(null);
    setNotice('');
    lastVerifiedAtRef.current = 0;
    try {
      await request;
    } catch {
      // Local logout should still clear client state if the server is unavailable.
    }
  };

  const authNotice = notice === 'expired'
    ? t('登录已过期，请重新登录。', 'Session expired. Please sign in again.')
    : notice === 'unavailable'
      ? t('暂时无法校验登录状态，请稍后重试。', 'Could not verify your session. Please retry shortly.')
      : '';

  return (
    <AuthContext.Provider value={{ user, loading, checking, authNotice, login, logout, verifySession: () => fetchProfile({ showChecking: true }) }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
