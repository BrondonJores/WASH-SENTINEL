import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, getToken, setToken, setUnauthorizedHandler } from '../lib/api';
import type { AuthUser } from '../lib/api';

interface AuthState {
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function storedUser(): AuthUser | null {
  try {
    return JSON.parse(localStorage.getItem('wash_admin_user') ?? 'null') as AuthUser | null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => (getToken() ? storedUser() : null));

  const logout = useCallback(() => {
    const hadToken = getToken() !== null;
    setToken(null);
    setUser(null);
    localStorage.removeItem('wash_admin_user');
    if (hadToken) api.logout().catch(() => undefined);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      localStorage.removeItem('wash_admin_user');
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { token, user: u } = await api.login(email, password);
    setToken(token);
    setUser(u);
    localStorage.setItem('wash_admin_user', JSON.stringify(u));
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth utilisé hors AuthProvider');
  return ctx;
}
