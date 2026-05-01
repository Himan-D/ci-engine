import { create } from 'zustand'
import {
  Node,
  Edge,
  Connection,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  NodeChange,
  EdgeChange,
} from '@xyflow/react'
import * as yaml from 'js-yaml'
import { getNodeType } from '../data/nodeTypes'
import type { Pipeline, PipelineStep } from '../types/pipeline'

const genId = () => Math.random().toString(36).substring(2, 9)

// Assign a node type from label / command heuristics
function inferNodeType(label: string, command = ''): string {
  const l = label.toLowerCase()
  const c = command.toLowerCase()
  if (c.includes('docker build')) return 'docker-build'
  if (c.includes('docker push')) return 'docker-push'
  if (c.includes('docker-compose') || c.includes('docker compose')) return 'docker-compose'
  if (c.includes('kubectl apply')) return 'kubectl-apply'
  if (c.includes('helm upgrade') || c.includes('helm install')) return 'helm-upgrade'
  if (c.includes('npm ci') || c.includes('npm install') || c.includes('yarn install') || c.includes('pnpm install')) return 'npm-install'
  if (c.includes('npm run build') || c.includes('yarn build') || c.includes('pnpm build')) return 'npm-build'
  if (c.includes('npm test') || c.includes('yarn test') || c.includes('jest') || c.includes('vitest')) return 'npm-test'
  if (c.includes('pytest') || c.includes('python -m pytest')) return 'pytest'
  if (c.includes('pip install')) return 'pip-install'
  if (c.includes('go build')) return 'go-build'
  if (c.includes('go test')) return 'go-test'
  if (c.includes('mvn') || c.includes('gradle')) return 'maven-build'
  if (c.includes('ruff') || c.includes('eslint') || c.includes('golangci')) return 'ruff'
  if (c.includes('aws ecr')) return 'aws-ecr-push'
  if (c.includes('aws ecs')) return 'aws-ecs-deploy'
  if (c.includes('aws s3')) return 'aws-s3-sync'
  if (c.includes('gcloud run deploy')) return 'gcloud-deploy'
  if (c.includes('terraform')) return 'terraform-apply'
  if (c.includes('ansible')) return 'ansible-run'
  if (c.includes('playwright')) return 'playwright'
  if (c.includes('cypress')) return 'cypress'
  if (c.includes('vercel')) return 'vercel-deploy'
  if (c.includes('netlify')) return 'netlify-deploy'
  if (c.includes('git clone')) return 'git-clone'
  if (c.includes('git tag')) return 'git-tag'
  if (c.includes('slack') || c.includes('curl') && c.includes('webhook')) return 'slack-notify'
  if (c.includes('trivy') || c.includes('semgrep') || c.includes('snyk')) return 'sast-scan'
  if (l.includes('wait') || l.includes('block') || l.includes('approval')) return 'wait'
  if (l.includes('parallel')) return 'parallel'
  return 'command'
}

// Lay out nodes in a simple topological sort / DAG layout
function computeLayout(
  steps: Array<{ id: string; label: string; depends_on?: string }>,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>()
  const labelToId = new Map<string, string>()
  steps.forEach(s => labelToId.set(s.label, s.id))

  // BFS levels
  const levels = new Map<string, number>()
  const inDegree = new Map<string, number>()
  steps.forEach(s => inDegree.set(s.id, 0))

  const edges: Array<[string, string]> = []
  steps.forEach(s => {
    if (s.depends_on) {
      const deps = s.depends_on.split(',').map(d => d.trim()).filter(Boolean)
      deps.forEach(dep => {
        const depId = labelToId.get(dep) ?? dep
        edges.push([depId, s.id])
        inDegree.set(s.id, (inDegree.get(s.id) ?? 0) + 1)
      })
    }
  })

  const queue: string[] = []
  steps.forEach(s => { if ((inDegree.get(s.id) ?? 0) === 0) { queue.push(s.id); levels.set(s.id, 0) } })

  while (queue.length) {
    const cur = queue.shift()!
    const curLevel = levels.get(cur) ?? 0
    edges.filter(([src]) => src === cur).forEach(([, tgt]) => {
      levels.set(tgt, Math.max(levels.get(tgt) ?? 0, curLevel + 1))
      inDegree.set(tgt, (inDegree.get(tgt) ?? 1) - 1)
      if ((inDegree.get(tgt) ?? 0) <= 0) queue.push(tgt)
    })
  }

  // Group by level
  const byLevel = new Map<number, string[]>()
  steps.forEach(s => {
    const lv = levels.get(s.id) ?? 0
    if (!byLevel.has(lv)) byLevel.set(lv, [])
    byLevel.get(lv)!.push(s.id)
  })

  const X_SPACING = 240
  const Y_SPACING = 130

  byLevel.forEach((ids, level) => {
    const totalWidth = (ids.length - 1) * X_SPACING
    ids.forEach((id, i) => {
      positions.set(id, {
        x: i * X_SPACING - totalWidth / 2 + 400,
        y: level * Y_SPACING + 60,
      })
    })
  })

  return positions
}

interface ParsedStep {
  id: string
  label: string
  command?: string
  depends_on?: string
  nodeType?: string
  timeout?: number
  maxRetries?: number
  priority?: number
  required_tags?: string
  continueOnError?: boolean
  skip_condition?: string
  env_raw?: string
  working_dir?: string
}

function parseYAML(yamlText: string): { nodes: Node[]; edges: Edge[] } {
  if (!yamlText.trim()) return { nodes: [], edges: [] }

  let parsed: unknown
  try {
    parsed = yaml.load(yamlText)
  } catch {
    return { nodes: [], edges: [] }
  }

  if (!parsed || typeof parsed !== 'object') return { nodes: [], edges: [] }
  const raw = parsed as Record<string, unknown>
  const stepsRaw = (raw.steps as unknown[]) ?? []
  if (!Array.isArray(stepsRaw)) return { nodes: [], edges: [] }

  const steps: ParsedStep[] = stepsRaw
    .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
    .map(s => {
      const label = String(s.label ?? s.name ?? 'Step')
      const command = String(s.command ?? s.run ?? '')
      const depends_on = Array.isArray(s.depends_on)
        ? (s.depends_on as string[]).join(', ')
        : typeof s.depends_on === 'string'
        ? s.depends_on
        : undefined
      const nodeType = typeof s.node_type === 'string' ? s.node_type : inferNodeType(label, command)
      // env
      let env_raw = ''
      if (s.env) {
        if (Array.isArray(s.env)) {
          env_raw = (s.env as string[]).join('\n')
        } else if (typeof s.env === 'object') {
          env_raw = Object.entries(s.env as Record<string, string>)
            .map(([k, v]) => `${k}=${v}`)
            .join('\n')
        }
      }

      return {
        id: genId(),
        label,
        command: command || undefined,
        depends_on,
        nodeType,
        timeout: typeof s['timeout-minutes'] === 'number' ? (s['timeout-minutes'] as number) : undefined,
        maxRetries: typeof s.retry === 'number' ? (s.retry as number) : undefined,
        priority: typeof s.priority === 'number' ? (s.priority as number) : undefined,
        required_tags: typeof s.agents === 'string' ? s.agents : undefined,
        continueOnError: s['continue-on-error'] === true,
        skip_condition: typeof s.if === 'string' ? s.if : undefined,
        env_raw: env_raw || undefined,
        working_dir: typeof s.working_dir === 'string' ? s.working_dir : undefined,
      }
    })

  const positions = computeLayout(steps)
  const labelToId = new Map<string, string>()
  steps.forEach(s => labelToId.set(s.label, s.id))

  const nodes: Node[] = steps.map(s => ({
    id: s.id,
    type: 'pipeline',
    position: positions.get(s.id) ?? { x: 200, y: 100 },
    data: {
      label: s.label,
      command: s.command,
      nodeType: s.nodeType,
      status: 'pending',
      depends_on: s.depends_on,
      timeout: s.timeout,
      maxRetries: s.maxRetries,
      priority: s.priority,
      required_tags: s.required_tags,
      continueOnError: s.continueOnError,
      skip_condition: s.skip_condition,
      env_raw: s.env_raw,
      working_dir: s.working_dir,
    },
  }))

  const edges: Edge[] = []
  steps.forEach(s => {
    if (!s.depends_on) return
    const deps = s.depends_on.split(',').map(d => d.trim()).filter(Boolean)
    deps.forEach(dep => {
      const srcId = labelToId.get(dep) ?? dep
      const src = steps.find(x => x.id === srcId || x.label === dep)
      if (!src) return
      edges.push({
        id: `${src.id}-${s.id}`,
        source: src.id,
        target: s.id,
        type: 'smoothstep',
        style: { stroke: '#3f3f46', strokeWidth: 2 },
        animated: false,
      })
    })
  })

  return { nodes, edges }
}

function nodesToYAML(nodes: Node[], edges: Edge[]): string {
  // Build depends_on from edges
  const depMap = new Map<string, string[]>()
  edges.forEach(e => {
    const src = nodes.find(n => n.id === e.source)
    if (!src) return
    const list = depMap.get(e.target) ?? []
    list.push((src.data as Record<string, unknown>).label as string)
    depMap.set(e.target, list)
  })

  const steps = nodes.map(n => {
    const d = n.data as Record<string, unknown>
    const deps = depMap.get(n.id) ?? ((d.depends_on as string) ? (d.depends_on as string).split(',').map(x => x.trim()).filter(Boolean) : [])
    const nodeType = (d.nodeType as string) ?? 'command'
    const step: Record<string, unknown> = { label: d.label }
    // Include node_type for special nodes so the backend can handle them
    if (nodeType && nodeType !== 'command') step.node_type = nodeType
    if (d.command && nodeType !== 'wait' && nodeType !== 'block') step.command = d.command
    if (deps.length) step.depends_on = deps.length === 1 ? deps[0] : deps
    if (d.timeout) step['timeout-minutes'] = d.timeout
    if (d.maxRetries) step.retry = d.maxRetries
    if (d.priority) step.priority = d.priority
    if (d.required_tags) step.agents = d.required_tags
    if (d.continueOnError) step['continue-on-error'] = true
    if (d.skip_condition) step.if = d.skip_condition
    if (d.working_dir) step.working_dir = d.working_dir
    if (d.env_raw) {
      const envObj: Record<string, string> = {}
      String(d.env_raw).split('\n').forEach(line => {
        const idx = line.indexOf('=')
        if (idx > 0) envObj[line.slice(0, idx)] = line.slice(idx + 1)
      })
      if (Object.keys(envObj).length) step.env = envObj
    }
    return step
  })

  return yaml.dump({ steps }, { lineWidth: -1, quotingType: '"', forceQuotes: false })
}

interface PipelineEditorState {
  nodes: Node[]
  edges: Edge[]
  pipelineYAML: string
  selectedNodeId: string | null
  pipelineName: string

  // Actions
  onNodesChange: (changes: NodeChange[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => void
  addNode: (nodeType: string, position?: { x: number; y: number }) => void
  updateNode: (id: string, data: Record<string, unknown>) => void
  deleteNode: (id: string) => void
  setSelectedNode: (id: string | null) => void
  loadFromYAML: (yaml: string) => void
  toYAML: () => string
  toPipeline: () => Pipeline
  setPipelineName: (name: string) => void
  /** Update a node's live status by matching job label */
  applyJobStatus: (label: string, status: string) => void
  /** Reset all node statuses to 'pending' (before re-running) */
  resetStatuses: () => void
}

export const usePipelineStore = create<PipelineEditorState>((set, get) => ({
  nodes: [],
  edges: [],
  pipelineYAML: '',
  selectedNodeId: null,
  pipelineName: 'My Pipeline',

  onNodesChange: changes => set({ nodes: applyNodeChanges(changes, get().nodes) }),
  onEdgesChange: changes => set({ edges: applyEdgeChanges(changes, get().edges) }),
  onConnect: connection =>
    set({
      edges: addEdge(
        { ...connection, type: 'smoothstep', style: { stroke: '#3f3f46', strokeWidth: 2 } },
        get().edges,
      ),
    }),

  addNode: (nodeType, position) => {
    const nt = getNodeType(nodeType)
    const existing = get().nodes
    const pos = position ?? { x: 200 + existing.length * 20, y: 100 + existing.length * 20 }
    const id = genId()
    const newNode: Node = {
      id,
      type: 'pipeline',
      position: pos,
      data: {
        label: nt.defaultLabel || nt.label,
        command: nt.defaultCommand,
        nodeType: nt.type,
        status: 'pending',
      },
    }
    set({ nodes: [...existing, newNode], selectedNodeId: id })
  },

  updateNode: (id, data) =>
    set({
      nodes: get().nodes.map(n => (n.id === id ? { ...n, data: { ...n.data, ...data } } : n)),
    }),

  deleteNode: id =>
    set({
      nodes: get().nodes.filter(n => n.id !== id),
      edges: get().edges.filter(e => e.source !== id && e.target !== id),
      selectedNodeId: get().selectedNodeId === id ? null : get().selectedNodeId,
    }),

  setSelectedNode: id => set({ selectedNodeId: id }),

  loadFromYAML: yamlText => {
    const { nodes, edges } = parseYAML(yamlText)
    set({ nodes, edges, pipelineYAML: yamlText })
  },

  toYAML: () => {
    const y = nodesToYAML(get().nodes, get().edges)
    set({ pipelineYAML: y })
    return y
  },

  toPipeline: () => {
    const { nodes } = get()
    const steps: PipelineStep[] = nodes.map(n => ({
      id: n.id,
      label: (n.data as Record<string, unknown>).label as string,
      command: (n.data as Record<string, unknown>).command as string,
    }))
    return { steps }
  },

  setPipelineName: name => set({ pipelineName: name }),

  applyJobStatus: (label, status) =>
    set({
      nodes: get().nodes.map(n =>
        (n.data as Record<string, unknown>).label === label
          ? { ...n, data: { ...n.data, status } }
          : n,
      ),
    }),

  resetStatuses: () =>
    set({
      nodes: get().nodes.map(n => ({ ...n, data: { ...n.data, status: 'pending' } })),
    }),
}))
