'use client';

import { useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { ErrorBanner } from './Field';
import { api, ApiError, type Brand } from '@/lib/api';

/**
 * Create and review brand voices. Without this the brand selector in chat can
 * never be populated, which makes brand-grounded generation unreachable.
 */
export function BrandPanel({
  workspaceId,
  brands,
  onCreated,
}: {
  workspaceId: string;
  brands: Brand[];
  onCreated: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: '',
    description: '',
    tone_of_voice: '',
    target_audience: '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.createBrand(workspaceId, { ...form, name: form.name.trim() });
      setForm({ name: '', description: '', tone_of_voice: '', target_audience: '' });
      setOpen(false);
      await onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the brand.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="label mb-0">Brands</h2>
        <button
          className="btn-ghost px-2 py-1"
          onClick={() => setOpen((v) => !v)}
          aria-label="New brand"
          aria-expanded={open}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      {open && (
        <form onSubmit={submit} className="mb-4 space-y-2 rounded-lg border border-ink-600 p-3">
          <ErrorBanner message={error} />
          <input
            className="input"
            placeholder="Brand name"
            aria-label="Brand name"
            required
            value={form.name}
            onChange={set('name')}
          />
          <input
            className="input"
            placeholder="What the brand does"
            aria-label="Brand description"
            value={form.description}
            onChange={set('description')}
          />
          <input
            className="input"
            placeholder="Tone of voice"
            aria-label="Tone of voice"
            value={form.tone_of_voice}
            onChange={set('tone_of_voice')}
          />
          <input
            className="input"
            placeholder="Target audience"
            aria-label="Target audience"
            value={form.target_audience}
            onChange={set('target_audience')}
          />
          <button className="btn-primary w-full" disabled={busy || !form.name.trim()}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? 'Saving' : 'Save brand'}
          </button>
        </form>
      )}

      {brands.length === 0 ? (
        <p className="text-sm text-slate-500">
          No brands yet. Add one so replies match your voice.
        </p>
      ) : (
        <ul className="space-y-1" aria-label="Brands">
          {brands.map((b) => (
            <li
              key={b.id}
              className="rounded-lg px-3 py-2 text-sm text-slate-300"
              title={b.tone_of_voice || undefined}
            >
              <span className="block truncate font-medium">{b.name}</span>
              {b.tone_of_voice && (
                <span className="block truncate text-xs text-slate-500">{b.tone_of_voice}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
