import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { getNodeType } from '../../data/nodeTypes'

export interface PipelineNodeData {
  label: string
  command?: string
  nodeType?: string
  status?: string
  continueOnError?: boolean
  timeout?: number
}

const STATUS = {
  pending:  { dot: '#52525b', ring: '#3f3f46', text: '#71717a', glow: 'none' },
  assigned: { dot: '#a78bfa', ring: '#7c3aed', text: '#c4b5fd', glow: 'none' },
  running:  { dot: '#3b82f6', ring: '#1d4ed8', text: '#93c5fd', glow: '0 0 8px #3b82f6' },
  passed:   { dot: '#22c55e', ring: '#15803d', text: '#86efac', glow: 'none' },
  failed:   { dot: '#ef4444', ring: '#b91c1c', text: '#fca5a5', glow: '0 0 6px #ef4444' },
  skipped:  { dot: '#4b5563', ring: '#374151', text: '#6b7280', glow: 'none' },
  blocked:  { dot: '#f59e0b', ring: '#d97706', text: '#fcd34d', glow: '0 0 6px #f59e0b' },
  cancelled:{ dot: '#4b5563', ring: '#374151', text: '#6b7280', glow: 'none' },
} as const

export function PipelineNode({ data, selected }: NodeProps) {
  const d = data as unknown as PipelineNodeData
  const status = (d.status as string) ?? 'pending'
  const s = STATUS[status as keyof typeof STATUS] ?? STATUS.pending
  const nt = getNodeType(d.nodeType ?? 'command')

  // Waiting/block nodes have no handles for commands
  const isWait = d.nodeType === 'wait'

  return (
    <div
      style={{
        position: 'relative',
        padding: '10px 14px 10px 12px',
        borderRadius: 12,
        background: '#18181b',
        border: `1.5px solid ${selected ? nt.color : '#2d2d30'}`,
        minWidth: 200,
        maxWidth: 260,
        boxShadow: selected
          ? `0 0 0 3px ${nt.color}30, 0 4px 24px rgba(0,0,0,0.5)`
          : '0 2px 12px rgba(0,0,0,0.35)',
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
    >
      {/* Color accent bar on left */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 8,
          bottom: 8,
          width: 3,
          borderRadius: 2,
          background: nt.color,
        }}
      />

      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: '#3f3f46',
          width: 8,
          height: 8,
          border: `1.5px solid ${s.dot}`,
          top: -4,
        }}
      />

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
        {/* emoji icon */}
        <span style={{ fontSize: 14, lineHeight: 1, flexShrink: 0 }}>{nt.emoji}</span>

        {/* label */}
        <span
          style={{
            color: '#f4f4f5',
            fontWeight: 600,
            fontSize: 12.5,
            fontFamily: '"Geist", "Inter", system-ui, sans-serif',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {d.label}
        </span>

        {/* status dot */}
        <div
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: s.dot,
            flexShrink: 0,
            boxShadow: s.glow,
          }}
        />
      </div>

      {/* Node type badge */}
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          background: `${nt.color}18`,
          border: `1px solid ${nt.color}35`,
          borderRadius: 4,
          padding: '1px 6px',
          marginBottom: d.command ? 5 : 0,
        }}
      >
        <span
          style={{
            fontSize: 10,
            color: nt.color,
            fontFamily: '"Geist Mono", ui-monospace, monospace',
            fontWeight: 500,
          }}
        >
          {nt.label}
        </span>
      </div>

      {/* command preview */}
      {d.command && !isWait && (
        <div
          style={{
            fontSize: 10.5,
            color: '#52525b',
            fontFamily: '"Geist Mono", ui-monospace, monospace',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: 220,
            marginTop: 2,
          }}
        >
          {d.command.split('\n')[0]}
        </div>
      )}

      {/* status text */}
      <div
        style={{
          marginTop: 5,
          fontSize: 10,
          color: s.text,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      >
        {isWait ? '⏸ waiting for approval' : status}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          background: '#3f3f46',
          width: 8,
          height: 8,
          border: `1.5px solid ${s.dot}`,
          bottom: -4,
        }}
      />
    </div>
  )
}

export default memo(PipelineNode)
