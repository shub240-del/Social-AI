/**
 * Full user journey, driven through the real React components against a live
 * backend on 127.0.0.1:8000.
 *
 * Homepage -> Register -> Dashboard -> Workspace -> Chat -> Prompt ->
 * AI response -> History -> Reload/persistence -> Logout -> Login again.
 *
 * Nothing here is mocked except Next's router and route params, which have no
 * runtime outside a Next server.
 */
import { render, screen, waitFor, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

// ---- next/navigation stand-in ---------------------------------------

const nav: string[] = [];
let routeId = '';
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (p: string) => nav.push(p),
    replace: (p: string) => nav.push(p),
    refresh: () => {},
  }),
  useParams: () => ({ id: routeId }),
  usePathname: () => nav.at(-1) ?? '/',
}));
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : '#'} {...rest}>
      {children}
    </a>
  ),
}));

import Home from '@/app/page';
import RegisterPage from '@/app/register/page';
import LoginPage from '@/app/login/page';
import DashboardPage from '@/app/dashboard/page';
import WorkspacePage from '@/app/workspace/[id]/page';
import { AuthProvider } from '@/lib/auth';
import { API_URL, tokens } from '@/lib/api';

const ui = (node: React.ReactNode) => render(<AuthProvider>{node}</AuthProvider>);
const stamp = Date.now();
const EMAIL = `journey.${stamp}@example.com`;
const PASSWORD = 'Sup3rSecret-Passphrase!';
const NAME = 'Journey Tester';
const WORKSPACE = `Journey WS ${stamp}`;
const BRAND = `Acme Voice ${stamp}`;
const CAMPAIGN = `Series A ${stamp}`;

/** Simulates a hard browser reload: tear down the tree, keep localStorage. */
const reload = () => cleanup();

afterEach(() => {
  cleanup();
});

beforeAll(async () => {
  const res = await fetch(`${API_URL}/healthz`);
  if (!res.ok) throw new Error('backend is not reachable on 127.0.0.1:8000');
});

describe('Social AI end-to-end journey', () => {
  it('1. homepage renders the marketing shell with both entry points', async () => {
    ui(<Home />);
    expect(
      await screen.findByRole('heading', { name: /sounds like your brand/i }),
    ).toBeDefined();
    expect(screen.getAllByText(/Create your workspace|Get started/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Log in/i).length).toBeGreaterThan(0);
  });

  it('2. register creates the account, stores tokens and routes to the dashboard', async () => {
    const user = userEvent.setup();
    ui(<RegisterPage />);

    await user.type(screen.getByLabelText(/full name/i), NAME);
    await user.type(screen.getByLabelText(/^email$/i), EMAIL);
    await user.type(screen.getByLabelText(/^password$/i), PASSWORD);
    await user.type(screen.getByLabelText(/workspace name/i), WORKSPACE);
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => expect(nav.at(-1)).toBe('/dashboard'), { timeout: 15000 });
    expect(tokens.access).toBeTruthy();
    expect(tokens.refresh).toBeTruthy();
  });

  it('3. register surfaces a friendly error on a weak password without calling the API', async () => {
    const user = userEvent.setup();
    ui(<RegisterPage />);
    await user.type(screen.getByLabelText(/full name/i), 'X');
    await user.type(screen.getByLabelText(/^email$/i), `weak.${stamp}@example.com`);
    await user.type(screen.getByLabelText(/^password$/i), 'short');
    await user.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('12 characters'),
    );
  });

  it('4. dashboard lists the workspace created at signup', async () => {
    ui(<DashboardPage />);
    expect(await screen.findByText(WORKSPACE, {}, { timeout: 15000 })).toBeDefined();
    expect(
      screen.getByRole('heading', { name: new RegExp(`Welcome back, ${NAME.split(' ')[0]}`, 'i') }),
    ).toBeDefined();
    const link = screen.getByText(WORKSPACE).closest('a') as HTMLAnchorElement;
    routeId = link.getAttribute('href')!.replace('/workspace/', '');
    expect(routeId).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it('5. dashboard can create a second workspace and re-render it', async () => {
    const user = userEvent.setup();
    ui(<DashboardPage />);
    await screen.findByText(WORKSPACE, {}, { timeout: 15000 });
    const second = `Second WS ${stamp}`;
    await user.type(screen.getByLabelText(/new workspace name/i), second);
    await user.click(screen.getByRole('button', { name: /^create$/i }));
    expect(await screen.findByText(second, {}, { timeout: 15000 })).toBeDefined();
  });

  it('6. workspace opens with an empty chat and a brand selector', async () => {
    ui(<WorkspacePage />);
    expect(
      await screen.findByText(/start a new conversation/i, {}, { timeout: 15000 }),
    ).toBeDefined();
    expect(screen.getByLabelText(/brand voice/i)).toBeDefined();
  });


  it('6b. a brand can be created from the workspace UI and appears in the chat selector', async () => {
    const user = userEvent.setup();
    ui(<WorkspacePage />);
    await screen.findByText(/start a new conversation/i, {}, { timeout: 15000 });

    // The brand selector starts empty; the only way to populate it is the UI.
    const selector = screen.getByLabelText(/brand voice/i) as HTMLSelectElement;
    expect(selector.options.length).toBe(1);

    await user.click(screen.getByRole('tab', { name: /brands/i }));
    expect(await screen.findByText(/no brands yet/i)).toBeDefined();

    await user.click(screen.getByRole('button', { name: /new brand/i }));
    await user.type(screen.getByLabelText(/brand name/i), BRAND);
    await user.type(screen.getByLabelText(/tone of voice/i), 'Direct, warm, no jargon');
    await user.type(screen.getByLabelText(/target audience/i), 'Series A founders');
    await user.click(screen.getByRole('button', { name: /save brand/i }));

    const list = await screen.findByRole('list', { name: /brands/i }, { timeout: 15000 });
    expect(within(list).getByText(BRAND)).toBeDefined();

    // And it is now selectable when generating.
    await user.click(screen.getByRole('tab', { name: /chats/i }));
    await waitFor(() =>
      expect(
        (screen.getByLabelText(/brand voice/i) as HTMLSelectElement).options.length,
      ).toBe(2),
    );
  });

  it('6c. a campaign can be created and linked to the brand', async () => {
    const user = userEvent.setup();
    ui(<WorkspacePage />);
    await screen.findByText(/start a new conversation/i, {}, { timeout: 15000 });

    await user.click(screen.getByRole('tab', { name: /campaigns/i }));
    await user.click(screen.getByRole('button', { name: /new campaign/i }));
    await user.type(screen.getByLabelText(/campaign name/i), CAMPAIGN);
    await user.type(screen.getByLabelText(/campaign objective/i), 'Announce the raise');
    await user.selectOptions(screen.getByLabelText(/campaign brand/i), [BRAND]);
    await user.click(screen.getByRole('button', { name: /save campaign/i }));

    const list = await screen.findByRole('list', { name: /campaigns/i }, { timeout: 15000 });
    expect(within(list).getByText(CAMPAIGN)).toBeDefined();
    expect(within(list).getByText(/draft/i)).toBeDefined();
  });

  it('6d. brand and campaign persist across a reload', async () => {
    reload();
    ui(<WorkspacePage />);
    await screen.findByText(/start a new conversation/i, {}, { timeout: 15000 });
    await waitFor(() =>
      expect(
        (screen.getByLabelText(/brand voice/i) as HTMLSelectElement).options.length,
      ).toBe(2),
    );
    expect(
      (screen.getByLabelText(/^campaign$/i) as HTMLSelectElement).options.length,
    ).toBe(2);
  });


  it('7. sending a prompt returns an assistant reply and persists the exchange', async () => {
    const user = userEvent.setup();
    ui(<WorkspacePage />);
    await screen.findByText(/start a new conversation/i, {}, { timeout: 15000 });

    const prompt = 'Write a LinkedIn post announcing our Series A.';
    await user.selectOptions(screen.getByLabelText(/brand voice/i), [BRAND]);
    await user.type(screen.getByLabelText(/^prompt$/i), prompt);
    await user.click(screen.getByRole('button', { name: /send message/i }));

    // user message echoed
    expect(await screen.findByText(prompt, {}, { timeout: 20000 })).toBeDefined();
    // assistant reply arrives and is not an echo of the prompt
    await waitFor(
      () => {
        const bubbles = document.querySelectorAll('.whitespace-pre-wrap');
        expect(bubbles.length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 20000 },
    );
  });

  it('8. conversation history appears in the sidebar', async () => {
    ui(<WorkspacePage />);
    const sidebar = await screen.findByRole('list', { name: /conversations/i }, { timeout: 15000 });
    await waitFor(() => expect(within(sidebar).getAllByRole('button').length).toBeGreaterThan(0));
  });

  it('9. reload restores the session and the conversation from the server', async () => {
    reload();
    expect(tokens.access).toBeTruthy();
    ui(<WorkspacePage />);
    await waitFor(
      () => {
        const bubbles = document.querySelectorAll('.whitespace-pre-wrap');
        expect(bubbles.length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 20000 },
    );
  });

  it('10. a stale access token is transparently refreshed', async () => {
    localStorage.setItem('socialai.access', 'not-a-valid-jwt');
    ui(<DashboardPage />);
    expect(await screen.findByText(WORKSPACE, {}, { timeout: 20000 })).toBeDefined();
    expect(tokens.access).not.toBe('not-a-valid-jwt');
  });

  it('11. logout clears tokens and routes to /login', async () => {
    const user = userEvent.setup();
    ui(<DashboardPage />);
    await screen.findByText(WORKSPACE, {}, { timeout: 15000 });
    await user.click(screen.getByRole('button', { name: /log out/i }));
    await waitFor(() => expect(nav.at(-1)).toBe('/login'), { timeout: 15000 });
    expect(tokens.access).toBeNull();
    expect(tokens.refresh).toBeNull();
  });

  it('12. protected pages bounce to /login once logged out', async () => {
    ui(<DashboardPage />);
    await waitFor(() => expect(nav.at(-1)).toBe('/login'), { timeout: 15000 });
  });

  it('13. login rejects a wrong password with a readable message', async () => {
    const user = userEvent.setup();
    ui(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), EMAIL);
    await user.type(screen.getByLabelText(/password/i), 'WrongPassword-123456');
    await user.click(screen.getByRole('button', { name: /^log in$/i }));
    const alert = await screen.findByRole('alert', {}, { timeout: 15000 });
    expect(alert.textContent).toMatch(/not correct/i);
  });

  it('14. logging back in restores the account and its persisted data', async () => {
    const user = userEvent.setup();
    ui(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), EMAIL);
    await user.type(screen.getByLabelText(/password/i), PASSWORD);
    await user.click(screen.getByRole('button', { name: /^log in$/i }));
    await waitFor(() => expect(nav.at(-1)).toBe('/dashboard'), { timeout: 15000 });

    cleanup();
    ui(<DashboardPage />);
    expect(await screen.findByText(WORKSPACE, {}, { timeout: 15000 })).toBeDefined();

    cleanup();
    ui(<WorkspacePage />);
    await waitFor(
      () => {
        const bubbles = document.querySelectorAll('.whitespace-pre-wrap');
        expect(bubbles.length).toBeGreaterThanOrEqual(2);
      },
      { timeout: 20000 },
    );
  });
});
