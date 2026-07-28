'use client';

import { useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { ErrorBanner } from './Field';
import { api, ApiError, type Brand, type Campaign } from '@/lib/api';

const STATUS_STYLES: Record<string, string> = {
  draft: 'bg-slate-500/15 text-slate-300',
  active: 'bg-emerald-500/15 text-emerald-300',
  paused: 'bg-amber-500/15 text-amber-300',
  completed: 'bg-indigo-500/15 text-indigo-300',
};

/**
 * Create and list the campaigns of a workspace.
 *
 * The API and the client library have supported campaigns since the first
 * release, but nothing rendered them, so the objective a campaign carries
 * could never reach the model. This panel is what makes that reachable.
 */
export function CampaignPanel({
  workspaceId,
  campaigns,
  brands,
  onCreated,
}: {
  workspaceId: string;
  campaigns: Campaign[];
  brands: Brand[];
  onCreated: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: '', objective: '', brand_id: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.createCampaign(workspaceId, {
        name: form.name.trim(),
        objective: form.objective.trim(),
        brand_id: form.brand_id || undefined,
      });
      setForm({ name: '', objective: '', brand_id: '' });
      setOpen(false);
      await onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the campaign.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wide text-slate-500">Campaigns</h2>
        <button
          type="button"
          className="btn-ghost px-2 py-1"
          onClick={() => setOpen((v) => !v)}
          aria-label="New campaign"
          aria-expanded={open}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      {open && (
        <form onSubmit={submit} className="mb-3 space-y-2 rounded-lg border border-slate-800 p-3">
          <ErrorBanner message={error} />
          <input
            className="input"
            placeholder="Campaign name"
            aria-label="Campaign name"
            required
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
          <input
            className="input"
            placeholder="Objective"
            aria-label="Campaign objective"
            value={form.objective}
            onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
          />
          <select
            className="input"
            aria-label="Campaign brand"
            value={form.brand_id}
            onChange={(e) => setForm((f) => ({ ...f, brand_id: e.target.value }))}
          >
            <option value="">No brand</option>
            {brands.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <button className="btn-primary w-full" disabled={busy || !form.name.trim()}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? 'Saving' : 'Save campaign'}
          </button>
        </form>
      )}

      {campaigns.length === 0 ? (
        <p className="text-sm text-slate-500">No campaigns yet.</p>
      ) : (
        <ul className="space-y-1" aria-label="Campaigns">
          {campaigns.map((c) => (
            <li key={c.id} className="rounded-lg px-3 py-2 text-sm text-slate-300">
              <span className="block truncate font-medium">{c.name}</span>
              <span
                className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                  STATUS_STYLES[c.status] ?? STATUS_STYLES.draft
                }`}
              >
                {c.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
