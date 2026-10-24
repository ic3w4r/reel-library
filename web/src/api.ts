export type ReelSummary = {
  id: string;
  url: string;
  status: "pending" | "analyzed" | "failed";
  title?: string;
  summary?: string;
  category?: string;
  content_type?: string;
  tags?: string[];
  creator?: string;
  collections?: string[];
  saved_at?: string;
  thumbnail?: string;
};

export type LinkItem = {
  name: string;
  kind?: string;
  url?: string;
  verified?: boolean;
  search_url?: string;
  description?: string;
  source?: string;
  found_via?: string;
  category?: string;
  from_reel?: { id: string; title?: string; url: string };
};

export type ReelDetail = ReelSummary & {
  key_points?: string[];
  topics?: string[];
  why_saved?: string;
  caption?: string;
  transcript?: string;
  on_screen_text?: string;
  language?: string;
  duration_seconds?: number;
  links?: LinkItem[];
  signals?: Record<string, Signal>;
  analyzed_at?: string;
  error?: string;
};

export type Overview = {
  total_reels: number;
  by_status: Record<string, number>;
  collections: { name: string; reels: number; top_categories: string[] }[];
  not_in_any_collection: number;
  categories: Record<string, number>;
  content_types: Record<string, number>;
  top_tags: Record<string, number>;
  top_creators: Record<string, number>;
  extracted_links: number;
  link_kinds: Record<string, number>;
};

export type JobStatus = {
  running: boolean;
  current: { id: string; creator?: string; elapsed_seconds: number } | null;
  queued: number;
  queued_ids: string[];
  batch_total: number;
  done: number;
  failed: number;
  recent: { id: string; status: string; title?: string; category?: string; error?: string; finished_at: number }[];
  library: Record<string, number>;
  halted: string | null;
};

export type Engine = {
  id: string;
  preset: string;
  name: string;
  type: "anthropic" | "openai" | "laya";
  base_url: string;
  model: string;
  effort: string;
  vision: boolean;
  json_mode: "auto" | "schema" | "object" | "none";
  key_set: boolean;
  key_from_env: boolean;
  key_hint: string;
  ready: boolean;
  label: string;
};

export type Preset = {
  label: string;
  type: "anthropic" | "openai" | "laya";
  base_url: string;
  model: string;
  key_env: string;
  needs_key: boolean;
  key_url: string;
};

export type EnginesState = {
  engines: Engine[];
  active: string | null;
  fallback: string | null;
  presets: Record<string, Preset>;
  created?: string;
};

export type Settings = {
  whisper_model: string;
  num_frames: number;
  verify_links: boolean;
  auto_signals: boolean;
  ai_ready: boolean;
  active_engine: Engine | null;
  fallback_engine: Engine | null;
  instagram_login: boolean;
  instagram_cookie_source: "uploaded" | "browser" | "file" | "none";
  data_dir: string;
  options: { whisper_models: string[] };
};

export type Signal = { answer: string; value: number | null; confidence: number | null };

export type Analytics = {
  total_reels: number;
  with_text: number;
  with_signals: number;
  missing_signals: number;
  laya_available: boolean;
  laya_loaded: boolean;
  saves_by_month: { month: string; total: number; by_category: Record<string, number> }[];
  categories: Record<string, number>;
  signal_categories: Record<string, number>;
  content_types: Record<string, number>;
  purposes: Record<string, number>;
  actionable: Record<string, number>;
  revisit: Record<string, number>;
  collections: { name: string; reels: number; analyzed: number; with_signals: number; actionable: number; top_category: string | null }[];
  signals_job: SignalsStatus;
};

export type SignalsStatus = { running: boolean; done: number; total: number; error: string | null; finished_at: number | null };

export type AskResult = {
  question: string;
  answer_type: "yes_no" | "choice" | "scale";
  asked: number;
  seconds?: number;
  summary?: Record<string, number>;
  skipped_without_text: number;
  results: { reel: ReelSummary; answer: string; probability?: number; score?: number; confidence?: number }[];
};

export type ImportResult = {
  files: string[];
  reels_seen: number;
  new_reels: number;
  collections: string[];
  pending_analysis: number;
  queued?: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return data as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  reels: (params: Record<string, string | number | undefined>) =>
    request<{ total: number; reels: ReelSummary[] }>(`/api/reels${qs(params)}`),
  reel: (id: string) => request<ReelDetail>(`/api/reels/${encodeURIComponent(id)}`),
  addReel: (url: string, collection?: string, analyze = true) =>
    request<{ id: string; queued: boolean }>("/api/reels", json("POST", { url, collection, analyze })),
  deleteReel: (id: string) => request(`/api/reels/${encodeURIComponent(id)}`, { method: "DELETE" }),
  addToCollection: (id: string, name: string) =>
    request<{ collections: string[] }>(`/api/reels/${encodeURIComponent(id)}/collections`, json("POST", { name })),
  removeFromCollection: (id: string, name: string) =>
    request<{ collections: string[] }>(
      `/api/reels/${encodeURIComponent(id)}/collections/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  links: (params: Record<string, string | number | boolean | undefined>) =>
    request<{ total: number; links: LinkItem[] }>(`/api/links${qs(params)}`),
  importExport: (file: File, analyze: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ImportResult>(`/api/import${qs({ analyze })}`, { method: "POST", body: fd });
  },
  analyze: (body: { ids?: string[]; limit?: number; collection?: string; retry_failed?: boolean }) =>
    request<{ queued: number }>("/api/analyze", json("POST", body)),
  jobs: () => request<JobStatus>("/api/jobs"),
  cancelJobs: () => request<{ cancelled: number }>("/api/jobs/cancel", { method: "POST" }),
  settings: () => request<Settings>("/api/settings"),
  analytics: () => request<Analytics>("/api/analytics"),
  runSignals: (body: { limit?: number; collection?: string; recompute?: boolean } = {}) =>
    request<{ started: boolean; count?: number; message?: string | null }>("/api/signals/run", json("POST", body)),
  signalsStatus: () => request<SignalsStatus>("/api/signals/status"),
  ask: (body: { question: string; answer_type: string; options?: string[]; collection?: string; category?: string; limit?: number }) =>
    request<AskResult>("/api/ask", json("POST", body)),
  saveSettings: (body: Partial<Pick<Settings, "whisper_model" | "num_frames" | "verify_links" | "auto_signals">>) =>
    request<Settings>("/api/settings", json("PUT", body)),
  engines: () => request<EnginesState>("/api/engines"),
  createEngine: (body: Partial<Engine> & { preset: string; api_key?: string }) =>
    request<EnginesState>("/api/engines", json("POST", body)),
  updateEngine: (id: string, body: Partial<Engine> & { api_key?: string }) =>
    request<EnginesState>(`/api/engines/${id}`, json("PUT", body)),
  deleteEngine: (id: string) => request<EnginesState>(`/api/engines/${id}`, { method: "DELETE" }),
  setEngineRoles: (active: string, fallback: string | null) =>
    request<EnginesState>("/api/engines-roles", json("PUT", { active, fallback })),
  testEngine: (id: string) => request<{ ok: boolean; message: string }>(`/api/engines/${id}/test`, { method: "POST" }),
  engineModels: (id: string) => request<{ models: string[] }>(`/api/engines/${id}/models`),
  setInstagramSession: (sessionid: string) =>
    request<Settings>("/api/settings/instagram", json("POST", { sessionid })),
  uploadCookies: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Settings>("/api/settings/cookies", { method: "POST", body: fd });
  },
  clearInstagram: () => request<Settings>("/api/settings/instagram", { method: "DELETE" }),
};
