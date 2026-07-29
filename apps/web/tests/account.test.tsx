/**
 * Email verification and password reset, driven through the real pages
 * against a live backend on 127.0.0.1:8000.
 *
 * The backend runs the `console` email backend, which logs the message it
 * would have sent. The test scrapes the token out of that log, which is the
 * closest thing to "opening the email" available without an SMTP provider.
 */
import { readFileSync } from 'node:fs';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

const nav: string[] = [];
let search = new URLSearchParams();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (p: string) => nav.push(p),
    replace: (p: string) => nav.push(p),
    refresh: () => {},
  }),
  useSearchParams: () => search,
  usePathname: () => nav.at(-1) ?? '/',
}));
vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : '#'} {...rest}>
      {children}
    </a>
  ),
}));

import VerifyPage from '@/app/verify/page';
import ForgotPasswordPage from '@/app/forgot-password/page';
import ResetPasswordPage from '@/app/reset-password/page';
import LoginPage from '@/app/login/page';
import { AuthProvider } from '@/lib/auth';
import { API_URL } from '@/lib/api';

const API = `${API_URL}/api/v1`;

const SERVER_LOG = process.env.SERVER_LOG ?? '/tmp/rc1-server.log';
const stamp = Date.now();
const EMAIL = `account.${stamp}@example.com`;
const PASSWORD = 'Sup3rSecret-Passphrase!';
const NEW_PASSWORD = 'Ev3nBetter-Passphrase!';

const ui = (node: React.ReactNode) => render(<AuthProvider>{node}</AuthProvider>);

afterEach(() => {
  cleanup();
  search = new URLSearchParams();
});

/** Pull the newest token addressed to `to` out of the server log. */
function tokenFromLog(to: string): string {
  const log = readFileSync(SERVER_LOG, 'utf8');
  const blocks = log.split('EMAIL NOT SENT').filter((b) => b.includes(`To: ${to}`));
  const last = blocks.at(-1);
  if (!last) throw new Error(`no email logged for ${to}`);
  const found = [...last.matchAll(/token=([A-Za-z0-9_-]+)/g)].at(-1);
  if (!found) throw new Error(`no token in the email for ${to}`);
  return found[1];
}

async function api(path: string, body: unknown) {
  return fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

beforeAll(async () => {
  const health = await fetch(`${API_URL}/healthz`).catch(() => null);
  if (!health?.ok) throw new Error('backend is not running on 127.0.0.1:8000');
  const r = await api('/auth/register', {
    email: EMAIL,
    password: PASSWORD,
    full_name: 'Account Tester',
  });
  if (r.status !== 201) throw new Error(`register failed: ${r.status} ${await r.text()}`);
});

describe('email verification', () => {
  it('sends a link from the verify page and confirms it', async () => {
    const user = userEvent.setup();
    ui(<VerifyPage />);

    await user.type(screen.getByLabelText(/email/i), EMAIL);
    await user.click(screen.getByRole('button', { name: /send verification link/i }));
    await screen.findByRole('status');

    const token = tokenFromLog(EMAIL);
    cleanup();

    search = new URLSearchParams({ token });
    ui(<VerifyPage />);
    await waitFor(() => expect(screen.getByText(/email verified/i)).toBeTruthy());
  });

  it('shows a helpful message when the link is stale', async () => {
    search = new URLSearchParams({ token: 'not-a-real-token-value' });
    ui(<VerifyPage />);
    await waitFor(() => expect(screen.getByText(/link expired/i)).toBeTruthy());
    expect(screen.getByRole('alert').textContent).toMatch(/no longer valid/i);
  });

  it('offers a resend form when opened with no token', async () => {
    ui(<VerifyPage />);
    expect(screen.getByRole('button', { name: /send verification link/i })).toBeTruthy();
  });
});

describe('password reset', () => {
  it('does not reveal whether an address has an account', async () => {
    const user = userEvent.setup();
    ui(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText(/email/i), `ghost.${stamp}@example.com`);
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    const banner = await screen.findByRole('status');
    expect(banner.textContent).toMatch(/if that address has an account/i);
  });

  it('walks the whole flow and leaves the new password working', async () => {
    const user = userEvent.setup();
    ui(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText(/email/i), EMAIL);
    await user.click(screen.getByRole('button', { name: /send reset link/i }));
    await screen.findByRole('status');

    const token = tokenFromLog(EMAIL);
    cleanup();

    search = new URLSearchParams({ token });
    ui(<ResetPasswordPage />);
    await user.type(screen.getByLabelText(/^new password$/i), NEW_PASSWORD);
    await user.type(screen.getByLabelText(/confirm new password/i), NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /update password/i }));

    await waitFor(() => expect(screen.getByText(/password updated/i)).toBeTruthy());

    const old = await api('/auth/login', { email: EMAIL, password: PASSWORD });
    expect(old.status).toBe(401);
    const fresh = await api('/auth/login', { email: EMAIL, password: NEW_PASSWORD });
    expect(fresh.status).toBe(200);
  });

  it('refuses mismatched passwords before calling the API', async () => {
    const user = userEvent.setup();
    search = new URLSearchParams({ token: 'irrelevant' });
    ui(<ResetPasswordPage />);
    await user.type(screen.getByLabelText(/^new password$/i), NEW_PASSWORD);
    await user.type(screen.getByLabelText(/confirm new password/i), `${NEW_PASSWORD}x`);
    await user.click(screen.getByRole('button', { name: /update password/i }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/do not match/i);
  });

  it('explains itself when the token is missing entirely', async () => {
    ui(<ResetPasswordPage />);
    expect(screen.getByText(/reset link missing/i)).toBeTruthy();
  });

  it('rejects a reused reset link', async () => {
    const user = userEvent.setup();
    ui(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText(/email/i), EMAIL);
    await user.click(screen.getByRole('button', { name: /send reset link/i }));
    await screen.findByRole('status');
    const token = tokenFromLog(EMAIL);
    cleanup();

    // Burn it once.
    const first = await api('/auth/password/reset', { token, new_password: NEW_PASSWORD });
    expect(first.status).toBe(200);

    search = new URLSearchParams({ token });
    ui(<ResetPasswordPage />);
    await user.type(screen.getByLabelText(/^new password$/i), NEW_PASSWORD);
    await user.type(screen.getByLabelText(/confirm new password/i), NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /update password/i }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/no longer valid/i);
  });
});

describe('login page', () => {
  it('links to the reset flow', () => {
    ui(<LoginPage />);
    const link = screen.getByRole('link', { name: /forgot password/i });
    expect(link.getAttribute('href')).toBe('/forgot-password');
  });
});
