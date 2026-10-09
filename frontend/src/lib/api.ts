// API client — thin typed wrapper over the Imperial Court REST contract.
// Contract source: docs/api-contract.md (backend/imperial/api/routes.py)

export interface Edict {
  id: string;
  title: string;
  formal_text: string;
  status: string;
  issued_at?: string;
  form_data?: Record<string, unknown>;
}

export interface EdictProgress {
  edict_id: string;
  stage: "pending" | "executing" | "done";
  total: number;
  done: number;
  percent: number;
  subtasks: {
    key: string;
    target: string;
    title: string;
    completed: boolean;
    summary?: string | null;
  }[];
}

export interface Memorial {
  id: string;
  edict_id?: string | null;
  from_post: string;
  from_post_title?: string;
  content: string;
  status: string;
  verdict?: string | null;
  created_at?: string;
  is_urgent?: boolean;
}

export interface Impeachment {
  id: string;
  target_post: string;
  target_post_title?: string;
  type: string;
  evidence: string;
  brief?: string | null;
  recommendation?: string | null;
  status: string;
  verdict?: string | null;
}

export interface Post {
  id: string;
  institution_id: string;
  title: string;
  role: string;
  reports_to?: string | null;
  status: string;
  model?: string | null;
  current_agent?: string | null;
  persona?: {
    name: string;
    courtesy: string;
    temperament: string;
    style: string;
    origin: string;
  } | null;
}

export interface EventRecord {
  id: number;
  ts: string;
  kind: string;
  post_id?: string | null;
  detail?: Record<string, unknown> | null;
}

export interface CensorateOverview {
  pending_impeachments: number;
  pending_verdicts: number;
  recent_violations: number;
  warnings_issued: number;
  removals: number;
}

// ── court room (朝房集议) ────────────────────────────────
export interface CourtMessage {
  id: string;
  thread_id: string;
  frm: string;
  content: string;
  created_at?: string;
}

export interface CourtThread {
  id: string;
  topic: string;
  opened_by: string;
  status: "open" | "closed";
  turns: number;
  created_at?: string;
  closed_at?: string | null;
  last_message?: Pick<CourtMessage, "frm" | "content" | "created_at"> | null;
  messages?: CourtMessage[];
}

export interface CourtRoomState {
  enabled: boolean;
  max_turns: number;
  participants: string[];
  threads: CourtThread[];
}

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // edicts
  listEdicts: () => request<Edict[]>("/api/edicts"),
  getEdict: (id: string) => request<Edict>(`/api/edicts/${id}`),
  getEdictProgress: (id: string) => request<EdictProgress>(`/api/edicts/${id}/progress`),
  createEdict: (body: {
    title: string;
    task_type: string;
    description: string;
    target?: string | null;
    constraints?: string | null;
    deadline?: string | null;
  }) =>
    request<Edict>("/api/edicts", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // memorials
  listMemorials: (status?: string) =>
    request<Memorial[]>(`/api/memorials${status ? `?status=${status}` : ""}`),
  getMemorial: (id: string) => request<Memorial>(`/api/memorials/${id}`),
  verdictMemorial: (id: string, verdict: string, comment?: string) =>
    request<Memorial>(`/api/memorials/${id}/verdict`, {
      method: "POST",
      body: JSON.stringify({ verdict, comment }),
    }),

  // impeachments
  listImpeachments: (status?: string) =>
    request<Impeachment[]>(`/api/impeachments${status ? `?status=${status}` : ""}`),
  verdictImpeachment: (id: string, verdict: string, comment?: string) =>
    request<Impeachment>(`/api/impeachments/${id}/verdict`, {
      method: "POST",
      body: JSON.stringify({ verdict, comment }),
    }),

  // posts
  listPosts: () => request<Post[]>("/api/posts"),
  appointPost: (id: string, agent: string) =>
    request<Post>(`/api/posts/${id}/appoint`, {
      method: "POST",
      body: JSON.stringify({ agent }),
    }),

  // events
  listEvents: (params?: { kind?: string; post_id?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.kind) q.set("kind", params.kind);
    if (params?.post_id) q.set("post_id", params.post_id);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<EventRecord[]>(`/api/events${qs ? `?${qs}` : ""}`);
  },

  // censorate
  censorateOverview: () => request<CensorateOverview>("/api/censorate/overview"),
  censorateViolations: (limit = 20) =>
    request<EventRecord[]>(`/api/censorate/violations?limit=${limit}`),

  // court room (朝房集议 / agent playground)
  courtRoom: () => request<CourtRoomState>("/api/court"),
  getCourtThread: (id: string) => request<CourtThread>(`/api/court/threads/${id}`),
  openCourtThread: (topic: string) =>
    request<CourtThread>("/api/court/threads", {
      method: "POST",
      body: JSON.stringify({ topic }),
    }),
  speakInCourt: (threadId: string, content: string) =>
    request<{ delivered: boolean; thread_closed: boolean }>(`/api/court/threads/${threadId}/speak`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};

// SSE stream types (event names from backend EventBroadcaster)
export type StreamEvent =
  | "edict"
  | "memorial"
  | "impeachment"
  | "post_status"
  | "court"
  | "ping";

export interface StreamPayload<T = Record<string, unknown>> {
  event: StreamEvent;
  data: T;
}
