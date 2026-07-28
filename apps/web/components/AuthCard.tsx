import Link from 'next/link';
import { Sparkles } from 'lucide-react';

/** Shared frame for the standalone auth pages (verify, forgot, reset). */
export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <Link href="/" className="mb-8 flex items-center gap-2 text-lg font-semibold text-white">
        <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
      </Link>
      <div className="card">
        <h1 className="mb-1 text-xl font-semibold text-white">{title}</h1>
        {subtitle && <p className="mb-6 text-sm text-slate-400">{subtitle}</p>}
        {children}
      </div>
      {footer && <p className="mt-5 text-center text-sm text-slate-500">{footer}</p>}
    </main>
  );
}

export function SuccessBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="status"
      className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300"
    >
      {message}
    </div>
  );
}
