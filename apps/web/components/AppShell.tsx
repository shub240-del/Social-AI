'use client';

import Link from 'next/link';
import { LogOut, Sparkles } from 'lucide-react';
import { useAuth } from '@/lib/auth';

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen">
      <header className="border-b border-ink-600 bg-ink-800">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 text-sm font-semibold text-white"
          >
            <Sparkles className="h-4 w-4 text-indigo-400" /> Social AI
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-400">{user?.email}</span>
            <button onClick={() => void logout()} className="btn-ghost" aria-label="Log out">
              <LogOut className="h-4 w-4" /> Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
