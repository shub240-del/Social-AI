/**
 * Typed API client.
 *
 * Access tokens are short-lived and kept in memory + localStorage; on a 401 the
 * client transparently refreshes once and replays the original request. Every
 * concurrent 401 shares a single in-flight refresh, because five parallel
 * dashboard requests must not rotate the refresh token five times — with
 * rotation enabled that would trip the server's replay detection and log the
 * user out.
 */

const RAW_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';
export const API_BASE = RAW_BASE.replace(/\/$/, '');
const V1 = `${API_BASE}/api/v1`;

const ACCESS_KEY = 'socialai.access';
const REFRESH_KEY = 'socialai.refresh';

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// ---- token storage ---------------------------------------------------

export const tokens = {
  get access(): string | null {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem(ACCESS_KEY);
  },
  get refresh(): string | null {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(ACCESS_KEY, access);
    window.localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem(ACCESS_KEY);
    window.localStorage.removeItem(REFRESH_KEY);
  },
};

// ---- types -----------------------------------------------------------

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  email_verified_at: string | null;
  workspaces: WorkspaceSummary[];
  permissions: string[];
}

export interface Brand {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  tone: string;
  audience: string;
  keywords: string;
}

export interface Campaign {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  name: string;
  objective: string;
  status: string;
  channel: string;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  sequence: number;
  model?: string | null;
  created_at?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  campaign_id: string | null;
  message_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface ChatResult {
  conversation_id: string;
  message: ChatMessage;
  model: string;
  provider: string;
  latency_ms: number;
  total_tokens: number;
}

// ---- core request ------------------------------------------------------

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  retryOn401?: boolean;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;

  // Collapse concurrent refreshes into one request.
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${V1}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!response.ok) {
          tokens.clear();
          return false;
        }
        const data = (await response.json()) as TokenPair;
        tokens.set(data.access_token, data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        // Cleared on the next tick so callers awaiting this promise all see it.
        setTimeout(() => {
          refreshInFlight = null;
        }, 0);
      }
    })();
  }
  return refreshInFlight;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, retryOn401 = true } = options;

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = tokens.access;
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${V1}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.');
  }

  if (response.status === 401 && auth && retryOn401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request<T>(path, { ...options, retryOn401: false });
    }
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string; details?: unknown } };
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? 'http_error',
      envelope?.error?.message ?? `Request failed (${response.status}).`,
      envelope?.error?.details,
    );
  }

  return payload as T;
}

// ---- public surface ------------------------------------------------------

export const api = {
  // auth
  async register(email: string, password: string, fullName: string) {
    const data = await request<TokenPair & { user: { id: string; email: string } }>(
      '/auth/register',
      { method: 'POST', auth: false, body: { email, password, full_name: fullName } },
    );
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async login(email: string, password: string) {
    const data = await request<TokenPair>('/auth/login', {
      method: 'POST',
      auth: false,
      body: { email, password },
    });
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async logout() {
    try {
      await request('/auth/logout', {
        method: 'POST',
        body: { refresh_token: tokens.refresh },
      });
    } finally {
      // Local state is cleared even if the server call fails, otherwise a
      // network blip leaves the user apparently signed in.
      tokens.clear();
    }
  },

  me: () => request<Me>('/auth/me'),

  // account
  requestVerification: (email: string) =>
    request<{ message: string }>('/auth/verify/request', {
      method: 'POST',
      auth: false,
      body: { email },
    }),

  confirmVerification: (token: string) =>
    request<{ message: string }>('/auth/verify/confirm', {
      method: 'POST',
      auth: false,
      body: { token },
    }),

  forgotPassword: (email: string) =>
    request<{ message: string }>('/auth/password/forgot', {
      method: 'POST',
      auth: false,
      body: { email },
    }),

  resetPassword: (token: string, newPassword: string) =>
    request<{ message: string }>('/auth/password/reset', {
      method: 'POST',
      auth: false,
      body: { token, new_password: newPassword },
    }),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ message: string }>('/auth/password/change', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  // workspaces
  listWorkspaces: () => request<(WorkspaceSummary & { description: string })[]>('/workspaces'),

  createWorkspace: (name: string, description = '') =>
    request<WorkspaceSummary>('/workspaces', { method: 'POST', body: { name, description } }),

  workspaceStats: (workspaceId: string) =>
    request<{ brands: number; campaigns: number; members: number }>(
      `/workspaces/${workspaceId}/stats`,
    ),

  // brands
  listBrands: (workspaceId: string) => request<Brand[]>(`/workspaces/${workspaceId}/brands`),

  createBrand: (workspaceId: string, body: Partial<Brand> & { name: string }) =>
    request<Brand>(`/workspaces/${workspaceId}/brands`, { method: 'POST', body }),

  // campaigns
  listCampaigns: (workspaceId: string) =>
    request<Campaign[]>(`/workspaces/${workspaceId}/campaigns`),

  // brand_id and channel are accepted by CampaignCreate on the server; the
  // client used to omit them, so a campaign could never be linked to a brand.
  createCampaign: (
    workspaceId: string,
    body: { name: string; objective?: string; channel?: string; brand_id?: string },
  ) => request<Campaign>(`/workspaces/${workspaceId}/campaigns`, { method: 'POST', body }),

  // chat
  chat: (
    workspaceId: string,
    body: { prompt: string; conversation_id?: string; brand_id?: string; campaign_id?: string },
  ) => request<ChatResult>(`/workspaces/${workspaceId}/chat`, { method: 'POST', body }),

  listConversations: (workspaceId: string) =>
    request<Conversation[]>(`/workspaces/${workspaceId}/chat/conversations`),

  getConversation: (workspaceId: string, conversationId: string) =>
    request<ConversationDetail>(`/workspaces/${workspaceId}/chat/conversations/${conversationId}`),

  deleteConversation: (workspaceId: string, conversationId: string) =>
    request<{ message: string }>(
      `/workspaces/${workspaceId}/chat/conversations/${conversationId}`,
      { method: 'DELETE' },
    ),
};

export function isAuthenticated(): boolean {
  return Boolean(tokens.access);
}
