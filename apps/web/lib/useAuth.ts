'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api, isAuthenticated, tokens, type Me } from '@/lib/api';

/**
 * Loads the current user and redirects to /login when there is no valid
 * session. `loading` starts true so a protected page never flashes its
 * contents before the check completes.
 */
export function useAuth(options: { redirect?: boolean } = {}) {
  const { redirect = true } = options;
  const router = useRouter();
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setLoading(false);
      if (redirect) router.replace('/login');
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      tokens.clear();
      if (redirect) router.replace('/login');
      else setError('Your session has expired.');
    } finally {
      setLoading(false);
    }
  }, [redirect, router]);

  useEffect(() => {
    void load();
  }, [load]);

  const logout = useCallback(async () => {
    await api.logout();
    router.replace('/login');
  }, [router]);

  return { user, loading, error, reload: load, logout };
}
