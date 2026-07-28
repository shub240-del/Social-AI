'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { AuthCard } from '@/components/AuthCard';
import { ErrorBanner, Field } from '@/components/Field';
import { api, ApiError } from '@/lib/api';

const MIN_LENGTH = 12;

function ResetInner() {
  const token = useSearchParams().get('token');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    if (password.length < MIN_LENGTH) {
      setError(`Please use at least ${MIN_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token as string, password);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? 'This reset link is no longer valid. Please request a new one.'
          : 'We could not reset your password. Please try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard
        title="Reset link missing"
        subtitle="This page needs the link from your reset email."
        footer={
          <Link href="/forgot-password" className="text-indigo-400 hover:underline">
            Request a new link
          </Link>
        }
      >
        <ErrorBanner message="No reset token was found in the address." />
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard
        title="Password updated"
        subtitle="You have been signed out everywhere else for safety."
        footer={
          <Link href="/login" className="text-indigo-400 hover:underline">
            Log in with your new password
          </Link>
        }
      >
        <div className="flex items-center gap-2 text-sm text-emerald-300">
          <CheckCircle2 className="h-5 w-5" /> All set.
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password" subtitle={`At least ${MIN_LENGTH} characters.`}>
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorBanner message={error} />
        <Field
          label="New password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••••••"
        />
        <Field
          label="Confirm new password"
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          placeholder="••••••••••••"
        />
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {busy ? 'Updating' : 'Update password'}
        </button>
      </form>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<AuthCard title="Choose a new password" />}>
      <ResetInner />
    </Suspense>
  );
}
