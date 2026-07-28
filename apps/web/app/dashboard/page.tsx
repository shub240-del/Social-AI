'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { LogOut, Plus, Sparkles, Users } from 'lucide-react';
import { EmptyState, ErrorBanner, Spinner } from '@/components/Field';
import { api, type WorkspaceSummary } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

export default function DashboardPage() {
  const { user, loading, logout } = useAuth();
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setWorkspaces(await api.listWorkspaces());
    } catch {
      setError('We could not load your workspaces.');
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createWorkspace(name.trim());
      setName('');
      setCreating(false);
      await load();
    } catch {
      setError('We could not create that workspace.');
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading your dashboard" />
      </main>
    );
  }
  if (!user) return null;

  return (
    <main className="min-h-screen">
      <header className="border-b border-slate-800">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold text-white">
            <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-400 sm:inline">{user.email}</span>
            <button onClick={() => void logout()} className="btn-ghost" aria-label="Log out">
              <LogOut className="h-4 w-4" /> Log out
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-white">
              Welcome back, {user.full_name || user.email.split('@')[0]}
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Pick a workspace to start writing, or create another one.
            </p>
          </div>
          <button onClick={() => setCreating((v) => !v)} className="btn-primary">
            <Plus className="h-4 w-4" /> New workspace
          </button>
        </div>

        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>

        {creating && (
          <form onSubmit={create} className="card mt-4 flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1">
              <label htmlFor="ws-name" className="mb-1.5 block text-sm font-medium text-slate-300">
                Workspace name
              </label>
              <input
                id="ws-name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Marketing"
                required
              />
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? 'Creating' : 'Create'}
            </button>
            <button type="button" className="btn-ghost" onClick={() => setCreating(false)}>
              Cancel
            </button>
          </form>
        )}

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {workspaces.map((workspace) => (
            <Link key={workspace.id} href={`/workspace/${workspace.id}`} className="card block transition hover:border-indigo-500/60">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-white">{workspace.name}</p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">/{workspace.slug}</p>
                </div>
                <span className="shrink-0 rounded-full border border-slate-700 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
                  {workspace.role}
                </span>
              </div>
              <p className="mt-4 inline-flex items-center gap-1.5 text-sm text-indigo-400">
                <Users className="h-3.5 w-3.5" /> Open workspace
              </p>
            </Link>
          ))}
        </div>

        {workspaces.length === 0 && (
          <div className="mt-6">
            <EmptyState
              title="No workspaces yet"
              body="Create your first workspace to start generating content."
            />
          </div>
        )}
      </div>
    </main>
  );
}
