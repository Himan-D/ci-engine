const API_BASE = 'http://localhost:8002';

export interface Build {
  id: number;
  pipeline: string;
  branch: string;
  commit: string;
  repository: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  created_at: string;
}

export interface BuildCreate {
  pipeline: string;
  branch?: string;
  commit?: string;
  repository?: string;
  git_ref?: string;
  clone_depth?: number;
}

export interface Job {
  id: number;
  build_id: number;
  step: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  agent_id?: number;
  started_at?: string;
  finished_at?: string;
}

export interface Agent {
  id: number;
  name: string;
  status: 'online' | 'offline' | 'draining';
  last_seen: string;
  labels: string[];
  current_jobs: number;
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}

export const buildsApi = {
  list: () => fetchJson<Build[]>('/api/builds'),

  get: (id: number) => fetchJson<Build>(`/api/builds/${id}`),

  create: (build: BuildCreate) =>
    fetchJson<Build>('/api/builds', {
      method: 'POST',
      body: JSON.stringify(build),
    }),

  getJobs: (buildId: number) => fetchJson<Job[]>(`/api/builds/${buildId}/jobs`),

  cancel: (buildId: number) =>
    fetchJson<{ status: string }>(`/api/builds/${buildId}/cancel`, {
      method: 'POST',
    }),
};

export const agentsApi = {
  list: () => fetchJson<Agent[]>('/api/agents'),

  get: (id: number) => fetchJson<Agent>(`/api/agents/${id}`),

  heartbeat: (id: number) =>
    fetchJson<{ status: string }>(`/api/agents/${id}/heartbeat`, {
      method: 'POST',
    }),
};

export const pipelineApi = {
  list: () => buildsApi.list(),

  create: (pipeline: string, options?: { branch?: string; commit?: string; repository?: string }) =>
    buildsApi.create({
      pipeline,
      branch: options?.branch || 'main',
      commit: options?.commit || '',
      repository: options?.repository || '',
    }),

  getJobs: (buildId: number) => buildsApi.getJobs(buildId),
};

export default { buildsApi, agentsApi, pipelineApi };