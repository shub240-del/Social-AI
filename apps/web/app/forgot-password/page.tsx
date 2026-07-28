'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { AuthCard, SuccessBanner } from '@/components/AuthCard';
import { ErrorBanner, Field } from '@/components/Field';
import { api } from '@/lib/api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle={
        sent
          ? undefined
          : 'We will email you a link to choose a new password.'
      }
      footer={
        <Link href="/login" className="text-indigo-400 hover:underline">
          Back to log in
        </Link>
      }
    >
      {sent ? (
        // Deliberately not confirming whether the address exists.
        <SuccessBanner message="If that address has an account, a reset link is on its way. The link expires in one hour." />
      ) : (
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
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? 'Sending' : 'Send reset link'}
          </button>
        </form>
      )}
    </AuthCard>
  );
}
