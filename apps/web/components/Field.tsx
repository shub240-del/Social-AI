import { AlertCircle } from 'lucide-react';
import type { InputHTMLAttributes } from 'react';

/** Labelled input. The label is bound with htmlFor so the control is reachable
 *  by screen readers and clicking the label focuses the field. */
export function Field({
  label,
  name,
  hint,
  ...props
}: { label: string; name: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={name} className="mb-1.5 block text-sm font-medium text-slate-300">
        {label}
      </label>
      <input id={name} name={name} className="input" {...props} />
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-slate-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
      {label}
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center">
      <p className="font-medium text-slate-300">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{body}</p>
    </div>
  );
}
