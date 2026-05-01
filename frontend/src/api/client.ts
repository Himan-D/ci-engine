// CI Engine API client — all requests go through the Vite proxy (/api → localhost:8765)

function getToken(): string | null {
  return localStorage.getItem('ci_token')
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) ?? {}),
  }

  const res = await fetch(path, { ...options, headers })

  if (res.status === 401) {
    localStorage.removeItem('ci_token')
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let msg = `HTTP ${res.status}`
    try {
      const json = JSON.parse(text)
      msg = json.detail || json.message || msg
    } catch {
      msg = text || msg
    }
    throw new Error(msg)
  }

  if (res.status === 204) return {} as T
  return res.json() as Promise<T>
}

// ─── Types ─────────────────────────────────────────────────────────────────

export type BuildStatus = 'pending' | 'running' | 'passed' | 'failed' | 'cancelled'
export type JobStatus   = 'pending' | 'running' | 'passed' | 'failed' | 'cancelled' | 'skipped' | 'soft_failed' | 'assigned' | 'blocked'
export type AgentStatus = 'idle' | 'busy' | 'offline' | 'draining'

export interface Build {
  id: number
  pipeline: string
  branch: string | null
  commit_sha: string | null
  commit?: string | null      // alias used in some responses
  repository: string | null
  status: BuildStatus
  created_at: string
  jobs?: Job[]
}

export interface BuildCreate {
  pipeline: string
  branch?: string
  commit_sha?: string
  repository?: string
}

export interface Job {
  id: number
  build_id: number
  label: string      // backend field name
  name?: string      // alias used in some responses
  command: string | null
  status: JobStatus
  exit_code: number | null
  agent_id: number | null
  started_at: string | null
  completed_at: string | null
  finished_at?: string | null  // alias for completed_at in some responses
}

export interface Agent {
  id: number
  name: string
  hostname: string | null
  status: AgentStatus
  tags: string[]
  last_seen: string | null
  current_jobs: number
  pool_id: number | null
}

export interface Secret {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_at: string
}

export interface SecretCreate {
  name: string
  value: string
  description?: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Stats {
  total_builds: number
  passed_builds: number
  failed_builds: number
  running_builds: number
  pending_builds: number
  total_agents: number
  online_agents: number
}

// ─── Auth ───────────────────────────────────────────────────────────────────

export const authApi = {
  login: (username: string, password: string) =>
    request<AuthResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, password: string, role = 'developer') =>
    request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password, role }),
    }),
}

// ─── Builds ─────────────────────────────────────────────────────────────────

export const buildsApi = {
  list: (limit = 50) =>
    request<Build[]>(`/api/builds?limit=${limit}`),

  get: (id: number) =>
    request<Build>(`/api/builds/${id}`),

  create: (build: BuildCreate) =>
    request<Build>('/api/builds', {
      method: 'POST',
      body: JSON.stringify(build),
    }),

  cancel: (id: number) =>
    request<{ status: string }>(`/api/builds/${id}/cancel`, { method: 'POST' }),

  getJobs: (buildId: number) =>
    request<Job[]>(`/api/builds/${buildId}/jobs`),

  getLogs: (jobId: number) =>
    request<{ lines: Array<{ content: string; line_number: number }> }>(`/api/jobs/${jobId}/logs`),

  unblock: (buildId: number) =>
    request<{ status: string }>(`/api/builds/${buildId}/unblock`, { method: 'POST' }),
}

// ─── Agents ─────────────────────────────────────────────────────────────────

export const agentsApi = {
  list: () =>
    request<Agent[]>('/api/agents'),

  get: (id: number) =>
    request<Agent>(`/api/agents/${id}`),

  drain: (id: number) =>
    request<Agent>(`/api/agents/${id}/drain`, { method: 'POST' }),

  undrain: (id: number) =>
    request<Agent>(`/api/agents/${id}/undrain`, { method: 'POST' }),
}

// ─── Secrets ─────────────────────────────────────────────────────────────────

export const secretsApi = {
  list: () =>
    request<Secret[]>('/api/secrets'),

  create: (secret: SecretCreate) =>
    request<Secret>('/api/secrets', {
      method: 'POST',
      body: JSON.stringify(secret),
    }),

  delete: (id: number) =>
    request<{ status: string }>(`/api/secrets/${id}`, { method: 'DELETE' }),
}

// ─── AI Analysis ─────────────────────────────────────────────────────────────

export interface JobAIAnalysis {
  id: number
  job_id: number
  root_cause: string | null
  error_category: string | null
  explanation: string | null
  fixed_command: string | null
  fix_applied: boolean
  confidence: number | null
  pipeline_suggestion: string | null
  provider?: string | null
  model?: string | null
}

export interface AIProviderStatus {
  enabled: boolean
  active_provider: string | null
  providers: Record<string, boolean>
  env_vars: Record<string, string>
}

export interface BuildAISummary {
  id: number
  build_id: number
  overall_health: string | null
  summary: string | null
  what_failed: string | null   // JSON-encoded list
  what_was_fixed: string | null
  recommendations: string | null
}

export const aiApi = {
  getJobAnalysis: (jobId: number) =>
    request<JobAIAnalysis>(`/api/jobs/${jobId}/ai-analysis`),

  getBuildSummary: (buildId: number) =>
    request<BuildAISummary>(`/api/builds/${buildId}/ai-summary`),

  getProviderStatus: () =>
    request<AIProviderStatus>('/api/ai/status'),
}

// ─── Annotations ─────────────────────────────────────────────────────────────

export type AnnotationStyle = 'success' | 'warning' | 'error' | 'info'

export interface BuildAnnotation {
  id: number
  context: string
  body_html: string
  style: AnnotationStyle
  created_by_job_id: number | null
  created_at: string
  updated_at: string | null
}

export interface AnnotationsResponse {
  build_id: number
  total: number
  annotations: BuildAnnotation[]
}

export const annotationsApi = {
  list: (buildId: number) =>
    request<AnnotationsResponse>(`/api/builds/${buildId}/annotations`),

  upsert: (buildId: number, context: string, body_html: string, style: AnnotationStyle) =>
    request<BuildAnnotation>(`/api/builds/${buildId}/annotations`, {
      method: 'POST',
      body: JSON.stringify({ context, body_html, style }),
    }),

  delete: (buildId: number, context: string) =>
    request<{ status: string }>(`/api/builds/${buildId}/annotations/${encodeURIComponent(context)}`, {
      method: 'DELETE',
    }),
}

// ─── Build Metadata ───────────────────────────────────────────────────────────

export interface BuildMetadataItem {
  id: number
  key: string
  value: string
  set_by_job_id: number | null
  created_at: string
  updated_at: string | null
}

export interface MetadataListResponse {
  build_id: number
  total: number
  metadata: BuildMetadataItem[]
}

export const metadataApi = {
  list: (buildId: number) =>
    request<MetadataListResponse>(`/api/builds/${buildId}/metadata`),

  get: (buildId: number, key: string) =>
    request<BuildMetadataItem>(`/api/builds/${buildId}/metadata/${encodeURIComponent(key)}`),

  set: (buildId: number, key: string, value: string) =>
    request<BuildMetadataItem>(`/api/builds/${buildId}/metadata/${encodeURIComponent(key)}`, {
      method: 'POST',
      body: JSON.stringify({ value }),
    }),
}

// ─── Analytics ────────────────────────────────────────────────────────────────

export interface RepositoryMetric {
  id: number
  repository: string
  date: string
  total_builds: number
  passed_builds: number
  failed_builds: number
  avg_duration_seconds: number | null
  p50_duration_seconds: number | null
  p95_duration_seconds: number | null
  mttr_seconds: number | null
  cost_usd: number | null
}

export interface FlakynessRecord {
  test_name: string
  suite_name: string | null
  repository: string | null
  total_runs: number
  failed_runs: number
  flakiness_score: number
  first_seen: string | null
  last_seen: string | null
  is_quarantined: boolean
}

export interface BuildCostEntry {
  build_id: number
  repository: string | null
  duration_seconds: number | null
  cost_usd: number | null
  created_at: string | null
}

export interface CostResponse {
  total_cost_usd: number
  avg_cost_usd: number | null
  total_builds: number
  builds: BuildCostEntry[]
}

export const analyticsApi = {
  repoMetrics: (repository: string, days = 30) => {
    const end = new Date()
    const start = new Date(end.getTime() - days * 86400_000)
    const params = new URLSearchParams({
      start_date: start.toISOString().split('T')[0],
      end_date: end.toISOString().split('T')[0],
    })
    return request<RepositoryMetric[]>(`/api/analytics/repositories/${encodeURIComponent(repository)}/metrics?${params}`)
  },

  flakiness: (repository: string) =>
    request<{ total: number; records: FlakynessRecord[] }>(
      `/api/repositories/${encodeURIComponent(repository)}/flakiness`
    ),

  cost: (repository?: string, days = 30) => {
    const end = new Date()
    const start = new Date(end.getTime() - days * 86400_000)
    const params = new URLSearchParams({
      start_date: start.toISOString().split('T')[0],
      end_date: end.toISOString().split('T')[0],
    })
    if (repository) params.set('repository', repository)
    return request<CostResponse>(`/api/analytics/cost?${params}`)
  },
}

// ─── Stats ───────────────────────────────────────────────────────────────────

export const statsApi = {
  get: () =>
    // Try /api/stats, fall back to derived stats from builds
    request<Stats>('/api/stats').catch(async () => {
      const builds = await buildsApi.list(200)
      const agents = await agentsApi.list().catch(() => [] as Agent[])
      return {
        total_builds:   builds.length,
        passed_builds:  builds.filter(b => b.status === 'passed').length,
        failed_builds:  builds.filter(b => b.status === 'failed').length,
        running_builds: builds.filter(b => b.status === 'running').length,
        pending_builds: builds.filter(b => b.status === 'pending').length,
        total_agents:   agents.length,
        online_agents:  agents.filter(a => a.status !== 'offline').length,
      } satisfies Stats
    }),
}
