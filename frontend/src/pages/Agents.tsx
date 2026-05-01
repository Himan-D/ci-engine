import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, Bot, Cpu, HardDrive, Clock } from 'lucide-react'
import { agentsApi, type Agent } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { formatDistanceToNow } from 'date-fns'

export default function Agents() {
  const [agents, setAgents]   = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [draining, setDraining] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    agentsApi.list()
      .then(a => { setAgents(a); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 15_000)
    return () => clearInterval(interval)
  }, [load])

  const toggleDrain = async (agent: Agent) => {
    setDraining(agent.id)
    try {
      if (agent.status === 'draining') {
        await agentsApi.undrain(agent.id)
      } else {
        await agentsApi.drain(agent.id)
      }
      load()
    } finally {
      setDraining(null)
    }
  }

  const online   = agents.filter(a => a.status !== 'offline').length
  const busy     = agents.filter(a => a.status === 'busy').length
  const offline  = agents.filter(a => a.status === 'offline').length

  return (
    <div className="p-6 max-w-6xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-display font-bold text-zinc-100">Agents</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            {online} online · {busy} busy · {offline} offline
          </p>
        </div>
        <button onClick={load} className="btn-secondary btn-sm" disabled={loading}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {[
          { label: 'Total',   value: agents.length, color: 'text-zinc-300' },
          { label: 'Online',  value: online,        color: 'text-green-400' },
          { label: 'Busy',    value: busy,          color: 'text-blue-400' },
        ].map(s => (
          <div key={s.label} className="card px-4 py-3 flex items-center justify-between">
            <span className="text-sm text-zinc-500">{s.label}</span>
            <span className={`text-xl font-display font-bold tabular-nums ${s.color}`}>{s.value}</span>
          </div>
        ))}
      </div>

      {/* Agent grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="card p-5 h-40 animate-pulse" />
          ))}
        </div>
      ) : agents.length === 0 ? (
        <div className="card py-16 text-center">
          <Bot size={36} className="text-zinc-700 mx-auto mb-3" />
          <p className="text-sm text-zinc-500">No agents registered</p>
          <p className="text-xs text-zinc-600 mt-1">
            Run <code className="font-mono bg-zinc-800 px-1 rounded">ci-engine agent start</code> to connect one
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map(agent => (
            <div key={agent.id} className="card p-5 space-y-4">
              {/* Name + status */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    agent.status === 'offline' ? 'bg-zinc-800' : 'bg-zinc-800 border border-zinc-700'
                  }`}>
                    <Bot size={14} className={
                      agent.status === 'busy'     ? 'text-blue-400' :
                      agent.status === 'idle'     ? 'text-green-400' :
                      agent.status === 'draining' ? 'text-amber-400' :
                      'text-zinc-600'
                    } />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-zinc-200 truncate">{agent.name}</div>
                    {agent.hostname && (
                      <div className="text-xs text-zinc-600 font-mono truncate">{agent.hostname}</div>
                    )}
                  </div>
                </div>
                <StatusBadge status={agent.status} size="sm" />
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex items-center gap-1.5 text-zinc-500">
                  <Cpu size={11} />
                  <span>{agent.current_jobs} job{agent.current_jobs !== 1 ? 's' : ''}</span>
                </div>
                {agent.last_seen && (
                  <div className="flex items-center gap-1.5 text-zinc-600">
                    <Clock size={11} />
                    <span>{formatDistanceToNow(new Date(agent.last_seen), { addSuffix: true })}</span>
                  </div>
                )}
              </div>

              {/* Tags */}
              {agent.tags && agent.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {agent.tags.map(tag => (
                    <span
                      key={tag}
                      className="text-xs px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded border border-zinc-700/50 font-mono"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {/* Actions */}
              {agent.status !== 'offline' && (
                <div className="pt-1 border-t border-zinc-800">
                  <button
                    onClick={() => toggleDrain(agent)}
                    disabled={draining === agent.id}
                    className={`btn btn-sm w-full justify-center ${
                      agent.status === 'draining'
                        ? 'btn-secondary'
                        : 'btn-ghost text-amber-500 hover:bg-amber-900/20'
                    } disabled:opacity-50`}
                  >
                    <HardDrive size={12} />
                    {draining === agent.id
                      ? 'Working…'
                      : agent.status === 'draining'
                      ? 'Undrain'
                      : 'Drain'
                    }
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
