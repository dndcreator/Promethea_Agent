import React, { createContext, useContext, useEffect, useState } from 'react';
import { authFetch, getAuthToken, setAuthToken, clearAuthToken } from '../lib/api';

interface UserProfile {
  username: string;
  user_id: string;
  agent_name?: string;
}

interface AuthContextType {
  user: UserProfile | null;
  loading: boolean;
  login: (token: string, profile: UserProfile) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchProfile = async () => {
    try {
      const res = await authFetch('/api/user/profile');
      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else {
        clearAuthToken();
      }
    } catch (e) {
      clearAuthToken();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handleAuthExpired = () => setUser(null);
    window.addEventListener('auth-expired', handleAuthExpired);

    if (getAuthToken()) {
      fetchProfile();
    } else {
      // Try restoring via cookie
      fetchProfile();
    }

    return () => window.removeEventListener('auth-expired', handleAuthExpired);
  }, []);

  const login = (token: string, profile: UserProfile) => {
    setAuthToken(token);
    setUser(profile);
  };

  const logout = async () => {
    try {
      await authFetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {}
    clearAuthToken();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};
