'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Sparkles, Layers, Shield, MessageSquare } from 'lucide-react';
import { useAuth } from '@/lib/auth';

const FEATURES = [
  {
    icon: Sparkles,
    title: 'On-brand generation',
    body: 'Every prompt is grounded in the brand voice and audience you define, so drafts land in your tone.',
  },
  {
    icon: Layers,
    title: 'Workspaces & campaigns',
    body: 'Separate clients and initiatives. Members, brands and conversations stay scoped to their workspace.',
  },
  {
    icon: MessageSquare,
    title: 'Persistent chat',
    body: 'Conversations are stored server-side, so history survives reloads and follows you between devices.',
  },
  {
    icon: Shield,
    title: 'Tenant isolation',
    body: 'Role-based access with fail-closed checks. Cross-tenant reads return 404, never a leak.',
  },
];

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace('/dashboard');
  }, [loading, user, router]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <nav className="mb-20 flex items-center justify-between">
        <span className="flex items-center gap-2 text-lg font-semibold text-white">
          <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
        </span>
        <div className="flex gap-3">
          <Link href="/login" className="btn-ghost">
            Log in
          </Link>
          <Link href="/register" className="btn-primary">
            Get started
          </Link>
        </div>
      </nav>

      <section className="mb-20">
        <h1 className="max-w-3xl text-5xl font-semibold leading-tight text-white">
          Social content that actually sounds like your brand.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-400">
          Social AI turns a one-line brief into ready-to-post copy — grounded in your brand voice,
          organised by campaign, and kept in one shared workspace with your team.
        </p>
        <div className="mt-8 flex gap-3">
          <Link href="/register" className="btn-primary px-6 py-3 text-base">
            Create your workspace
          </Link>
          <Link href="/login" className="btn-ghost px-6 py-3 text-base">
            I already have an account
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="card">
            <Icon className="mb-3 h-5 w-5 text-indigo-400" />
            <h2 className="mb-1.5 font-medium text-white">{title}</h2>
            <p className="text-sm leading-relaxed text-slate-400">{body}</p>
          </div>
        ))}
      </section>

      <footer className="mt-20 border-t border-ink-600 pt-6 text-sm text-slate-500">
        Social AI — FastAPI + Next.js. Built for teams that ship every day.
      </footer>
    </main>
  );
}
