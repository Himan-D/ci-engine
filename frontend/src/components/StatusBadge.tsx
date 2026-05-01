import type { BuildStatus, JobStatus, AgentStatus } from '../api/client'

type Status = BuildStatus | JobStatus | AgentStatus

const CONFIG: Record<string, { label: string; dot: string; text: string; bg: string; pulse?: boolean }> = {
  pending:   { label: 'Pending',   dot: 'bg-zinc-500',  text: 'text-zinc-400',  bg: 'bg-zinc-800/60' },
  running:   { label: 'Running',   dot: 'bg-blue-400',  text: 'text-blue-300',  bg: 'bg-blue-900/30',  pulse: true },
  passed:    { label: 'Passed',    dot: 'bg-green-400', text: 'text-green-300', bg: 'bg-green-900/30' },
  failed:    { label: 'Failed',    dot: 'bg-red-400',   text: 'text-red-300',   bg: 'bg-red-900/30'  },
  cancelled: { label: 'Cancelled', dot: 'bg-zinc-500',  text: 'text-zinc-400',  bg: 'bg-zinc-800/60' },
  skipped:      { label: 'Skipped',     dot: 'bg-zinc-600',  text: 'text-zinc-500',  bg: 'bg-zinc-800/40' },
  soft_failed:  { label: 'Soft Failed', dot: 'bg-amber-400', text: 'text-amber-300', bg: 'bg-amber-900/30' },
  assigned:     { label: 'Assigned',    dot: 'bg-indigo-400',text: 'text-indigo-300',bg: 'bg-indigo-900/30' },
  blocked:      { label: 'Blocked',     dot: 'bg-zinc-500',  text: 'text-zinc-400',  bg: 'bg-zinc-800/60' },
  idle:      { label: 'Idle',      dot: 'bg-green-400', text: 'text-green-300', bg: 'bg-green-900/30' },
  busy:      { label: 'Busy',      dot: 'bg-blue-400',  text: 'text-blue-300',  bg: 'bg-blue-900/30',  pulse: true },
  offline:   { label: 'Offline',   dot: 'bg-zinc-600',  text: 'text-zinc-500',  bg: 'bg-zinc-800/40' },
  draining:  { label: 'Draining',  dot: 'bg-amber-400', text: 'text-amber-300', bg: 'bg-amber-900/30' },
}

interface Props {
  status: Status
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'md' }: Props) {
  const cfg = CONFIG[status] ?? CONFIG['pending']
  const px  = size === 'sm' ? 'px-2 py-0.5 text-xs gap-1.5' : 'px-2.5 py-1 text-xs gap-2'

  return (
    <span className={`inline-flex items-center rounded-full font-medium ${px} ${cfg.bg} ${cfg.text}`}>
      <span className={`status-dot ${cfg.dot} ${cfg.pulse ? 'animate-pulse-slow' : ''}`} />
      {cfg.label}
    </span>
  )
}

export function StatusDot({ status }: { status: Status }) {
  const cfg = CONFIG[status] ?? CONFIG['pending']
  return (
    <span className={`status-dot ${cfg.dot} ${cfg.pulse ? 'animate-pulse-slow' : ''}`} />
  )
}
