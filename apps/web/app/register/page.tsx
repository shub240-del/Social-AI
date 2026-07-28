'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { AuthCard } from '@/components/AuthCard';
import { ErrorBanner, Field } from '@/components/Field';
import { api, ApiError } from '@/lib/api';

const MIN_LENGTH = 8;

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_LENGTH) {
      setError(`Please use at least ${MIN_LENGTH} characters.`);
      return;
    }
    setBusy(true);
    try {
      await api.register(email, password, fullName || email.split('@')[0]);
      router.push('/dashboard');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('An account with that email already exists. Try logging in.');
      } else if (err instanceof ApiError && err.status === 422) {
        setError(err.message);
      } else {
        setError('We could not create your account. Please try again.');
      }
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Create your account"
      subtitle="Start generating on-brand content in a minute."
      footer={
        <>
          Already registered?{' '}
          <Link href="/login" className="text-indigo-400 hover:underline">
            Log in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorBanner message={error} />
        <Field
          label="Full name"
          name="full_name"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Ada Lovelace"
        />
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
          autoComplete="new-password"
          required
          minLength={MIN_LENGTH}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••••••"
          hint={`At least ${MIN_LENGTH} characters.`}
        />
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {busy ? 'Creating your account' : 'Create account'}
        </button>
      </form>
    </AuthCard>
  );
}
