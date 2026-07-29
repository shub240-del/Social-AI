'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { ErrorBanner, Field } from '@/components/Field';
import { useAuth } from '@/lib/auth';
import { ApiError } from '@/lib/api';

export default function RegisterPage() {
  const { register, user, loading } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    password: '',
    workspace_name: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace('/dashboard');
  }, [loading, user, router]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }
    setBusy(true);
    try {
      await register(
        form.email,
        form.password,
        form.full_name,
        form.workspace_name.trim() || undefined,
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 409
            ? 'An account with that email already exists.'
            : err.message
          : 'Something went wrong. Please try again.',
      );
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
      <Link href="/" className="mb-8 flex items-center gap-2 text-lg font-semibold text-white">
        <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
      </Link>
      <div className="card">
        <h1 className="mb-1 text-xl font-semibold text-white">Create your account</h1>
        <p className="mb-6 text-sm text-slate-400">
          We&apos;ll set up your first workspace at the same time.
        </p>
        <form onSubmit={onSubmit} className="space-y-4">
          <ErrorBanner message={error} />
          <Field
            label="Full name"
            name="full_name"
            required
            value={form.full_name}
            onChange={set('full_name')}
            placeholder="Ada Lovelace"
          />
          <Field
            label="Email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={form.email}
            onChange={set('email')}
            placeholder="you@company.com"
          />
          <Field
            label="Password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={form.password}
            onChange={set('password')}
            placeholder="At least 12 characters"
          />
          <Field
            label="Workspace name (optional)"
            name="workspace_name"
            value={form.workspace_name}
            onChange={set('workspace_name')}
            placeholder="Acme Marketing"
          />
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? 'Creating account' : 'Create account'}
          </button>
        </form>
      </div>
      <p className="mt-5 text-center text-sm text-slate-500">
        Already registered?{' '}
        <Link href="/login" className="text-indigo-400 hover:underline">
          Log in
        </Link>
      </p>
    </main>
  );
}
