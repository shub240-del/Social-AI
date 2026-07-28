'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Loader2, MessageSquarePlus, Send, Sparkles, Trash2 } from 'lucide-react';
import { EmptyState, ErrorBanner, Spinner } from '@/components/Field';
import {
  api,
  ApiError,
  type Brand,
  type ChatMessage,
  type Conversation,
} from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const workspaceId = params.id;
  const { user, loading } = useAuth();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandId, setBrandId] = useState<string>('');
  const [prompt, setPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  const loadSidebar = useCallback(async () => {
    try {
      const [convos, brandList] = await Promise.all([
        api.listConversations(workspaceId),
        api.listBrands(workspaceId),
      ]);
      setConversations(convos);
      setBrands(brandList);
      if (brandList.length && !brandId) setBrandId(brandList[0].id);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? 'That workspace does not exist, or you no longer have access to it.'
          : 'We could not load this workspace.',
      );
    }
  }, [workspaceId, brandId]);

  useEffect(() => {
    if (user) void loadSidebar();
    // loadSidebar changes with brandId; only re-run on workspace/user change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, workspaceId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function openConversation(id: string) {
    setActiveId(id);
    setHistoryLoading(true);
    setError(null);
    try {
      const detail = await api.getConversation(workspaceId, id);
      setMessages(detail.messages);
    } catch {
      setError('We could not load that conversation.');
    } finally {
      setHistoryLoading(false);
    }
  }

  function startNew() {
    setActiveId(null);
    setMessages([]);
    setError(null);
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = prompt.trim();
    if (!text || sending) return;

    setError(null);
    setSending(true);
    setPrompt('');

    // Optimistic echo so the interface responds immediately; the id is
    // replaced when the server answers.
    const optimistic: ChatMessage = {
      id: `pending-${Date.now()}`,
      role: 'user',
      content: text,
      sequence: messages.length,
    };
    setMessages((prev) => [...prev, optimistic]);

    try {
      const result = await api.chat(workspaceId, {
        prompt: text,
        conversation_id: activeId ?? undefined,
        brand_id: brandId || undefined,
      });
      setActiveId(result.conversation_id);
      setMessages((prev) => [...prev, result.message]);
      await loadSidebar();
    } catch (err) {
      // Roll the optimistic message back so the transcript matches the server.
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setPrompt(text);
      if (err instanceof ApiError && err.status === 403) {
        setError('Your role in this workspace does not allow sending messages.');
      } else if (err instanceof ApiError && err.status === 429) {
        setError('Too many requests. Please wait a moment.');
      } else if (err instanceof ApiError && err.status >= 502) {
        setError('The AI provider is unavailable right now. Please try again.');
      } else {
        setError('We could not send that message.');
      }
    } finally {
      setSending(false);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteConversation(workspaceId, id);
      if (activeId === id) startNew();
      await loadSidebar();
    } catch {
      setError('We could not delete that conversation.');
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading workspace" />
      </main>
    );
  }
  if (!user) return null;

  return (
    <main className="flex h-screen flex-col">
      <header className="border-b border-slate-800">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <Link href="/dashboard" className="btn-ghost px-2 py-1" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <span className="flex items-center gap-2 font-semibold text-white">
              <Sparkles className="h-4 w-4 text-indigo-400" /> Workspace
            </span>
          </div>
          {brands.length > 0 && (
            <div className="flex items-center gap-2">
              <label htmlFor="brand" className="text-xs text-slate-500">
                Brand voice
              </label>
              <select
                id="brand"
                className="input w-auto py-1.5 text-xs"
                value={brandId}
                onChange={(e) => setBrandId(e.target.value)}
              >
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-800 md:flex">
          <div className="p-3">
            <button onClick={startNew} className="btn-primary w-full">
              <MessageSquarePlus className="h-4 w-4" /> New conversation
            </button>
          </div>
          <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`group mb-1 flex items-center gap-1 rounded-lg px-2 py-2 text-sm transition ${
                  activeId === c.id ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-900'
                }`}
              >
                <button onClick={() => void openConversation(c.id)} className="min-w-0 flex-1 truncate text-left">
                  {c.title}
                  <span className="ml-1 text-[11px] text-slate-600">({c.message_count})</span>
                </button>
                <button
                  onClick={() => void remove(c.id)}
                  aria-label={`Delete ${c.title}`}
                  className="opacity-0 transition group-hover:opacity-100 hover:text-red-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {conversations.length === 0 && (
              <p className="px-2 py-6 text-center text-xs text-slate-600">No conversations yet.</p>
            )}
          </nav>
        </aside>

        <section className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
            <div className="mx-auto max-w-3xl space-y-4">
              {error && <ErrorBanner message={error} />}
              {historyLoading && <Spinner label="Loading conversation" />}

              {!historyLoading && messages.length === 0 && (
                <EmptyState
                  title="Start a conversation"
                  body="Ask for a launch tweet, a LinkedIn post, or a week of captions."
                />
              )}

              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      m.role === 'user'
                        ? 'bg-indigo-600 text-white'
                        : 'border border-slate-800 bg-slate-900 text-slate-200'
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))}

              {sending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
                    <Spinner label="Writing" />
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>

          <form onSubmit={send} className="border-t border-slate-800 p-4">
            <div className="mx-auto flex max-w-3xl items-end gap-2">
              <textarea
                className="input min-h-[52px] resize-y"
                rows={1}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void send(e as unknown as React.FormEvent);
                  }
                }}
                placeholder="Write a launch tweet for our new espresso blend…"
                aria-label="Your message"
                disabled={sending}
              />
              <button type="submit" className="btn-primary h-[52px]" disabled={sending || !prompt.trim()}>
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                <span className="hidden sm:inline">Send</span>
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
