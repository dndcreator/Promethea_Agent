import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { authFetch, getAuthToken, setAuthToken, clearAuthToken } from '../services/api';

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
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [authNotice, setAuthNotice] = useState('');
  const lastVerifiedAtRef = useRef(0);

  const fetchProfile = useCallback(async (options: { showChecking?: boolean } = {}) => {
    const showChecking = options.showChecking ?? false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), PROFILE_VERIFY_TIMEOUT_MS);
    if (showChecking) setChecking(true);
    try {
      const res = await authFetch('/api/user/profile', { signal: controller.signal, suppressAuthExpired: true });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        setAuthNotice('');
        lastVerifiedAtRef.current = Date.now();
        return true;
      } else if (res.status === 401 || res.status === 403) {
        clearAuthToken();
        setUser(null);
        setAuthNotice('Session expired. Please sign in again.');
        return false;
      } else {
        setAuthNotice('Could not verify your session. Keeping the current sign-in state and retrying later.');
        return Boolean(getAuthToken());
      }
    } catch {
      setAuthNotice('Could not verify your session. Keeping the current sign-in state and retrying later.');
      return Boolean(getAuthToken());
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
      if (showChecking) setChecking(false);
    }
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      setUser(null);
      setAuthNotice('Session expired. Please sign in again.');
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
      window.removeEventListener('auth-expired', handleAuthExpired);
      window.removeEventListener('focus', recheck);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchProfile]);

  const login = (token: string, profile: UserProfile, options: { remember?: boolean } = {}) => {
    setAuthToken(token, options.remember ?? true);
    setUser(profile);
    setAuthNotice('');
    lastVerifiedAtRef.current = Date.now();
  };

  const logout = async () => {
    try {
      await authFetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Local logout should still clear client state if the server is unavailable.
    }
    clearAuthToken();
    setUser(null);
    lastVerifiedAtRef.current = 0;
  };

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
