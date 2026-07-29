import Link from 'next/link';
import { Compass } from 'lucide-react';

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <div className="card">
        <Compass className="mb-3 h-6 w-6 text-indigo-400" />
        <h1 className="mb-1 text-lg font-semibold text-white">Page not found</h1>
        <p className="mb-5 text-sm text-slate-400">
          That page does not exist, or you do not have access to it.
        </p>
        <Link href="/dashboard" className="btn-primary">
          Back to dashboard
        </Link>
      </div>
    </main>
  );
}
