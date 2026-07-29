'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ArrowRight, Loader2, Plus } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { Empty, ErrorBanner, Spinner } from '@/components/Field';
import { api, ApiError } from '@/lib/api';
import { useAuth, useRequireAuth } from '@/lib/auth';

export default function DashboardPage() {
  const { loading } = useRequireAuth();
  const { user, workspaces, refreshWorkspaces } = useAuth();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading || !user) return <Spinner label="Loading your session" />;

  async function createWorkspace(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createWorkspace(name.trim());
      setName('');
      await refreshWorkspaces();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the workspace.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <h1 className="text-2xl font-semibold text-white">
        Welcome back, {user.full_name.split(' ')[0]}
      </h1>
      <p className="mt-1 text-sm text-slate-400">
        Pick a workspace to start generating content, or create a new one.
      </p>

      <form onSubmit={createWorkspace} className="mt-6 flex gap-2">
        <input
          className="input max-w-xs"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New workspace name"
          aria-label="New workspace name"
        />
        <button className="btn-primary" disabled={busy || !name.trim()}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Create
        </button>
      </form>
      <div className="mt-3">
        <ErrorBanner message={error} />
      </div>

      <section className="mt-8">
        <h2 className="label">Your workspaces</h2>
        {workspaces.length === 0 ? (
          <Empty
            title="No workspaces yet"
            body="Create your first workspace above to get started."
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2" aria-label="Workspaces">
            {workspaces.map((ws) => (
              <li key={ws.id}>
                <Link
                  href={`/workspace/${ws.id}`}
                  className="card flex items-center justify-between transition hover:border-indigo-500"
                >
                  <span>
                    <span className="block font-medium text-white">{ws.name}</span>
                    <span className="text-xs uppercase tracking-wide text-slate-500">
                      {ws.role ?? 'member'}
                    </span>
                  </span>
                  <ArrowRight className="h-4 w-4 text-slate-500" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </AppShell>
  );
}
