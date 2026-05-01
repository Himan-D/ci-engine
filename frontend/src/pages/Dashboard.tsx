import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Hammer, Bot, CheckCircle2, XCircle, TrendingUp, Plus } from 'lucide-react'
import { buildsApi, agentsApi, type Build, type Agent } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { formatDistanceToNow } from 'date-fns'

interface Stats {
  total: number
  passed: number
  failed: number
  running: number
  successRate: number
  agents: number
  onlineAgents: number
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = false,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-4">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${accent ? 'bg-brand-500/15 border border-brand-500/30' : 'bg-zinc-800 border border-zinc-700'}`}>
          <Icon size={16} className={accent ? 'text-brand-400' : 'text-zinc-400'} />
        </div>
      </div>
      <div className="text-2xl font-display font-bold text-zinc-100 tabular-nums">{value}</div>
      <div className="text-sm text-zinc-500 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-zinc-600 mt-1">{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [builds, setBuilds]   = useState<Build[]>([])
  const [agents, setAgents]   = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats]     = useState<Stats>({ total: 0, passed: 0, failed: 0, running: 0, successRate: 0, agents: 0, onlineAgents: 0 })

  useEffect(() => {
    Promise.all([
      buildsApi.list(20),
      agentsApi.list().catch(() => [] as Agent[]),
    ]).then(([b, a]) => {
      setBuilds(b)
      setAgents(a)
      const passed  = b.filter(x => x.status === 'passed').length
      const failed  = b.filter(x => x.status === 'failed').length
      const running = b.filter(x => x.status === 'running').length
      const done    = passed + failed
      setStats({
        total:       b.length,
        passed,
        failed,
        running,
        successRate: done > 0 ? Math.round((passed / done) * 100) : 0,
        agents:      a.length,
        onlineAgents: a.filter(x => x.status !== 'offline').length,
      })
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  return (
    <div className="p-6 max-w-6xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-display font-bold text-zinc-100">Dashboard</h1>
          <p className="text-sm text-zinc-500 mt-0.5">Overview of your CI/CD pipeline</p>
        </div>
        <button
          onClick={() => navigate('/pipeline')}
          className="btn-primary"
        >
          <Plus size={15} />
          New Build
        </button>
      </div>

      {/* Stats */}
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse bg-zinc-900" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard icon={Hammer}       label="Total Builds"   value={stats.total}           accent />
          <StatCard icon={TrendingUp}   label="Success Rate"   value={`${stats.successRate}%`} sub={`${stats.passed} passed, ${stats.failed} failed`} />
          <StatCard icon={CheckCircle2} label="Running Now"    value={stats.running}         sub={stats.running > 0 ? 'In progress' : 'All idle'} />
          <StatCard icon={Bot}          label="Agents"         value={`${stats.onlineAgents}/${stats.agents}`} sub="online / total" />
        </div>
      )}

      {/* Recent Builds */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-300">Recent Builds</h2>
          <button onClick={() => navigate('/builds')} className="text-xs text-zinc-500 hover:text-brand-400 transition-colors">
            View all →
          </button>
        </div>

        {loading ? (
          <div className="divide-y divide-zinc-800">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="px-5 py-3.5 flex items-center gap-4 animate-pulse">
                <div className="w-10 h-4 bg-zinc-800 rounded" />
                <div className="flex-1 h-4 bg-zinc-800 rounded" />
                <div className="w-20 h-4 bg-zinc-800 rounded" />
              </div>
            ))}
          </div>
        ) : builds.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <Hammer size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-sm text-zinc-500">No builds yet.</p>
            <button onClick={() => navigate('/pipeline')} className="btn-primary btn-sm mt-4 mx-auto">
              Create your first build
            </button>
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/60">
            {builds.slice(0, 10).map(build => (
              <button
                key={build.id}
                onClick={() => navigate(`/builds/${build.id}`)}
                className="w-full text-left px-5 py-3.5 flex items-center gap-4 hover:bg-zinc-800/30 transition-colors group"
              >
                <span className="text-xs font-mono text-zinc-600 w-10 flex-shrink-0">
                  #{build.id}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-300 truncate font-medium group-hover:text-zinc-100 transition-colors">
                    {build.repository || 'pipeline'}
                  </div>
                  {build.branch && (
                    <div className="text-xs text-zinc-600 mt-0.5 font-mono">{build.branch}</div>
                  )}
                </div>
                <StatusBadge status={build.status} size="sm" />
                <span className="text-xs text-zinc-600 w-24 text-right flex-shrink-0">
                  {formatDistanceToNow(new Date(build.created_at), { addSuffix: true })}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Active Agents */}
      {agents.length > 0 && (
        <div className="mt-4 card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
            <h2 className="text-sm font-semibold text-zinc-300">Agent Fleet</h2>
            <button onClick={() => navigate('/agents')} className="text-xs text-zinc-500 hover:text-brand-400 transition-colors">
              Manage agents →
            </button>
          </div>
          <div className="flex gap-2 p-4 flex-wrap">
            {agents.map(a => (
              <div key={a.id} className="flex items-center gap-1.5 px-2.5 py-1.5 bg-zinc-800/50 rounded-lg border border-zinc-800">
                <span className={`status-dot ${
                  a.status === 'idle'     ? 'bg-green-400' :
                  a.status === 'busy'     ? 'bg-blue-400 animate-pulse-slow' :
                  a.status === 'draining' ? 'bg-amber-400' :
                  'bg-zinc-600'
                }`} />
                <span className="text-xs text-zinc-300 font-medium">{a.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Success-rate bar visual */}
      {stats.total > 0 && (
        <div className="mt-4 card p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-zinc-400">Build success rate</span>
            <span className="text-sm font-display font-bold text-zinc-200">{stats.successRate}%</span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 rounded-full transition-all duration-700"
              style={{ width: `${stats.successRate}%` }}
            />
          </div>
          <div className="flex justify-between mt-2">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 size={12} className="text-green-400" />
              <span className="text-xs text-zinc-500">{stats.passed} passed</span>
            </div>
            <div className="flex items-center gap-1.5">
              <XCircle size={12} className="text-red-400" />
              <span className="text-xs text-zinc-500">{stats.failed} failed</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
