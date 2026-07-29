'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Loader2, MessageSquare, Plus, Send } from 'lucide-react';
import { AppShell } from '@/components/AppShell';
import { BrandPanel } from '@/components/BrandPanel';
import { CampaignPanel } from '@/components/CampaignPanel';
import { Empty, ErrorBanner, Spinner } from '@/components/Field';
import {
  api,
  ApiError,
  type Brand,
  type Campaign,
  type Conversation,
  type Message,
} from '@/lib/api';
import { useRequireAuth } from '@/lib/auth';

type Tab = 'chats' | 'brands' | 'campaigns';

const TABS: { id: Tab; label: string }[] = [
  { id: 'chats', label: 'Chats' },
  { id: 'brands', label: 'Brands' },
  { id: 'campaigns', label: 'Campaigns' },
];

export default function WorkspacePage() {
  const { loading: authLoading, user } = useRequireAuth();
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [tab, setTab] = useState<Tab>('chats');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [brandId, setBrandId] = useState('');
  const [campaignId, setCampaignId] = useState('');
  const [prompt, setPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadSidebar = useCallback(async () => {
    const [convs, brandPage, campaignPage] = await Promise.all([
      api.listConversations(workspaceId),
      api.listBrands(workspaceId),
      api.listCampaigns(workspaceId),
    ]);
    setConversations(convs.items);
    setBrands(brandPage.items);
    setCampaigns(campaignPage.items);
    return convs.items;
  }, [workspaceId]);

  // Initial load. Restores the most recent conversation so a reload lands
  // the user exactly where they left off.
  useEffect(() => {
    if (authLoading || !user) return;
    let cancelled = false;
    (async () => {
      try {
        const items = await loadSidebar();
        if (cancelled) return;
        if (items.length) {
          const detail = await api.getConversation(workspaceId, items[0].id);
          if (cancelled) return;
          setActiveId(detail.id);
          setMessages(detail.messages);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? 'This workspace does not exist or you do not have access to it.'
              : 'Could not load this workspace.',
          );
        }
      } finally {
        if (!cancelled) setLoadingData(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authLoading, user, workspaceId, loadSidebar]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages, sending]);

  async function openConversation(id: string) {
    setError(null);
    setActiveId(id);
    setMessages([]);
    try {
      const detail = await api.getConversation(workspaceId, id);
      setMessages(detail.messages);
    } catch {
      setError('Could not open that conversation.');
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || sending) return;

    setPrompt('');
    setSending(true);
    setError(null);
    // Optimistic echo so the UI feels immediate; replaced by server state below.
    const optimistic: Message = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: text,
      model: null,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);

    try {
      const res = await api.sendMessage(workspaceId, {
        prompt: text,
        conversation_id: activeId ?? undefined,
        brand_id: brandId || undefined,
        campaign_id: campaignId || undefined,
      });
      setActiveId(res.conversation_id);
      const detail = await api.getConversation(workspaceId, res.conversation_id);
      setMessages(detail.messages);
      await loadSidebar();
    } catch (err) {
      setMessages((m) => m.filter((x) => x.id !== optimistic.id));
      setPrompt(text);
      setError(
        err instanceof ApiError
          ? err.status === 429
            ? 'You are sending messages too quickly. Give it a moment.'
            : err.message
          : 'The assistant could not respond.',
      );
    } finally {
      setSending(false);
    }
  }

  if (authLoading || !user) return <Spinner label="Loading your session" />;

  return (
    <AppShell>
      <Link
        href="/dashboard"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200"
      >
        <ArrowLeft className="h-4 w-4" /> All workspaces
      </Link>

      {loadingData ? (
        <Spinner label="Loading workspace" />
      ) : (
        <div className="grid gap-6 md:grid-cols-[260px_1fr]">
          <aside>
            <div role="tablist" aria-label="Workspace sections" className="mb-4 flex gap-1">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                    tab === t.id
                      ? 'bg-indigo-500/15 text-indigo-200'
                      : 'text-slate-400 hover:bg-ink-700'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {tab === 'chats' && (
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="label mb-0">Conversations</h2>
                  <button
                    className="btn-ghost px-2 py-1"
                    onClick={() => {
                      setActiveId(null);
                      setMessages([]);
                      setError(null);
                    }}
                    aria-label="New conversation"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
                {conversations.length === 0 ? (
                  <p className="text-sm text-slate-500">No conversations yet.</p>
                ) : (
                  <ul className="space-y-1" aria-label="Conversations">
                    {conversations.map((c) => (
                      <li key={c.id}>
                        <button
                          onClick={() => void openConversation(c.id)}
                          className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                            c.id === activeId
                              ? 'bg-indigo-500/15 text-indigo-200'
                              : 'text-slate-400 hover:bg-ink-700'
                          }`}
                        >
                          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{c.title}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {tab === 'brands' && (
              <BrandPanel workspaceId={workspaceId} brands={brands} onCreated={loadSidebar} />
            )}

            {tab === 'campaigns' && (
              <CampaignPanel
                workspaceId={workspaceId}
                campaigns={campaigns}
                brands={brands}
                onCreated={loadSidebar}
              />
            )}
          </aside>

          <section className="flex min-h-[60vh] flex-col rounded-xl border border-ink-600 bg-ink-800">
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.length === 0 && !sending ? (
                <Empty
                  title="Start a new conversation"
                  body="Describe the post you need — platform, angle, and audience."
                />
              ) : (
                messages.map((m) => <Bubble key={m.id} message={m} />)
              )}
              {sending && (
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" /> Generating…
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <form onSubmit={send} className="space-y-3 border-t border-ink-600 p-4">
              <ErrorBanner message={error} />
              <div className="flex flex-wrap gap-2">
                <select
                  className="input max-w-[160px]"
                  value={brandId}
                  onChange={(e) => setBrandId(e.target.value)}
                  aria-label="Brand voice"
                >
                  <option value="">No brand</option>
                  {brands.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
                <select
                  className="input max-w-[160px]"
                  value={campaignId}
                  onChange={(e) => setCampaignId(e.target.value)}
                  aria-label="Campaign"
                >
                  <option value="">No campaign</option>
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <input
                  className="input min-w-[200px] flex-1"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Write a LinkedIn post announcing our Series A…"
                  aria-label="Prompt"
                  disabled={sending}
                />
                <button
                  className="btn-primary"
                  disabled={sending || !prompt.trim()}
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </AppShell>
  );
}

function Bubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-3 text-sm leading-relaxed ${
          isUser ? 'bg-indigo-500 text-white' : 'border border-ink-600 bg-ink-900 text-slate-200'
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
