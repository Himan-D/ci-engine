import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, Plus, Hammer, XCircle } from 'lucide-react'
import { buildsApi, type Build, type BuildStatus } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { formatDistanceToNow } from 'date-fns'

const FILTERS: { label: string; value: 'all' | BuildStatus }[] = [
  { label: 'All',       value: 'all'       },
  { label: 'Running',   value: 'running'   },
  { label: 'Passed',    value: 'passed'    },
  { label: 'Failed',    value: 'failed'    },
  { label: 'Pending',   value: 'pending'   },
]

export default function Builds() {
  const navigate = useNavigate()
  const [builds, setBuilds]   = useState<Build[]>([])
  const [filter, setFilter]   = useState<'all' | BuildStatus>('all')
  const [loading, setLoading] = useState(true)
  const [cancelling, setCancelling] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    buildsApi.list(100)
      .then(b => { setBuilds(b); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleCancel = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    setCancelling(id)
    try {
      await buildsApi.cancel(id)
      load()
    } finally {
      setCancelling(null)
    }
  }

  const visible = filter === 'all' ? builds : builds.filter(b => b.status === filter)

  return (
    <div className="p-6 max-w-6xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-display font-bold text-zinc-100">Builds</h1>
          <p className="text-sm text-zinc-500 mt-0.5">{builds.length} builds total</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="btn-secondary btn-sm" disabled={loading}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button onClick={() => navigate('/pipeline')} className="btn-primary btn-sm">
            <Plus size={13} />
            New Build
          </button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-4 bg-zinc-900/60 p-1 rounded-lg w-fit border border-zinc-800">
        {FILTERS.map(f => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              filter === f.value
                ? 'bg-zinc-800 text-zinc-100 shadow-sm'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {f.label}
            {f.value !== 'all' && (
              <span className="ml-1.5 text-zinc-600">
                {builds.filter(b => b.status === f.value).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[48px_1fr_120px_100px_140px_80px] gap-4 px-5 py-3 bg-zinc-900/80 border-b border-zinc-800 text-xs font-medium text-zinc-500 uppercase tracking-wider">
          <div>#</div>
          <div>Pipeline / Repository</div>
          <div>Branch</div>
          <div>Status</div>
          <div>Created</div>
          <div className="text-right">Actions</div>
        </div>

        {loading ? (
          <div className="divide-y divide-zinc-800/60">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="grid grid-cols-[48px_1fr_120px_100px_140px_80px] gap-4 px-5 py-4 animate-pulse">
                <div className="h-4 bg-zinc-800 rounded" />
                <div className="h-4 bg-zinc-800 rounded w-3/4" />
                <div className="h-4 bg-zinc-800 rounded w-1/2" />
                <div className="h-4 bg-zinc-800 rounded w-16" />
                <div className="h-4 bg-zinc-800 rounded w-24" />
                <div className="h-4 bg-zinc-800 rounded w-8 ml-auto" />
              </div>
            ))}
          </div>
        ) : visible.length === 0 ? (
          <div className="py-16 text-center">
            <Hammer size={32} className="text-zinc-700 mx-auto mb-3" />
            <p className="text-sm text-zinc-500">No builds found</p>
            {filter !== 'all' && (
              <button onClick={() => setFilter('all')} className="text-xs text-brand-400 mt-2 hover:underline">
                Clear filter
              </button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/40">
            {visible.map(build => (
              <div
                key={build.id}
                onClick={() => navigate(`/builds/${build.id}`)}
                className="grid grid-cols-[48px_1fr_120px_100px_140px_80px] gap-4 px-5 py-3.5 items-center cursor-pointer hover:bg-zinc-800/30 transition-colors group"
              >
                {/* ID */}
                <span className="text-xs font-mono text-zinc-600 group-hover:text-zinc-500">
                  #{build.id}
                </span>

                {/* Pipeline */}
                <div className="min-w-0">
                  <div className="text-sm text-zinc-300 font-medium truncate group-hover:text-zinc-100 transition-colors">
                    {build.repository || 'pipeline'}
                  </div>
                  {build.commit_sha && (
                    <div className="text-xs font-mono text-zinc-600 mt-0.5 truncate">
                      {build.commit_sha.slice(0, 8)}
                    </div>
                  )}
                </div>

                {/* Branch */}
                <div>
                  {build.branch ? (
                    <span className="text-xs font-mono text-zinc-400 bg-zinc-800/60 px-2 py-0.5 rounded border border-zinc-700/50 truncate block max-w-full">
                      {build.branch}
                    </span>
                  ) : (
                    <span className="text-xs text-zinc-700">—</span>
                  )}
                </div>

                {/* Status */}
                <StatusBadge status={build.status} size="sm" />

                {/* Created */}
                <span className="text-xs text-zinc-600">
                  {formatDistanceToNow(new Date(build.created_at), { addSuffix: true })}
                </span>

                {/* Actions */}
                <div className="flex justify-end">
                  {(build.status === 'running' || build.status === 'pending') && (
                    <button
                      onClick={e => handleCancel(e, build.id)}
                      disabled={cancelling === build.id}
                      className="p-1.5 text-zinc-600 hover:text-red-400 hover:bg-red-900/20 rounded transition-colors disabled:opacity-50"
                      title="Cancel build"
                    >
                      <XCircle size={14} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
