'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { AuthCard, SuccessBanner } from '@/components/AuthCard';
import { ErrorBanner, Field } from '@/components/Field';
import { api, ApiError } from '@/lib/api';

type State = 'confirming' | 'done' | 'failed' | 'idle';

function VerifyInner() {
  const token = useSearchParams().get('token');
  const [state, setState] = useState<State>(token ? 'confirming' : 'idle');
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [resent, setResent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // React 18 StrictMode double-invokes effects; a single-use token would be
  // burned by the first call and rejected on the second.
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    api
      .confirmVerification(token)
      .then(() => setState('done'))
      .catch((err) => {
        setState('failed');
        setError(
          err instanceof ApiError && err.status === 401
            ? 'This link is no longer valid. It may have expired or already been used.'
            : 'We could not verify your email. Please try again.',
        );
      });
  }, [token]);

  async function resend(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.requestVerification(email);
      setResent('If that address has an account, a new verification link is on its way.');
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  if (state === 'confirming') {
    return (
      <AuthCard title="Verifying your email">
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> One moment…
        </div>
      </AuthCard>
    );
  }

  if (state === 'done') {
    return (
      <AuthCard
        title="Email verified"
        subtitle="Your account is confirmed and ready to use."
        footer={
          <Link href="/login" className="text-indigo-400 hover:underline">
            Continue to log in
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
    <AuthCard
      title={state === 'failed' ? 'Link expired' : 'Verify your email'}
      subtitle="Enter your address and we will send a fresh verification link."
      footer={
        <Link href="/login" className="text-indigo-400 hover:underline">
          Back to log in
        </Link>
      }
    >
      <form onSubmit={resend} className="space-y-4">
        <ErrorBanner message={error} />
        <SuccessBanner message={resent} />
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
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {busy ? 'Sending' : 'Send verification link'}
        </button>
      </form>
    </AuthCard>
  );
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<AuthCard title="Verify your email" />}>
      <VerifyInner />
    </Suspense>
  );
}
