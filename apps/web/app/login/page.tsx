'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { AuthCard } from '@/components/AuthCard';
import { ErrorBanner, Field } from '@/components/Field';
import { api, ApiError } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(email, password);
      router.push('/dashboard');
    } catch (err) {
      if (err instanceof ApiError && err.code === 'email_not_verified') {
        setError('Confirm your email address first. Check your inbox for the link.');
      } else if (err instanceof ApiError && err.status === 401) {
        setError('Incorrect email or password.');
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts. Please wait a minute and try again.');
      } else {
        setError('We could not sign you in. Please try again.');
      }
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Log in"
      subtitle="Welcome back to Social AI."
      footer={
        <>
          No account?{' '}
          <Link href="/register" className="text-indigo-400 hover:underline">
            Create one
          </Link>
        </>
      }
    >
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
        <div className="text-right">
          <Link href="/forgot-password" className="text-xs text-slate-400 hover:text-indigo-400">
            Forgot your password?
          </Link>
        </div>
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {busy ? 'Signing in' : 'Log in'}
        </button>
      </form>
    </AuthCard>
  );
}
