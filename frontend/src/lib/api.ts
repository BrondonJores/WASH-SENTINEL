export interface ProviderField {
  name: string;
  label: string;
  type: string;
  default: string;
  required: boolean;
}

export interface ProviderType {
  id: string;
  label: string;
  description: string;
  api_key_required: boolean;
  fields: ProviderField[];
}

export interface ModelProfile {
  id: number;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  vision_model: string | null;
  embed_model: string | null;
  timeout: number;
  is_active: boolean;
  is_default: boolean;
  last_tested_at: string | null;
  last_test_status: string | null;
  last_test_latency_ms: number | null;
  api_key_masked: string | null;
}

export interface SttProfile {
  id: number;
  name: string;
  driver: string;
  base_url: string | null;
  model: string | null;
  tokens_path: string | null;
  default_language: string;
  threads: number;
  timeout: number;
  is_active: boolean;
  is_default: boolean;
  last_tested_at: string | null;
  last_test_status: string | null;
  last_test_latency_ms: number | null;
  api_key_masked: string | null;
}

export interface LlmTestResult {
  ok: boolean;
  latency_ms: number;
  sample: string;
  error: string | null;
  provider: string;
  model: string;
}

export interface SttTestResult {
  ok: boolean;
  latency_ms: number;
  transcript: string;
  error: string | null;
  driver: string;
  language: string;
}

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  roles: string[];
}

export interface ProfilePayload {
  name: string;
  provider?: string;
  driver?: string;
  base_url?: string;
  model?: string;
  vision_model?: string;
  embed_model?: string;
  tokens_path?: string;
  api_key?: string;
  default_language?: string;
  threads?: number;
  timeout?: number;
}

const baseUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost/api';

let token: string | null = localStorage.getItem('wash_admin_token');
let unauthorizedHandler: (() => void) | null = null;

export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  unauthorizedHandler = fn;
};
export const getToken = () => token;

export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem('wash_admin_token', t);
  else localStorage.removeItem('wash_admin_token');
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response, fallback: string): Promise<never> {
  const body = (await res.json().catch(() => ({}))) as { message?: string; errors?: Record<string, string[]> };
  const first = body.errors ? Object.values(body.errors)[0]?.[0] : undefined;
  throw new ApiError(res.status, first ?? body.message ?? fallback);
}

function handle401(): never {
  setToken(null);
  unauthorizedHandler?.();
  throw new ApiError(401, 'Session expirée, reconnectez-vous.');
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) handle401();
  if (!res.ok) await parseError(res, `Erreur ${res.status}`);
  return (await res.json()) as T;
}

async function reqMultipart<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
  });
  if (res.status === 401) handle401();
  if (!res.ok) await parseError(res, `Erreur ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  login: (email: string, password: string) =>
    req<{ token: string; user: AuthUser }>('/v1/auth/token', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  logout: () => req<{ message: string }>('/v1/auth/token', { method: 'DELETE' }),
  providerTypes: () => req<{ providers: ProviderType[] }>('/v1/admin/provider-types'),
  modelProfiles: () => req<ModelProfile[]>('/v1/admin/model-profiles'),
  createModelProfile: (p: ProfilePayload) =>
    req<{ profile: ModelProfile }>('/v1/admin/model-profiles', { method: 'POST', body: JSON.stringify(p) }),
  updateModelProfile: (id: number, p: Partial<ProfilePayload>) =>
    req<{ profile: ModelProfile }>(`/v1/admin/model-profiles/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  deleteModelProfile: (id: number) =>
    req<{ message: string }>(`/v1/admin/model-profiles/${id}`, { method: 'DELETE' }),
  activateModelProfile: (id: number) =>
    req<{ profile: ModelProfile }>(`/v1/admin/model-profiles/${id}/activate`, { method: 'POST' }),
  testModelProfile: (id: number) =>
    req<LlmTestResult>(`/v1/admin/model-profiles/${id}/test`, { method: 'POST' }),
  sttTypes: () => req<{ drivers: ProviderType[] }>('/v1/admin/stt-types'),
  sttProfiles: () => req<SttProfile[]>('/v1/admin/stt-profiles'),
  createSttProfile: (p: ProfilePayload) =>
    req<{ profile: SttProfile }>('/v1/admin/stt-profiles', { method: 'POST', body: JSON.stringify(p) }),
  updateSttProfile: (id: number, p: Partial<ProfilePayload>) =>
    req<{ profile: SttProfile }>(`/v1/admin/stt-profiles/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  deleteSttProfile: (id: number) =>
    req<{ message: string }>(`/v1/admin/stt-profiles/${id}`, { method: 'DELETE' }),
  activateSttProfile: (id: number) =>
    req<{ profile: SttProfile }>(`/v1/admin/stt-profiles/${id}/activate`, { method: 'POST' }),
  testSttProfile: (id: number, audio: File, language?: string) => {
    const form = new FormData();
    form.append('audio', audio);
    if (language) form.append('language', language);
    return reqMultipart<SttTestResult>(`/v1/admin/stt-profiles/${id}/test`, form);
  },
};
