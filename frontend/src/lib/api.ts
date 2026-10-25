// Typed client for the Data Mind API.

export type Preview = { columns: string[]; rows: unknown[][] }

export type ColumnDetail = {
  name: string
  type: string
  missing_pct: number
  unique: number
  warnings: string[]
  stats?: Record<string, number | string | boolean | null> | null
  top_values?: { value: string; count: number }[]
}

export type DatasetMeta = {
  id: string
  name: string
  source: 'upload' | 'sample' | 'database'
  rows: number
  columns: number
  created_at: number
  report?: Record<string, unknown>
}

export type DatasetPayload = {
  dataset: DatasetMeta
  preview: Preview
  profile: {
    rows: number
    columns: number
    duplicate_rows: number
    missing_cells_pct: number
    type_counts: Record<string, number>
    strong_correlations: { a: string; b: string; r: number }[]
    columns_detail: ColumnDetail[]
  }
  candidates: string[]
}

export type ChatMessage = { role: 'user' | 'assistant'; content: string }

export type Intent = {
  target?: string | null
  task?: string | null
  goal?: string | null
  exclude_columns?: string[]
  notes?: string
}

export type IntakeReply = {
  reply: string
  intent: Intent
  ready: boolean
  source: string
  candidates: string[]
  steps?: { label: string; detail: string }[]
  action?: 'run' | 'wait'
  llm_error?: string
}

export type AgentEvent = {
  seq: number
  ts: number
  type:
    | 'run_started'
    | 'node_started'
    | 'node_log'
    | 'node_completed'
    | 'node_failed'
    | 'node_error'
    | 'awaiting_input'
    | 'input_received'
    | 'run_resumed'
    | 'llm_call'
    | 'run_completed'
    | 'run_failed'
  node: string | null
  message: string
  data: any
}

export type Stage = { id: string; label: string; desc: string }
export type GraphDef = { stages: Stage[]; edges: { from: string; to: string; kind?: string; label?: string }[] }

export type PlanColumn = {
  column: string
  role: 'feature' | 'target' | 'drop'
  kind?: string
  semantic_type?: string
  impute?: string
  outliers?: string
  encode?: string
  scale?: string
  reason?: string
  source?: string
  confidence?: number
  ops?: string
}

export type Question = { id: string; question: string; options: string[]; column?: string | null; default?: string | null }

export type CardOption = { value: string; label: string; description?: string }
export type QuestionCard = { id: string; header: string; question: string; options: CardOption[]; allow_other?: boolean; other_placeholder?: string }

export type PendingInput =
  | { node: string; kind: 'questions'; id: string; title: string; questions: QuestionCard[] }
  | {
      node: string
      kind: 'question'
      id: string
      title: string
      question: string
      options: { value: string; label: string; description?: string }[]
      allow_free_text?: boolean
    }
  | {
      node: string
      kind: 'review'
      id: string
      title: string
      question: string
      plan: { target?: string; task?: string; split?: any; imbalance?: string; notes?: string[]; columns: PlanColumn[] }
      questions: Question[]
      low_confidence: string[]
    }

export type RunMeta = {
  run_id: string
  status: 'running' | 'waiting' | 'completed' | 'failed' | 'interrupted'
  created_at: number
  completed_at?: number
  dataset: DatasetMeta
  provider: string
  intent?: Intent
  pending?: PendingInput | null
  error?: string | null
  failure?: RunFailure | null
  repairs?: RepairAttempt[]
}

/** One self-repair attempt: what failed, why, and what the agent changed before retrying. */
export type RepairAttempt = {
  attempt: number
  limit: number
  stage: string
  label: string
  error_type: string
  error: string
  reason: string
  hint: string
  diagnosis: string
  culprits: string[]
  fixes: string[]
  changes: string[]
  source: string
}

export type RunFailure = {
  stage: string | null
  label: string
  error_type: string
  error: string
  reason: string
  hint: string
  columns?: string[]
  traceback?: string
  attempts: RepairAttempt[]
  limit?: number
  why_stopped?: string
}

export type Check = { id: string; name: string; status: 'pass' | 'warn' | 'fail'; detail: string }

export type RunDetail = {
  meta: RunMeta
  result: null | {
    stats: Record<string, any>
    feature_names: string[]
    checks: {
      checks: Check[]
      summary: { passed: number; warnings: number; failed: number; total: number }
      baseline: null | Record<string, any>
      comparisons: { column: string; before: Record<string, number | null>; after: Record<string, number | null>; transform: string }[]
      leakage_warnings: any[]
    }
    verdict: { verdict: string; summary: string; concerns: string[]; source: string } | null
    plan: { target?: string; task?: string; columns: PlanColumn[]; notes: string[]; split: any; imbalance: string }
    files: { name: string; size: number; kind: string }[]
    llm_calls: any[]
  }
  plan: any
  verdict: any
  target_info: any
  profile: DatasetPayload['profile'] | null
}

export type PlotSpec = { data: any[]; layout: any }

export type Insight = {
  id: string
  kind: string
  title: string
  text: string
  score: number
  columns: string[]
  stats: Record<string, any>
  chart: PlotSpec
}

export type InsightsPayload = {
  roles: Record<string, any>
  kpis: { label: string; value: string; hint?: string }[]
  insights: Insight[]
  candidates_considered: number
  narrative: { headline: string; summary: string; bullets: string[]; next_steps: string[]; source?: string }
}

export type ChartAnswer = {
  reply: string
  chart?: PlotSpec | null
  table?: { columns: string[]; rows: unknown[][] }
  kpi?: { label: string; value: string }
  spec?: Record<string, any>
  source?: string
}

export type Settings = {
  llm: {
    provider: 'heuristic' | 'ollama' | 'groq' | 'gemini'
    fallback_order: string[]
    use_fallback: boolean
    temperature: number
    timeout_seconds: number
    ollama_base_url: string
    ollama_model: string
    groq_api_key: string
    groq_model: string
    gemini_api_key: string
    gemini_model: string
  }
  privacy: { share_labels_with_local: boolean; share_labels_with_cloud: boolean; max_labels_per_column: number }
  agent: { human_review: 'always' | 'on_uncertainty' | 'never'; max_plan_retries: number; max_revise_loops: number; max_repair_attempts: number; run_baseline_model: boolean; baseline_max_rows: number }
  prep: {
    model_family: string
    test_size: number
    random_seed: number
    drop_missing_threshold: number
    max_onehot_categories: number
    rare_category_threshold: number
    outlier_strategy: string
    scaling: string
    imbalance: string
    add_missing_flags: boolean
    drop_duplicates: boolean
  }
  insights: { max_insights: number; significance_level: number; narrative: boolean }
  ui: { theme: 'dark' | 'light' | 'system'; animation_speed: number; reduce_motion: boolean; pace_runs: boolean }
  env_file?: string
}

export type DBTable = {
  name: string
  columns: { name: string; type: string }[]
  primary_key: string[]
  foreign_keys: { columns: string[]; ref_table: string; ref_columns: string[] }[]
  rows: number | null
}
export type JoinSpec = { left: string; right: string; left_on: string; right_on: string; how: string; confidence?: number; reason?: string }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init?.headers : { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not json */
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<DatasetPayload>('/api/datasets/upload', { method: 'POST', body: fd })
  },
  samples: () => req<{ id: string; title: string; description: string; file: string }[]>('/api/samples'),
  loadSample: (id: string) => post<DatasetPayload & { database_url?: string }>(`/api/samples/${id}`),
  datasets: () => req<DatasetMeta[]>('/api/datasets'),
  dataset: (id: string) => req<DatasetPayload>(`/api/datasets/${id}`),
  intake: (dataset_id: string, messages: ChatMessage[]) => post<IntakeReply>('/api/chat/intake', { dataset_id, messages }),
  graph: () => req<GraphDef>('/api/graph'),
  startRun: (dataset_id: string, messages: ChatMessage[], intent: Intent) => post<{ run_id: string }>('/api/runs', { dataset_id, messages, intent }),
  runs: () => req<RunMeta[]>('/api/runs'),
  run: (id: string) => req<RunDetail>(`/api/runs/${id}`),
  deleteRun: (id: string) => req<unknown>(`/api/runs/${id}`, { method: 'DELETE' }),
  events: (id: string) => req<AgentEvent[]>(`/api/runs/${id}/events`),
  resume: (id: string, value: unknown) => post<{ ok: boolean }>(`/api/runs/${id}/resume`, { value }),
  table: (id: string, which: string, offset: number, limit: number) =>
    req<Preview & { total: number; offset: number }>(`/api/runs/${id}/table?which=${which}&offset=${offset}&limit=${limit}`),
  insights: (id: string) => req<InsightsPayload>(`/api/runs/${id}/insights`),
  insightChat: (id: string, message: string, history: ChatMessage[]) => post<ChartAnswer>(`/api/runs/${id}/insights/chat`, { message, history }),
  settings: () => req<{ settings: Settings; ollama_models: string[] }>('/api/settings'),
  saveSettings: (s: Partial<Settings>) => req<{ settings: Settings }>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
  testProvider: (provider: string) => post<{ ok: boolean; seconds: number; reply: any; error?: string }>('/api/settings/test', { provider }),
  ollamaModels: (base_url: string) => req<{ models: string[] }>(`/api/ollama/models?base_url=${encodeURIComponent(base_url)}`),
  dbConnect: (url: string) => post<{ dialect: string; tables: DBTable[] }>('/api/db/connect', { url }),
  dbJoins: (url: string, tables: string[]) => post<{ joins: JoinSpec[] }>('/api/db/joins', { url, tables }),
  dbPreview: (body: Record<string, unknown>) => post<{ sql: string; preview: Preview }>('/api/db/preview', body),
  dbImport: (body: Record<string, unknown>) => post<DatasetPayload>('/api/db/import', body),
  fileUrl: (id: string, name: string) => `/api/runs/${id}/files/${encodeURIComponent(name)}`,
  streamUrl: (id: string, after: number) => `/api/runs/${id}/stream?after=${after}`,
}
