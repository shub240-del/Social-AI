import Link from 'next/link';
import { ArrowRight, MessageSquare, Palette, Shield, Sparkles, Users } from 'lucide-react';

const FEATURES = [
  {
    icon: Palette,
    title: 'Brand voice',
    body: 'Describe your tone, audience and keywords once. Every generation is conditioned on it.',
  },
  {
    icon: MessageSquare,
    title: 'Conversations that persist',
    body: 'Full history per workspace. Close the tab, log back in, pick up exactly where you left off.',
  },
  {
    icon: Users,
    title: 'Workspaces and roles',
    body: 'Invite your team with owner, admin, editor, member or viewer permissions.',
  },
  {
    icon: Shield,
    title: 'Isolated by default',
    body: 'Every resource lives inside a workspace and is unreachable from any other tenant.',
  },
];

export default function HomePage() {
  return (
    <main className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <span className="flex items-center gap-2 text-lg font-semibold text-white">
          <Sparkles className="h-5 w-5 text-indigo-400" /> Social AI
        </span>
        <nav className="flex items-center gap-3">
          <Link href="/login" className="btn-ghost">
            Log in
          </Link>
          <Link href="/register" className="btn-primary">
            Get started
          </Link>
        </nav>
      </header>

      <section className="mx-auto max-w-4xl px-6 pb-16 pt-16 text-center sm:pt-24">
        <p className="mono mb-4 inline-block rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-300">
          Powered by NVIDIA NIM · Llama 3.1 70B
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-white sm:text-6xl">
          Social content that
          <span className="bg-gradient-to-r from-indigo-400 to-sky-400 bg-clip-text text-transparent">
            {' '}
            sounds like you
          </span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-400">
          Social AI writes posts, captions and campaign copy in your brand voice — with your team,
          your history and your data kept in your own workspace.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <Link href="/register" className="btn-primary px-6 py-3 text-base">
            Create a free account <ArrowRight className="h-4 w-4" />
          </Link>
          <Link href="/login" className="btn-ghost px-6 py-3 text-base">
            I already have one
          </Link>
        </div>
      </section>

      <section className="mx-auto grid max-w-5xl gap-4 px-6 pb-24 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="card">
            <Icon className="h-6 w-6 text-indigo-400" />
            <h2 className="mt-3 font-semibold text-white">{title}</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{body}</p>
          </div>
        ))}
      </section>

      <footer className="border-t border-slate-800 py-8 text-center text-sm text-slate-500">
        Social AI · Built for teams that publish every day
      </footer>
    </main>
  );
}
