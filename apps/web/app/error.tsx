'use client';

import { useEffect } from 'react';
import { AlertCircle, RotateCw } from 'lucide-react';

/**
 * Route-level error boundary. Without this an unhandled render error leaves
 * the user on a blank page with no way forward.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <div className="card">
        <AlertCircle className="mb-3 h-6 w-6 text-red-400" />
        <h1 className="mb-1 text-lg font-semibold text-white">Something went wrong</h1>
        <p className="mb-5 text-sm text-slate-400">
          The page failed to load. This is usually temporary.
          {error.digest && (
            <>
              {' '}
              Reference <code className="text-slate-300">{error.digest}</code>.
            </>
          )}
        </p>
        <button onClick={reset} className="btn-primary">
          <RotateCw className="h-4 w-4" /> Try again
        </button>
      </div>
    </main>
  );
}
