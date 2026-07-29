'use client';

import { useRouter } from 'next/navigation';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, tokens, type User, type Workspace } from './api';

type AuthState = {
  user: User | null;
  workspaces: Workspace[];
  /** True until the initial session probe finishes. Guards against UI flicker. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    fullName: string,
    workspaceName?: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
  refreshWorkspaces: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const hydrate = useCallback(async () => {
    if (!tokens.access) {
      setUser(null);
      setWorkspaces([]);
      setLoading(false);
      return;
    }
    try {
      const me = await api.me();
      setUser(me.user);
      setWorkspaces(me.workspaces);
    } catch {
      tokens.clear();
      setUser(null);
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Restore the session on hard reload — this is what makes persistence work.
  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  const login = useCallback(
    async (email: string, password: string) => {
      const pair = await api.login(email, password);
      tokens.set(pair.access_token, pair.refresh_token);
      const me = await api.me();
      setUser(me.user);
      setWorkspaces(me.workspaces);
      router.push('/dashboard');
    },
    [router],
  );

  const register = useCallback(
    async (email: string, password: string, fullName: string, workspaceName?: string) => {
      const pair = await api.register(email, password, fullName, workspaceName);
      tokens.set(pair.access_token, pair.refresh_token);
      const me = await api.me();
      setUser(me.user);
      setWorkspaces(me.workspaces);
      router.push('/dashboard');
    },
    [router],
  );

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setWorkspaces([]);
    router.push('/login');
  }, [router]);

  const refreshWorkspaces = useCallback(async () => {
    const me = await api.me();
    setWorkspaces(me.workspaces);
  }, []);

  const value = useMemo(
    () => ({ user, workspaces, loading, login, register, logout, refreshWorkspaces }),
    [user, workspaces, loading, login, register, logout, refreshWorkspaces],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

/** Redirects to /login once the session probe confirms there is no user. */
export function useRequireAuth() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [loading, user, router]);
  return { user, loading };
}
