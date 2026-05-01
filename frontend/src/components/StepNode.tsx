import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { StepStatus } from '../types/pipeline'

interface StepNodeData {
  label: string
  command?: string
  status?: StepStatus
}

const STATUS_COLOR: Record<string, { dot: string; ring: string; text: string }> = {
  pending:   { dot: '#52525b', ring: '#3f3f46',  text: '#71717a' },
  running:   { dot: '#3b82f6', ring: '#1d4ed8',  text: '#93c5fd' },
  passed:    { dot: '#22c55e', ring: '#15803d',  text: '#86efac' },
  failed:    { dot: '#ef4444', ring: '#b91c1c',  text: '#fca5a5' },
  skipped:   { dot: '#4b5563', ring: '#374151',  text: '#6b7280' },
  cancelled: { dot: '#4b5563', ring: '#374151',  text: '#6b7280' },
}

function StepNode({ data, selected }: NodeProps) {
  const d = data as unknown as StepNodeData
  const status = d?.status ?? 'pending'
  const colors = STATUS_COLOR[status] ?? STATUS_COLOR.pending

  return (
    <div
      style={{
        padding: '12px 14px',
        borderRadius: '10px',
        background: '#18181b',
        border: `1.5px solid ${selected ? colors.ring : '#27272a'}`,
        minWidth: '180px',
        boxShadow: selected ? `0 0 0 3px ${colors.ring}40` : '0 2px 8px rgba(0,0,0,0.4)',
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: '#3f3f46', width: 8, height: 8, border: '1.5px solid #52525b' }}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: colors.dot,
            flexShrink: 0,
            boxShadow: status === 'running' ? `0 0 6px ${colors.dot}` : 'none',
          }}
        />
        <span style={{ color: '#f4f4f5', fontWeight: 600, fontSize: 13, fontFamily: 'Syne, system-ui, sans-serif' }}>
          {d.label}
        </span>
      </div>

      {d.command && (
        <div
          style={{
            fontSize: 10.5,
            color: '#71717a',
            fontFamily: '"JetBrains Mono", ui-monospace, monospace',
            maxWidth: 160,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            marginBottom: 4,
          }}
        >
          {d.command}
        </div>
      )}

      <div style={{ fontSize: 10.5, color: colors.text, fontWeight: 500, textTransform: 'capitalize' }}>
        {status}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: '#3f3f46', width: 8, height: 8, border: '1.5px solid #52525b' }}
      />
    </div>
  )
}

export default memo(StepNode)
