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

export interface ChatHistoryMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
}

export interface AgentCard {
  type: string;
  title: string;
  data: Record<string, unknown>;
}

export interface AgentChatResponse {
  answer: string;
  tools_executed: string[];
  cards: AgentCard[];
  model_used: string;
}

export interface TerritoryPulse {
  open_incidents: number;
  affected_students: number;
  critical_incidents: number;
  schools_tracked: number;
  schools_with_open: number;
}

export interface LibraryProject {
  id: number;
  name: string;
  conversations_count: number;
  created_at: string;
}

export interface LibraryMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  model: string | null;
  created_at: string;
}

export interface LibraryConversation {
  id: number;
  project_id: number | null;
  title: string;
  updated_at: string;
  messages: LibraryMessage[];
}

export interface LibraryPayload {
  projects: LibraryProject[];
  conversations: LibraryConversation[];
}

export interface MessagePayload {
  role: 'user' | 'assistant';
  content: string;
  tools: string[];
  cards: AgentCard[];
  model: string;
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
  converse: (message: string, history: ChatHistoryMessage[]) =>
    req<AgentChatResponse>('/v1/wash/agent/converse', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
    }),
  overview: () => req<TerritoryPulse>('/v1/wash/overview'),
  library: () => req<LibraryPayload>('/v1/wash/library'),
  createProject: (name: string) =>
    req<LibraryProject>('/v1/wash/projects', { method: 'POST', body: JSON.stringify({ name }) }),
  renameProject: (id: number, name: string) =>
    req<LibraryProject>(`/v1/wash/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),
  deleteProject: (id: number) =>
    req<{ message: string }>(`/v1/wash/projects/${id}`, { method: 'DELETE' }),
  createConversation: (p: { title: string; project_id: number | null; messages: MessagePayload[] }) =>
    req<LibraryConversation>('/v1/wash/conversations', { method: 'POST', body: JSON.stringify(p) }),
  replaceMessages: (id: number, messages: MessagePayload[]) =>
    req<LibraryConversation>(`/v1/wash/conversations/${id}/messages`, {
      method: 'PUT',
      body: JSON.stringify({ messages }),
    }),
  deleteConversation: (id: number) =>
    req<{ message: string }>(`/v1/wash/conversations/${id}`, { method: 'DELETE' }),
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
  schools: (params?: { district?: string; search?: string; page?: number }) =>
    req<Paginated<School>>(`/v1/wash/schools${qs(params ?? {})}`),
  school: (id: number) => req<School>(`/v1/wash/schools/${id}`),
  createSchool: (payload: SchoolPayload) =>
    req<{ message: string; school: School }>('/v1/wash/schools', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  incidents: (params?: {
    school_id?: number;
    status?: string;
    urgency?: string;
    district?: string;
    page?: number;
  }) => req<Paginated<Incident>>(`/v1/wash/incidents${qs(params ?? {})}`),
  incident: (id: number) => req<{ incident: Incident }>(`/v1/wash/incidents/${id}`),
  updateIncidentStatus: (id: number, status: string) =>
    req<{ message: string; incident: Incident }>(`/v1/wash/incidents/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  assignIncident: (id: number, user_id: number) =>
    req<{ message: string; incident: Incident }>(`/v1/wash/incidents/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ user_id }),
    }),
  overridePriority: (id: number, payload: { priority_score: number; urgency?: string }) =>
    req<{ message: string; incident: Incident }>(`/v1/wash/incidents/${id}/override-priority`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  storeMaintenanceLog: (id: number, payload: MaintenanceLogPayload) =>
    req<{ message: string; log: MaintenanceLog }>(`/v1/wash/incidents/${id}/maintenance-logs`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  assignableUsers: () => req<AssignableUser[]>('/v1/wash/assignable-users'),
  reports: (params?: { school_id?: number; incident_id?: number; page?: number }) =>
    req<Paginated<Report>>(`/v1/wash/reports${qs(params ?? {})}`),
  report: (id: number) => req<Report>(`/v1/wash/reports/${id}`),
  createReport: (payload: { school_id: number; message: string }) =>
    req<{ message: string; is_duplicate: boolean; report: Report; incident: Incident }>(
      '/v1/wash/reports',
      { method: 'POST', body: JSON.stringify({ ...payload, channel: 'text' }) },
    ),
  notifications: () => req<Paginated<AppNotification>>('/v1/notifications'),
  readNotification: (id: string) =>
    req<{ message: string }>(`/v1/notifications/${id}/read`, { method: 'POST' }),
  readAllNotifications: () =>
    req<{ message: string }>('/v1/notifications/read-all', { method: 'POST' }),
  aiAnalyses: (params?: { analysis_type?: string; incident_id?: number; page?: number }) =>
    req<Paginated<AiAnalysis>>(`/v1/admin/ai-analyses${qs(params ?? {})}`),
};

export interface Paginated<T> {
  data: T[];
  current_page: number;
  last_page: number;
  total: number;
}

export interface SchoolRef {
  id: number;
  name: string;
  district: string;
}

export interface MaintenanceLog {
  id: number;
  incident_id: number;
  school_id: number;
  cost_amount: number;
  currency: string | null;
  repaired_at: string | null;
  days_without_service: number | null;
  notes: string | null;
  performed_by: number | null;
  created_at: string;
}

export interface MaintenanceLogPayload {
  cost_amount: number;
  currency?: string;
  repaired_at?: string;
  days_without_service?: number;
  notes?: string;
}

export interface AiAnalysis {
  id: number;
  incident_id: number | null;
  report_id: number | null;
  analysis_type: string;
  input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null;
  model_used: string | null;
  confidence: number | null;
  processing_ms: number | null;
  created_at: string;
  incident?: { id: number; reference_code: string; title: string; school?: SchoolRef };
  report?: { id: number; school_id: number; channel: string; is_duplicate: boolean };
}

export interface Report {
  id: number;
  incident_id: number | null;
  school_id: number;
  reporter_id: number | null;
  channel: string;
  source: string | null;
  raw_content: string;
  audio_path: string | null;
  photo_path: string | null;
  is_duplicate: boolean;
  duplicate_of_incident_id: number | null;
  duplicate_similarity_score: number | null;
  raw_ai_extraction: Record<string, unknown> | null;
  created_at: string;
  school?: SchoolRef;
  incident?: { id: number; reference_code: string; title: string; urgency: string; status: string };
  ai_analyses?: AiAnalysis[];
}

export interface Incident {
  id: number;
  school_id: number;
  reference_code: string;
  title: string;
  category: string;
  issue_type: string | null;
  status: string;
  urgency: string;
  health_hazard: string | null;
  priority_score: number;
  affected_students: number;
  ai_summary: string | null;
  ai_tags: string[] | null;
  assigned_to_user_id: number | null;
  resolved_at: string | null;
  created_at: string;
  school?: SchoolRef;
  assignee?: { id: number; name: string } | null;
  reports_count?: number;
  reports?: Report[];
  ai_analyses?: AiAnalysis[];
  maintenance_logs?: MaintenanceLog[];
}

export interface School {
  id: number;
  name: string;
  code: string;
  district: string;
  default_language: string | null;
  latitude: number | null;
  longitude: number | null;
  student_count: number;
  female_students: number | null;
  teacher_count: number | null;
  broken_toilets: number | null;
  distance_from_center_km: number | null;
  equipment_type: string | null;
  installation_year: number | null;
  estimated_replacement_cost: number | null;
  contact_phone: string | null;
  open_incidents_count?: number;
  reports_count?: number;
  maintenance_logs_count?: number;
  open_incidents?: Incident[];
  maintenance_logs?: MaintenanceLog[];
}

export interface SchoolPayload {
  name: string;
  code: string;
  district: string;
  latitude?: number;
  longitude?: number;
  student_count?: number;
  female_students?: number;
  teacher_count?: number;
  distance_from_center_km?: number;
  equipment_type?: string;
  installation_year?: number;
  estimated_replacement_cost?: number;
  contact_phone?: string;
}

export interface AppNotification {
  id: string;
  type: string;
  data: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export interface AssignableUser {
  id: number;
  name: string;
}

function qs(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}
