'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { ErrorBanner, Field } from '@/components/Field';
import { useAuth } from '@/lib/auth';
import { ApiError } from '@/lib/api';

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace('/dashboard');
  }, [loading, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 401
            ? err.code === 'email_not_verified'
              ? 'Please verify your email address first. Check your inbox for the link.'
              : 'That email and password combination is not correct.'
            : err.message
          : 'Something went wrong. Please try again.',
      );
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" className="mb-8 flex items-center gap-2 text-lg font-semibold text-white">
        <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
      </Link>
      <div className="card">
        <h1 className="mb-1 text-xl font-semibold text-white">Welcome back</h1>
        <p className="mb-6 text-sm text-slate-400">Log in to your workspace.</p>
        <form onSubmit={onSubmit} className="space-y-4">
          <ErrorBanner message={error} />
          <Field
            label="Email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />
          <div className="relative">
            <Link
              href="/forgot-password"
              className="absolute right-0 top-0 text-xs text-slate-400 hover:text-indigo-400 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Field
            label="Password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••••••"
          />
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? 'Logging in' : 'Log in'}
          </button>
        </form>
      </div>
      <p className="mt-5 text-center text-sm text-slate-500">
        No account?{' '}
        <Link href="/register" className="text-indigo-400 hover:underline">
          Create one
        </Link>
      </p>
    </main>
  );
}
