import { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import { StepStatus } from '../types/pipeline';

interface StepNodeData {
  label: string;
  command?: string;
  status?: StepStatus;
  depends_on?: string[];
}

const statusColors: Record<StepStatus, string> = {
  pending: '#6b7280',
  running: '#3b82f6',
  passed: '#22c55e',
  failed: '#ef4444',
  skipped: '#9ca3af',
};

const statusLabels: Record<StepStatus, string> = {
  pending: 'Pending',
  running: 'Running...',
  passed: 'Passed',
  failed: 'Failed',
  skipped: 'Skipped',
};

function StepNode({ data, selected }: NodeProps) {
  const stepData = data as StepNodeData;
  const status = stepData.status || 'pending';
  const color = statusColors[status];

  return (
    <div
      style={{
        padding: '12px 16px',
        borderRadius: '8px',
        background: '#1e1e1e',
        border: selected ? `2px solid ${color}` : `2px solid #333`,
        minWidth: '180px',
        boxShadow: selected ? `0 0 0 2px ${color}40` : 'none',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: '#555', width: 8, height: 8 }}
      />
      
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: color,
          }}
        />
        <div style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>
          {stepData.label}
        </div>
      </div>
      
      {stepData.command && (
        <div
          style={{
            marginTop: 8,
            fontSize: 11,
            color: '#888',
            fontFamily: 'monospace',
            maxWidth: 150,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {stepData.command}
        </div>
      )}
      
      <div
        style={{
          marginTop: 6,
          fontSize: 11,
          color: color,
          fontWeight: 500,
        }}
      >
        {statusLabels[status]}
      </div>
      
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: '#555', width: 8, height: 8 }}
      />
    </div>
  );
}

export default memo(StepNode);