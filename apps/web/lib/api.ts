/**
 * Typed API client.
 *
 * Handles token storage, automatic refresh on 401, and a single request
 * de-duplication point so a burst of components cannot each trigger their own
 * refresh round-trip.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://127.0.0.1:8000';
const API = `${API_URL}/api/v1`;

const ACCESS_KEY = 'socialai.access';
const REFRESH_KEY = 'socialai.refresh';

export type ApiErrorBody = { error: { code: string; message: string; details?: unknown } };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---- token storage ---------------------------------------------------

export const tokens = {
  get access() {
    return typeof window === 'undefined' ? null : localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return typeof window === 'undefined' ? null : localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

// ---- core request ----------------------------------------------------

let refreshInFlight: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  try {
    const res = await fetch(`${API}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      tokens.clear();
      return false;
    }
    const data = await res.json();
    tokens.set(data.access_token, data.refresh_token);
    return true;
  } catch {
    tokens.clear();
    return false;
  }
}

/** Collapses concurrent refreshes into one in-flight request. */
function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const access = tokens.access;
  if (access) headers.set('Authorization', `Bearer ${access}`);

  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Is the API running?');
  }

  if (res.status === 401 && retry && tokens.refresh) {
    if (await refreshOnce()) return request<T>(path, init, false);
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const body = text ? JSON.parse(text) : {};

  if (!res.ok) {
    const err = (body as ApiErrorBody).error;
    throw new ApiError(
      res.status,
      err?.code ?? 'unknown',
      err?.message ?? `Request failed (${res.status})`,
    );
  }
  return body as T;
}

// ---- types -----------------------------------------------------------

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  email_verified_at: string | null;
  created_at: string;
};
export type Workspace = {
  id: string;
  name: string;
  slug: string;
  owner_id: string;
  created_at: string;
  role: string | null;
};
export type Brand = {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  tone_of_voice: string;
  target_audience: string;
  created_at: string;
};
export type Campaign = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  name: string;
  objective: string;
  status: string;
  created_at: string;
};
export type Message = {
  id: string;
  role: string;
  content: string;
  model: string | null;
  created_at: string;
};
export type Conversation = {
  id: string;
  workspace_id: string;
  title: string;
  campaign_id: string | null;
  brand_id: string | null;
  created_at: string;
  updated_at: string;
};
export type ConversationDetail = Conversation & { messages: Message[] };
export type Paged<T> = { items: T[]; page: { total: number; limit: number; offset: number } };
export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

// ---- endpoints -------------------------------------------------------

export const api = {
  register: (email: string, password: string, full_name: string, workspace_name?: string) =>
    request<TokenPair>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name, workspace_name }),
    }),

  login: (email: string, password: string) =>
    request<TokenPair>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  logout: async () => {
    const refresh = tokens.refresh;
    if (refresh) {
      await request<void>('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refresh }),
      }).catch(() => undefined);
    }
    tokens.clear();
  },

  me: () => request<{ user: User; workspaces: Workspace[] }>('/auth/me'),

  requestVerification: (email: string) =>
    request<{ message: string }>('/auth/verify/request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  confirmVerification: (token: string) =>
    request<{ message: string }>('/auth/verify/confirm', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  forgotPassword: (email: string) =>
    request<{ message: string }>('/auth/password/forgot', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, new_password: string) =>
    request<{ message: string }>('/auth/password/reset', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    }),

  listWorkspaces: () => request<Workspace[]>('/workspaces'),
  createWorkspace: (name: string) =>
    request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify({ name }) }),

  listBrands: (ws: string) => request<Paged<Brand>>(`/workspaces/${ws}/brands`),
  createBrand: (ws: string, data: Partial<Brand> & { name: string }) =>
    request<Brand>(`/workspaces/${ws}/brands`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  listCampaigns: (ws: string) => request<Paged<Campaign>>(`/workspaces/${ws}/campaigns`),
  createCampaign: (ws: string, data: { name: string; objective?: string; brand_id?: string }) =>
    request<Campaign>(`/workspaces/${ws}/campaigns`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  listConversations: (ws: string) =>
    request<Paged<Conversation>>(`/workspaces/${ws}/chat/conversations`),
  getConversation: (ws: string, id: string) =>
    request<ConversationDetail>(`/workspaces/${ws}/chat/conversations/${id}`),
  sendMessage: (
    ws: string,
    body: { prompt: string; conversation_id?: string; brand_id?: string; campaign_id?: string },
  ) =>
    request<{ conversation_id: string; message: Message; provider: string }>(
      `/workspaces/${ws}/chat`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
};
