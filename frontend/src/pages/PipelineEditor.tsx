import { useCallback, useEffect, useState, useRef } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useReactFlow,
  ReactFlowProvider,
  type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Play,
  Save,
  Plus,
  ChevronLeft,
  ChevronRight,
  GitBranch,
  Settings,
  Layers,
  Code2,
  LayoutTemplate,
  ExternalLink,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import PipelineNode from '../components/nodes/PipelineNode'
import { NodePicker } from '../components/NodePicker'
import { NodeProperties } from '../components/NodeProperties'
import { usePipelineStore } from '../hooks/usePipelineStore'
import { type NodeTypeDef } from '../data/nodeTypes'
import { buildsApi } from '../api/client'

const nodeTypes = { pipeline: PipelineNode }

// ─── Template pipelines ──────────────────────────────────────────────────────
const TEMPLATES = [
  {
    name: 'Node.js CI',
    emoji: '📦',
    yaml: [
      'steps:',
      "  - label: Setup",
      "    command: \"mkdir -p demo-app && cd demo-app && npm init -y && npm pkg set scripts.lint='echo lint ok' scripts.test='echo 42 tests passed' scripts.build='mkdir -p dist && echo build ok' && npm install\"",
      "  - label: Lint",
      "    command: cd demo-app && npm run lint",
      "    depends_on: Setup",
      "  - label: Test",
      "    command: cd demo-app && npm run test",
      "    depends_on: Setup",
      "  - label: Build",
      "    command: cd demo-app && npm run build",
      "    depends_on: Lint,Test",
      "  - label: Package",
      "    command: echo Artifact ready && ls demo-app/dist",
      "    depends_on: Build",
    ].join('\n'),
  },
  {
    name: 'Python CI',
    emoji: '🐍',
    yaml: [
      'steps:',
      "  - label: Setup",
      "    command: \"mkdir -p demo-py/src demo-py/tests && echo 'def add(a,b): return a+b' > demo-py/src/utils.py && echo 'from src.utils import add' > demo-py/tests/test_utils.py && echo 'def test_add(): assert add(2,3)==5' >> demo-py/tests/test_utils.py && echo 'def test_sub(): assert add(10,-3)==7' >> demo-py/tests/test_utils.py && pip install pytest ruff --quiet\"",
      "  - label: Lint",
      "    command: cd demo-py && ruff check src/ || echo Lint ok",
      "    depends_on: Setup",
      "  - label: Type Check",
      "    command: python -m py_compile demo-py/src/utils.py && echo Syntax OK",
      "    depends_on: Setup",
      "  - label: Test",
      "    command: cd demo-py && python -m pytest tests/ -v",
      "    depends_on: Lint,Type Check",
      "  - label: Package",
      "    command: mkdir -p demo-py/dist && echo demo-py-1.0.0.whl > demo-py/dist/package.txt && echo Package ready",
      "    depends_on: Test",
    ].join('\n'),
  },
  {
    name: 'Go CI',
    emoji: '🐹',
    yaml: [
      'steps:',
      "  - label: Setup",
      "    command: \"mkdir -p demo-go/cmd/app && echo 'package main' > demo-go/cmd/app/main.go && echo 'func main() {}' >> demo-go/cmd/app/main.go && cd demo-go && go mod init demo-go 2>/dev/null || true\"",
      "  - label: Vet",
      "    command: cd demo-go && go vet ./...",
      "    depends_on: Setup",
      "  - label: Test",
      "    command: cd demo-go && go test ./... || echo No test files OK",
      "    depends_on: Vet",
      "  - label: Build",
      "    command: cd demo-go && mkdir -p bin && go build -o bin/app ./cmd/app && echo Binary ready",
      "    depends_on: Vet,Test",
    ].join('\n'),
  },
  {
    name: 'Docker Pipeline',
    emoji: '🐳',
    yaml: [
      'steps:',
      "  - label: Checkout",
      "    command: echo Workspace ready && ls -la",
      "  - label: Unit Tests",
      "    command: echo Running 128 unit tests... && sleep 1 && echo All tests passed",
      "    depends_on: Checkout",
      "  - label: Security Scan",
      "    command: echo Scanning image for CVEs... && sleep 1 && echo No critical issues found",
      "    depends_on: Checkout",
      "  - label: Build Image",
      "    command: echo docker build -t myapp:$BUILD_ID . && echo Image built",
      "    depends_on: Unit Tests,Security Scan",
      "  - label: Push Image",
      "    command: echo docker push registry/myapp:$BUILD_ID && echo Pushed",
      "    depends_on: Build Image",
      "  - label: Deploy",
      "    command: echo kubectl set image deployment/app app=myapp:$BUILD_ID && echo Deployed",
      "    depends_on: Push Image",
    ].join('\n'),
  },
  {
    name: 'Full-stack Deploy',
    emoji: '🚀',
    yaml: [
      'steps:',
      "  - label: Setup Backend",
      "    command: \"mkdir -p demo-fs/backend && echo 'x = 1 + 1' > demo-fs/backend/app.py && echo 'assert x == 2' >> demo-fs/backend/app.py && pip install pytest --quiet\"",
      "  - label: Setup Frontend",
      "    command: \"mkdir -p demo-fs/frontend && cd demo-fs/frontend && npm init -y && npm pkg set scripts.test='echo Frontend tests passed' scripts.build='mkdir -p dist && echo index.html > dist/index.html' && npm install\"",
      "  - label: Test Backend",
      "    command: cd demo-fs/backend && python app.py && echo Backend tests passed",
      "    depends_on: Setup Backend",
      "  - label: Test Frontend",
      "    command: cd demo-fs/frontend && npm test",
      "    depends_on: Setup Frontend",
      "  - label: Build Frontend",
      "    command: cd demo-fs/frontend && npm run build",
      "    depends_on: Test Frontend",
      "  - label: Build Docker",
      "    command: echo docker build -t app:$BUILD_ID . && echo Image built",
      "    depends_on: Test Backend,Build Frontend",
      "  - label: Deploy",
      "    command: echo helm upgrade --install app ./chart && echo Deployed",
      "    depends_on: Build Docker",
    ].join('\n'),
  },
]

// ─── Inner editor (needs ReactFlow context) ──────────────────────────────────
function PipelineEditorInner() {
  const navigate = useNavigate()
  const reactFlow = useReactFlow()

  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    updateNode,
    deleteNode,
    setSelectedNode,
    selectedNodeId,
    loadFromYAML,
    toYAML,
    pipelineName,
    setPipelineName,
    applyJobStatus,
    resetStatuses,
  } = usePipelineStore()

  // Panels
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'nodes' | 'yaml' | 'templates'>('nodes')

  // Build run
  const [branch, setBranch] = useState('main')
  const [repo, setRepo] = useState('')
  const [running, setRunning] = useState(false)
  const [buildResult, setBuildResult] = useState<{ id: number } | null>(null)
  const [buildError, setBuildError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // Node picker (floating, on double-click canvas)
  const [showPicker, setShowPicker] = useState(false)
  const [pickerPos, setPickerPos] = useState<{ x: number; y: number } | undefined>()
  const canvasClickPos = useRef<{ x: number; y: number }>({ x: 200, y: 200 })

  // YAML textarea
  const [yaml, setYaml] = useState('')
  const [yamlError, setYamlError] = useState('')

  // Load default template on mount
  useEffect(() => {
    loadFromYAML(TEMPLATES[0].yaml)
    setYaml(TEMPLATES[0].yaml)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Sync yaml textarea when nodes change
  useEffect(() => {
    if (activeTab === 'yaml') {
      setYaml(toYAML())
    }
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  // Subscribe to real-time build updates when a build is started
  useEffect(() => {
    if (!buildResult) return

    // Close any existing socket
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    const wsUrl = `ws://localhost:8000/ws/builds/${buildResult.id}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as Record<string, unknown>
        // Server sends { type: 'job_update', job: { label, status, ... } }
        // or { jobs: [...] } for full build snapshot
        if (msg.type === 'job_update' && msg.job) {
          const job = msg.job as Record<string, unknown>
          if (job.label && job.status) {
            applyJobStatus(String(job.label), String(job.status))
          }
        } else if (Array.isArray(msg.jobs)) {
          ;(msg.jobs as Record<string, unknown>[]).forEach(job => {
            if (job.label && job.status) {
              applyJobStatus(String(job.label), String(job.status))
            }
          })
        } else if (msg.status) {
          // Build-level status message — look for jobs array
          const jobs = msg.jobs as Record<string, unknown>[] | undefined
          if (Array.isArray(jobs)) {
            jobs.forEach(job => {
              if (job.label && job.status) {
                applyJobStatus(String(job.label), String(job.status))
              }
            })
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      // Silently ignore — backend may not be running or WS unavailable
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [buildResult, applyJobStatus])

  const selectedNode = nodes.find(n => n.id === selectedNodeId) ?? null

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_e, node) => {
      setSelectedNode(node.id)
      setRightOpen(true)
    },
    [setSelectedNode],
  )

  const handlePaneDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      const bounds = (e.currentTarget as HTMLElement).getBoundingClientRect()
      const rfPos = reactFlow.screenToFlowPosition({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      })
      canvasClickPos.current = rfPos
      setPickerPos({ x: e.clientX, y: e.clientY })
      setShowPicker(true)
    },
    [reactFlow],
  )

  // Slash key on canvas
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault()
        setPickerPos(undefined)
        setShowPicker(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handlePickerSelect = useCallback(
    (nt: NodeTypeDef) => {
      addNode(nt.type, canvasClickPos.current)
      setShowPicker(false)
      setRightOpen(true)
    },
    [addNode],
  )

  const handleYamlChange = useCallback(
    (value: string) => {
      setYaml(value)
      setYamlError('')
      try {
        loadFromYAML(value)
      } catch (e) {
        setYamlError(String(e))
      }
    },
    [loadFromYAML],
  )

  const handleRun = useCallback(async () => {
    setRunning(true)
    setBuildError(null)
    setBuildResult(null)
    resetStatuses()
    try {
      const y = toYAML()
      const build = await buildsApi.create({
        pipeline: y,
        branch: branch || 'main',
        repository: repo || undefined,
      })
      setBuildResult(build)
    } catch (e) {
      setBuildError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }, [toYAML, branch, repo, resetStatuses])

  const handleSave = useCallback(() => {
    const y = toYAML()
    const blob = new Blob([y], { type: 'text/yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${pipelineName.replace(/\s+/g, '-').toLowerCase()}.yml`
    a.click()
    URL.revokeObjectURL(url)
  }, [toYAML, pipelineName])

  const allNodeLabels = nodes.map(n => (n.data as Record<string, unknown>).label as string)

  // ─── Color scheme ──────────────────────────────────────────────────────────
  const PANEL_BG = '#0a0a0c'
  const PANEL_BORDER = '#1a1a1e'
  const TOOLBAR_H = 48

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: '100vh',
        background: '#070709',
        fontFamily: '"Geist", "Inter", system-ui, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div
        style={{
          height: TOOLBAR_H,
          background: PANEL_BG,
          borderBottom: `1px solid ${PANEL_BORDER}`,
          display: 'flex',
          alignItems: 'center',
          paddingInline: 12,
          gap: 8,
          flexShrink: 0,
          zIndex: 20,
        }}
      >
        {/* Pipeline name */}
        <input
          value={pipelineName}
          onChange={e => setPipelineName(e.target.value)}
          style={{
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#f4f4f5',
            fontSize: 14,
            fontWeight: 600,
            width: 200,
            fontFamily: '"Geist", system-ui, sans-serif',
          }}
        />

        <div style={{ flex: 1 }} />

        {/* Branch */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#111115', border: '1px solid #1f1f23', borderRadius: 7, padding: '4px 10px' }}>
          <GitBranch size={12} color="#52525b" />
          <input
            value={branch}
            onChange={e => setBranch(e.target.value)}
            placeholder="main"
            style={{ background: 'transparent', border: 'none', outline: 'none', color: '#a1a1aa', fontSize: 12, width: 70 }}
          />
        </div>

        {/* Repo */}
        <input
          value={repo}
          onChange={e => setRepo(e.target.value)}
          placeholder="repository URL (optional)"
          style={{
            background: '#111115',
            border: '1px solid #1f1f23',
            borderRadius: 7,
            padding: '4px 10px',
            color: '#a1a1aa',
            fontSize: 12,
            width: 200,
            outline: 'none',
          }}
        />

        {/* Save */}
        <button
          onClick={handleSave}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: '#111115',
            border: '1px solid #1f1f23',
            borderRadius: 7,
            color: '#a1a1aa',
            fontSize: 12,
            padding: '5px 12px',
            cursor: 'pointer',
            transition: 'all 0.1s',
          }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = '#3f3f46')}
          onMouseLeave={e => (e.currentTarget.style.borderColor = '#1f1f23')}
        >
          <Save size={13} />
          Save YAML
        </button>

        {/* Run */}
        <button
          onClick={handleRun}
          disabled={running}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: running ? '#1a3a1a' : '#166534',
            border: '1px solid',
            borderColor: running ? '#15803d50' : '#15803d',
            borderRadius: 7,
            color: running ? '#4ade80' : '#bbf7d0',
            fontSize: 12,
            fontWeight: 600,
            padding: '5px 14px',
            cursor: running ? 'not-allowed' : 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {running ? (
            <>
              <span
                style={{
                  width: 12,
                  height: 12,
                  border: '2px solid #4ade8030',
                  borderTop: '2px solid #4ade80',
                  borderRadius: '50%',
                  animation: 'spin 0.7s linear infinite',
                  flexShrink: 0,
                }}
              />
              Running…
            </>
          ) : (
            <>
              <Play size={13} fill="currentColor" />
              Run Pipeline
            </>
          )}
        </button>

        {buildResult && (
          <button
            onClick={() => navigate(`/builds/${buildResult.id}`)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'transparent',
              border: 'none',
              color: '#4ade80',
              fontSize: 12,
              cursor: 'pointer',
              textDecoration: 'underline',
            }}
          >
            Build #{buildResult.id} <ExternalLink size={11} />
          </button>
        )}

        {buildError && (
          <span style={{ color: '#f87171', fontSize: 11, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {buildError}
          </span>
        )}
      </div>

      {/* ── Main area ────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Left panel ─────────────────────────────────────────────────── */}
        <div
          style={{
            width: leftOpen ? 260 : 0,
            transition: 'width 0.2s ease',
            background: PANEL_BG,
            borderRight: `1px solid ${PANEL_BORDER}`,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          {/* Tab bar */}
          <div
            style={{
              display: 'flex',
              borderBottom: `1px solid ${PANEL_BORDER}`,
              flexShrink: 0,
            }}
          >
            {([['nodes', Layers, 'Nodes'], ['templates', LayoutTemplate, 'Templates'], ['yaml', Code2, 'YAML']] as const).map(
              ([tab, Icon, label]) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab as typeof activeTab)}
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 3,
                    padding: '8px 4px',
                    background: 'transparent',
                    border: 'none',
                    borderBottom: `2px solid ${activeTab === tab ? '#a78bfa' : 'transparent'}`,
                    color: activeTab === tab ? '#c4b5fd' : '#3f3f46',
                    cursor: 'pointer',
                    fontSize: 9.5,
                    letterSpacing: '0.05em',
                    transition: 'all 0.1s',
                  }}
                >
                  <Icon size={14} />
                  {label}
                </button>
              ),
            )}
          </div>

          {/* Tab content */}
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {activeTab === 'nodes' && (
              <NodePicker
                embedded
                onSelect={nt => {
                  addNode(nt.type)
                  setRightOpen(true)
                }}
                onClose={() => {}}
              />
            )}

            {activeTab === 'templates' && (
              <div
                style={{
                  padding: 12,
                  overflowY: 'auto',
                  flex: 1,
                  scrollbarWidth: 'thin',
                  scrollbarColor: '#27272a transparent',
                }}
              >
                <p style={{ color: '#52525b', fontSize: 11, marginBottom: 12 }}>
                  Click to load a template into the editor
                </p>
                {TEMPLATES.map(t => (
                  <div
                    key={t.name}
                    onClick={() => { loadFromYAML(t.yaml); setYaml(t.yaml); setPipelineName(t.name) }}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 8,
                      border: '1px solid #1f1f23',
                      marginBottom: 8,
                      cursor: 'pointer',
                      transition: 'all 0.1s',
                      background: 'transparent',
                    }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = '#3f3f46'; (e.currentTarget as HTMLElement).style.background = '#111115' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = '#1f1f23'; (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ fontSize: 16 }}>{t.emoji}</span>
                      <span style={{ color: '#e4e4e7', fontSize: 12.5, fontWeight: 600 }}>{t.name}</span>
                    </div>
                    <span style={{ color: '#52525b', fontSize: 10.5 }}>
                      {t.yaml.split('\n').filter(l => l.includes('- label:')).length} steps
                    </span>
                  </div>
                ))}
              </div>
            )}

            {activeTab === 'yaml' && (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 12, gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#52525b', fontSize: 10.5 }}>Edit YAML ↔ updates graph</span>
                  <button
                    onClick={() => { const y = toYAML(); setYaml(y) }}
                    style={{ fontSize: 10, color: '#a78bfa', background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    Sync from graph ↻
                  </button>
                </div>
                {yamlError && <div style={{ color: '#f87171', fontSize: 10, background: '#3d0000', padding: '4px 8px', borderRadius: 4 }}>{yamlError}</div>}
                <textarea
                  value={yaml}
                  onChange={e => handleYamlChange(e.target.value)}
                  spellCheck={false}
                  style={{
                    flex: 1,
                    background: '#0a0a0c',
                    color: '#86efac',
                    border: '1px solid #1f1f23',
                    borderRadius: 6,
                    padding: 10,
                    fontFamily: '"Geist Mono", ui-monospace, monospace',
                    fontSize: 11,
                    outline: 'none',
                    resize: 'none',
                    lineHeight: 1.6,
                  }}
                />
              </div>
            )}
          </div>
        </div>

        {/* ── Toggle left panel ──────────────────────────────────────────── */}
        <button
          onClick={() => setLeftOpen(!leftOpen)}
          style={{
            position: 'absolute',
            left: leftOpen ? 252 : 0,
            top: '50%',
            transform: 'translateY(-50%)',
            zIndex: 30,
            background: PANEL_BG,
            border: `1px solid ${PANEL_BORDER}`,
            borderLeft: leftOpen ? `1px solid ${PANEL_BORDER}` : 'none',
            borderRadius: leftOpen ? '0 6px 6px 0' : '0 6px 6px 0',
            color: '#52525b',
            cursor: 'pointer',
            padding: '6px 4px',
            display: 'flex',
            alignItems: 'center',
            transition: 'left 0.2s',
          }}
        >
          {leftOpen ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}
        </button>

        {/* ── Canvas ─────────────────────────────────────────────────────── */}
        <div style={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={() => { setSelectedNode(null) }}
            onDoubleClick={handlePaneDoubleClick as unknown as React.MouseEventHandler}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            attributionPosition="bottom-left"
            deleteKeyCode={['Backspace', 'Delete']}
            defaultEdgeOptions={{
              type: 'smoothstep',
              style: { stroke: '#3f3f46', strokeWidth: 2 },
            }}
            style={{ background: '#070709' }}
          >
            <Background color="#1a1a1e" gap={20} size={1} variant={'dots' as never} />
            <Controls
              style={{
                background: PANEL_BG,
                border: `1px solid ${PANEL_BORDER}`,
                borderRadius: 8,
              }}
            />
            <MiniMap
              nodeColor={n => {
                const s = (n.data as Record<string, unknown>).status as string ?? 'pending'
                return { pending: '#27272a', running: '#3b82f6', passed: '#22c55e', failed: '#ef4444' }[s] ?? '#27272a'
              }}
              style={{ background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`, borderRadius: 8 }}
              maskColor="rgba(0,0,0,0.6)"
            />
            <Panel position="top-right" style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => { setPickerPos(undefined); setShowPicker(true) }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  background: '#111115',
                  border: '1px solid #1f1f23',
                  borderRadius: 7,
                  color: '#a78bfa',
                  fontSize: 12,
                  padding: '6px 12px',
                  cursor: 'pointer',
                }}
              >
                <Plus size={13} /> Add Node
              </button>
            </Panel>
            <Panel position="bottom-left" style={{ marginBottom: 8 }}>
              <div
                style={{
                  background: PANEL_BG,
                  border: `1px solid ${PANEL_BORDER}`,
                  borderRadius: 8,
                  padding: '6px 12px',
                  color: '#3f3f46',
                  fontSize: 10.5,
                  display: 'flex',
                  gap: 16,
                  alignItems: 'center',
                }}
              >
                <span>
                  <kbd style={{ color: '#52525b', fontFamily: 'monospace' }}>/</kbd> add node
                </span>
                <span>
                  <kbd style={{ color: '#52525b', fontFamily: 'monospace' }}>dbl-click</kbd> canvas
                </span>
                <span>{nodes.length} steps</span>
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {/* ── Toggle right panel ─────────────────────────────────────────── */}
        {!rightOpen && selectedNode && (
          <button
            onClick={() => setRightOpen(true)}
            style={{
              position: 'absolute',
              right: 0,
              top: '50%',
              transform: 'translateY(-50%)',
              zIndex: 30,
              background: PANEL_BG,
              border: `1px solid ${PANEL_BORDER}`,
              borderRadius: '6px 0 0 6px',
              color: '#52525b',
              cursor: 'pointer',
              padding: '6px 4px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Settings size={13} />
          </button>
        )}

        {/* ── Right properties panel ─────────────────────────────────────── */}
        <div
          style={{
            width: rightOpen ? 300 : 0,
            transition: 'width 0.2s ease',
            background: PANEL_BG,
            borderLeft: `1px solid ${PANEL_BORDER}`,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            flexShrink: 0,
          }}
        >
          <NodeProperties
            node={selectedNode}
            onUpdate={(id, data) => updateNode(id, data)}
            onDelete={id => deleteNode(id)}
            onClose={() => setRightOpen(false)}
            allNodeLabels={allNodeLabels}
          />
        </div>
      </div>

      {/* ── Floating node picker ─────────────────────────────────────────── */}
      {showPicker && (
        <NodePicker
          position={pickerPos}
          onSelect={handlePickerSelect}
          onClose={() => setShowPicker(false)}
        />
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .react-flow__attribution { display: none; }
        .react-flow__controls button {
          background: #0a0a0c !important;
          border-color: #1a1a1e !important;
          color: #52525b !important;
        }
        .react-flow__controls button:hover {
          background: #111115 !important;
          color: #a1a1aa !important;
        }
      `}</style>
    </div>
  )
}

// ─── Export with provider ─────────────────────────────────────────────────────
export default function PipelineEditor() {
  return (
    <ReactFlowProvider>
      <PipelineEditorInner />
    </ReactFlowProvider>
  )
}
