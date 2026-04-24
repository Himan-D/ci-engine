export interface PipelineStep {
  id: string;
  label: string;
  command?: string;
  container?: {
    image: string;
    cpu?: string;
    memory?: string;
  };
  env_vars?: Record<string, string>;
  working_directory?: string;
  timeout?: number;
  retry?: number;
  depends_on?: string[];
  cache?: {
    key: string;
    path: string | string[];
  };
  services?: ServiceConfig[];
  if?: string;
}

export interface ServiceConfig {
  name: string;
  image: string;
  env?: Record<string, string>;
  ports?: string[];
}

export interface Pipeline {
  name?: string;
  steps: PipelineStep[];
}

export interface PipelineNode {
  id: string;
  type: 'step' | 'trigger' | 'wait' | 'block';
  data: {
    label: string;
    command?: string;
    status?: 'pending' | 'running' | 'passed' | 'failed';
    [key: string]: unknown;
  };
  position: { x: number; y: number };
}

export interface PipelineEdge {
  id: string;
  source: string;
  target: string;
  type?: 'default' | 'smoothstep' | 'step';
}

export interface VisualPipeline {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

export type StepStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

export interface Build {
  id: number;
  status: string;
  branch: string;
  commit: string;
  created_at: string;
  finished_at?: string;
}

export interface Job {
  id: number;
  build_id: number;
  label: string;
  status: StepStatus;
  started_at?: string;
  finished_at?: string;
}