import { useEffect, useState, useMemo } from 'react'
import {
  TrendingUp, TrendingDown, Minus,
  AlertTriangle, BarChart3, Clock, DollarSign,
  RefreshCw, ChevronRight,
} from 'lucide-react'
import { buildsApi, analyticsApi, type RepositoryMetric, type FlakynessRecord } from '../api/client'
import { formatDistanceToNow } from 'date-fns'

// ─── Tiny SVG sparkline ───────────────────────────────────────────────────────

function Sparkline({
  data,
  color = '#f97316',
  height = 40,
  width = 120,
}: {
  data: number[]
  color?: string
  height?: number
  width?: number
}) {
  if (data.length < 2) return null
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  const step = width / (data.length - 1)
  const pts = data.map((v, i) => {
    const x = i * step
    const y = height - ((v - min) / range) * height * 0.85 - height * 0.075
    return `${x},${y}`
  }).join(' ')

  // Area fill
  const first = `0,${height}`
  const last = `${width},${height}`
  const area = `${first} ${pts} ${last}`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <defs>
        <linearGradient id={`spark-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={area}
        fill={`url(#spark-${color.replace('#', '')})`}
      />
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Last point dot */}
      {data.length > 0 && (() => {
        const last = data[data.length - 1]
        const x = (data.length - 1) * step
        const y = height - ((last - min) / range) * height * 0.85 - height * 0.075
        return <circle cx={x} cy={y} r="3" fill={color} />
      })()}
    </svg>
  )
}

// ─── Pass rate bar chart ──────────────────────────────────────────────────────

function PassRateChart({ metrics }: { metrics: RepositoryMetric[] }) {
  const sorted = [...metrics].sort((a, b) => a.date.localeCompare(b.date)).slice(-14)
  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-zinc-700 text-sm">
        No data yet
      </div>
    )
  }

  const maxBuilds = Math.max(...sorted.map(m => m.total_builds), 1)

  return (
    <div className="flex flex-col h-40">
      <div className="flex-1 flex items-end gap-1 min-h-0 px-1 pb-1">
        {sorted.map((m) => {
          const passRate = m.total_builds > 0 ? m.passed_builds / m.total_builds : 0
          const failRate = m.total_builds > 0 ? m.failed_builds / m.total_builds : 0
          const barH = Math.max((m.total_builds / maxBuilds) * 100, 2)
          const passH = barH * passRate
          const failH = barH * failRate

          return (
            <div
              key={m.date}
              className="flex-1 flex flex-col justify-end gap-px group relative"
              title={`${m.date}: ${m.passed_builds} passed / ${m.failed_builds} failed`}
            >
              {/* Tooltip */}
              <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-zinc-800 border border-zinc-700 rounded-md px-2.5 py-1.5 text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                <div className="text-zinc-400 mb-1">{m.date.slice(5)}</div>
                <div className="text-green-400">{m.passed_builds} passed</div>
                <div className="text-red-400">{m.failed_builds} failed</div>
              </div>
              {failH > 0 && (
                <div
                  className="w-full rounded-sm bg-red-600/70 transition-all"
                  style={{ height: `${failH}%` }}
                />
              )}
              {passH > 0 && (
                <div
                  className="w-full rounded-sm bg-green-600/70 transition-all"
                  style={{ height: `${passH}%` }}
                />
              )}
            </div>
          )
        })}
      </div>
      {/* X-axis labels */}
      <div className="flex gap-1 px-1">
        {sorted.map((m, i) => (
          <div
            key={m.date}
            className="flex-1 text-center text-zinc-700 leading-none"
            style={{ fontSize: '9px' }}
          >
            {i % 3 === 0 ? m.date.slice(8) : ''}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, trend, color = 'brand',
}: {
  label: string
  value: string | number
  sub?: string
  trend?: 'up' | 'down' | 'flat'
  color?: 'brand' | 'green' | 'red' | 'blue' | 'amber'
}) {
  const colorMap = {
    brand: 'text-brand-400',
    green: 'text-green-400',
    red:   'text-red-400',
    blue:  'text-blue-400',
    amber: 'text-amber-400',
  }
  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus

  return (
    <div className="card p-4">
      <div className="text-xs text-zinc-600 uppercase tracking-wider font-medium mb-2">{label}</div>
      <div className={`text-2xl font-display font-bold ${colorMap[color]}`}>{value}</div>
      {sub && (
        <div className="flex items-center gap-1.5 mt-1.5">
          {trend && <TrendIcon size={11} className={colorMap[color]} />}
          <span className="text-xs text-zinc-600">{sub}</span>
        </div>
      )}
    </div>
  )
}

// ─── Flakiness table ──────────────────────────────────────────────────────────

function FlakinessTable({ records }: { records: FlakynessRecord[] }) {
  if (records.length === 0) {
    return (
      <div className="flex items-center justify-center py-10 text-zinc-700 text-sm">
        No flaky tests detected
      </div>
    )
  }

  const top = records.slice(0, 20)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-800/60">
            <th className="text-left px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider">Test</th>
            <th className="text-left px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider hidden md:table-cell">Suite</th>
            <th className="text-right px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider">Runs</th>
            <th className="text-right px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider">Failures</th>
            <th className="text-right px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider">Score</th>
            <th className="text-center px-3 py-2.5 text-zinc-500 font-semibold uppercase tracking-wider hidden lg:table-cell">Status</th>
          </tr>
        </thead>
        <tbody>
          {top.map((r, i) => {
            const pct = Math.round(r.flakiness_score * 100)
            const barColor = pct > 50 ? 'bg-red-500' : pct > 20 ? 'bg-amber-500' : 'bg-yellow-500'
            return (
              <tr
                key={i}
                className="border-b border-zinc-800/30 last:border-0 hover:bg-zinc-800/20 transition-colors"
              >
                <td className="px-3 py-2.5">
                  <code className="text-zinc-200 font-mono text-xs truncate block max-w-xs">
                    {r.test_name}
                  </code>
                  {r.last_seen && (
                    <div className="text-zinc-700 mt-0.5" style={{ fontSize: '10px' }}>
                      Last: {formatDistanceToNow(new Date(r.last_seen), { addSuffix: true })}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-zinc-500 hidden md:table-cell">
                  <code>{r.suite_name ?? '—'}</code>
                </td>
                <td className="px-3 py-2.5 text-right text-zinc-400 tabular-nums">{r.total_runs}</td>
                <td className="px-3 py-2.5 text-right text-red-400 tabular-nums">{r.failed_runs}</td>
                <td className="px-3 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-16 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${barColor} rounded-full transition-all`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className={`tabular-nums font-mono ${pct > 50 ? 'text-red-400' : pct > 20 ? 'text-amber-400' : 'text-yellow-400'}`}>
                      {pct}%
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-center hidden lg:table-cell">
                  {r.is_quarantined ? (
                    <span className="inline-flex items-center gap-1 text-xs bg-amber-900/30 text-amber-400 border border-amber-800/40 px-2 py-0.5 rounded-full">
                      <AlertTriangle size={9} /> Quarantined
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs bg-zinc-800/60 text-zinc-600 border border-zinc-700/40 px-2 py-0.5 rounded-full">
                      Active
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Duration trend line chart (SVG) ─────────────────────────────────────────

function DurationChart({ metrics }: { metrics: RepositoryMetric[] }) {
  const sorted = [...metrics]
    .sort((a, b) => a.date.localeCompare(b.date))
    .filter(m => m.avg_duration_seconds != null)
    .slice(-14)

  if (sorted.length < 2) {
    return (
      <div className="flex items-center justify-center h-32 text-zinc-700 text-sm">
        No duration data
      </div>
    )
  }

  const vals = sorted.map(m => m.avg_duration_seconds!)
  return (
    <div className="px-2 py-1">
      <Sparkline data={vals} color="#60a5fa" width={400} height={60} />
      <div className="flex justify-between text-zinc-700 mt-1" style={{ fontSize: '10px' }}>
        <span>{sorted[0]?.date.slice(5)}</span>
        <span className="text-zinc-500">avg duration (s)</span>
        <span>{sorted[sorted.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  )
}

// ─── Analytics page ───────────────────────────────────────────────────────────

export default function Analytics() {
  const [repositories, setRepositories] = useState<string[]>([])
  const [selectedRepo, setSelectedRepo] = useState<string>('')
  const [metrics, setMetrics] = useState<RepositoryMetric[]>([])
  const [flakiness, setFlakiness] = useState<FlakynessRecord[]>([])
  const [loadingMetrics, setLoadingMetrics] = useState(false)
  const [loadingFlaky, setLoadingFlaky] = useState(false)
  const [days, setDays] = useState(30)

  // Derive repository list from recent builds
  useEffect(() => {
    buildsApi.list(200).then(builds => {
      const repos = [...new Set(
        builds.map(b => b.repository).filter((r): r is string => !!r)
      )]
      setRepositories(repos)
      if (repos.length > 0 && !selectedRepo) setSelectedRepo(repos[0])
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedRepo) return

    setLoadingMetrics(true)
    analyticsApi.repoMetrics(selectedRepo, days)
      .then(setMetrics)
      .catch(() => setMetrics([]))
      .finally(() => setLoadingMetrics(false))

    setLoadingFlaky(true)
    analyticsApi.flakiness(selectedRepo)
      .then(res => setFlakiness(res.records ?? []))
      .catch(() => setFlakiness([]))
      .finally(() => setLoadingFlaky(false))
  }, [selectedRepo, days])

  // Derived KPIs
  const kpis = useMemo(() => {
    if (metrics.length === 0) return null
    const total = metrics.reduce((s, m) => s + m.total_builds, 0)
    const passed = metrics.reduce((s, m) => s + m.passed_builds, 0)
    const failed = metrics.reduce((s, m) => s + m.failed_builds, 0)
    const passRate = total > 0 ? Math.round((passed / total) * 100) : 0

    const durVals = metrics.map(m => m.avg_duration_seconds).filter((v): v is number => v != null)
    const avgDur = durVals.length > 0 ? Math.round(durVals.reduce((a, b) => a + b, 0) / durVals.length) : null

    const mttrVals = metrics.map(m => m.mttr_seconds).filter((v): v is number => v != null)
    const avgMttr = mttrVals.length > 0 ? Math.round(mttrVals.reduce((a, b) => a + b, 0) / mttrVals.length) : null

    const passVals = metrics.map(m => m.passed_builds)
    const trend: 'up' | 'down' | 'flat' = passVals.length >= 2
      ? passVals[passVals.length - 1] > passVals[passVals.length - 2] ? 'up'
        : passVals[passVals.length - 1] < passVals[passVals.length - 2] ? 'down' : 'flat'
      : 'flat'

    return { total, passed, failed, passRate, avgDur, avgMttr, trend, passVals }
  }, [metrics])

  const formatDuration = (secs: number | null) => {
    if (secs == null) return '—'
    if (secs < 60) return `${secs}s`
    if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
    return `${(secs / 3600).toFixed(1)}h`
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto animate-fade-in">
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-zinc-800/60 bg-zinc-950/60 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <BarChart3 size={18} className="text-brand-500" />
            <h1 className="text-lg font-display font-bold text-zinc-100">Analytics</h1>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Repository selector */}
            {repositories.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-600">Repository</span>
                <select
                  value={selectedRepo}
                  onChange={e => setSelectedRepo(e.target.value)}
                  className="input text-xs py-1.5 pr-8 w-auto min-w-[160px]"
                >
                  {repositories.map(r => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Time window */}
            <div className="flex items-center gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
              {[7, 14, 30].map(d => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    days === d
                      ? 'bg-zinc-700 text-zinc-100'
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {d}d
                </button>
              ))}
            </div>

            <button
              onClick={() => {
                if (!selectedRepo) return
                setLoadingMetrics(true)
                analyticsApi.repoMetrics(selectedRepo, days)
                  .then(setMetrics)
                  .catch(() => setMetrics([]))
                  .finally(() => setLoadingMetrics(false))
              }}
              className="btn-secondary btn-sm"
            >
              <RefreshCw size={12} className={loadingMetrics ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6 space-y-6">
        {/* No repo state */}
        {repositories.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <BarChart3 size={32} className="text-zinc-700 mb-3" />
            <p className="text-zinc-500 font-medium">No repository data yet</p>
            <p className="text-zinc-700 text-sm mt-1">
              Run some builds with a repository field to see analytics.
            </p>
          </div>
        )}

        {/* KPI cards */}
        {kpis && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              label="Pass Rate"
              value={`${kpis.passRate}%`}
              sub={`${kpis.passed} of ${kpis.total} builds`}
              trend={kpis.trend}
              color={kpis.passRate >= 80 ? 'green' : kpis.passRate >= 60 ? 'amber' : 'red'}
            />
            <KpiCard
              label="Total Builds"
              value={kpis.total}
              sub={`${kpis.failed} failed in ${days}d`}
              color="brand"
            />
            <KpiCard
              label="Avg Duration"
              value={formatDuration(kpis.avgDur)}
              sub="per build"
              color="blue"
            />
            <KpiCard
              label="MTTR"
              value={formatDuration(kpis.avgMttr)}
              sub="mean time to recovery"
              color="amber"
            />
          </div>
        )}

        {/* Build trend + duration */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Pass/Fail chart */}
          <div className="card p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-zinc-200">Build Trend</h2>
                <span className="text-xs text-zinc-600">last {days} days</span>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-green-600/70 inline-block" />
                  <span className="text-zinc-600">Passed</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-sm bg-red-600/70 inline-block" />
                  <span className="text-zinc-600">Failed</span>
                </span>
              </div>
            </div>
            {loadingMetrics ? (
              <div className="h-40 bg-zinc-800/40 rounded animate-pulse" />
            ) : (
              <PassRateChart metrics={metrics} />
            )}
          </div>

          {/* Duration trend */}
          <div className="card p-4">
            <div className="flex items-center gap-2 mb-4">
              <Clock size={14} className="text-blue-400" />
              <h2 className="text-sm font-semibold text-zinc-200">Avg Build Duration</h2>
            </div>
            {loadingMetrics ? (
              <div className="h-32 bg-zinc-800/40 rounded animate-pulse" />
            ) : (
              <DurationChart metrics={metrics} />
            )}
          </div>
        </div>

        {/* Flakiness table */}
        <div className="card overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800/60">
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} className="text-amber-400" />
              <h2 className="text-sm font-semibold text-zinc-200">Flaky Tests</h2>
              {flakiness.length > 0 && (
                <span className="text-xs bg-amber-900/30 text-amber-400 border border-amber-800/40 px-2 py-0.5 rounded-full">
                  {flakiness.length} detected
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                <span className="text-zinc-600">{'> 50% fail rate'}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
                <span className="text-zinc-600">20–50%</span>
              </span>
            </div>
          </div>
          {loadingFlaky ? (
            <div className="p-4 space-y-2">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-10 bg-zinc-800/40 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <FlakinessTable records={flakiness} />
          )}
        </div>

        {/* Pass rate sparkline KPI */}
        {kpis && kpis.passVals.length >= 2 && (
          <div className="card p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-zinc-600 uppercase tracking-wider font-medium mb-1">
                  Pass Rate Trend · {days}d
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xl font-display font-bold text-green-400">
                    {kpis.passRate}%
                  </span>
                  <div className="flex items-center gap-2 text-xs text-zinc-600">
                    {kpis.trend === 'up' ? (
                      <TrendingUp size={13} className="text-green-400" />
                    ) : kpis.trend === 'down' ? (
                      <TrendingDown size={13} className="text-red-400" />
                    ) : (
                      <Minus size={13} />
                    )}
                    <span>
                      {kpis.trend === 'up' ? 'Improving' : kpis.trend === 'down' ? 'Declining' : 'Stable'}
                    </span>
                  </div>
                </div>
              </div>
              <Sparkline data={kpis.passVals} color="#4ade80" width={200} height={50} />
            </div>
          </div>
        )}

        {/* Cost summary (if data available) */}
        <CostSummary repository={selectedRepo} days={days} />
      </div>
    </div>
  )
}

// ─── Cost summary section ─────────────────────────────────────────────────────

function CostSummary({ repository, days }: { repository: string; days: number }) {
  const [cost, setCost] = useState<{ total_cost_usd: number; avg_cost_usd: number | null; total_builds: number } | null>(null)

  useEffect(() => {
    if (!repository) return
    analyticsApi.cost(repository, days)
      .then(c => {
        if (c.total_cost_usd > 0) setCost(c)
        else setCost(null)
      })
      .catch(() => setCost(null))
  }, [repository, days])

  if (!cost) return null

  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-4">
        <DollarSign size={14} className="text-green-400" />
        <h2 className="text-sm font-semibold text-zinc-200">Cost Summary</h2>
        <span className="text-xs text-zinc-600">last {days} days · {repository}</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="text-xs text-zinc-600 mb-1">Total Cost</div>
          <div className="text-xl font-display font-bold text-green-400">
            ${cost.total_cost_usd.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-600 mb-1">Per Build (avg)</div>
          <div className="text-xl font-display font-bold text-zinc-300">
            {cost.avg_cost_usd != null ? `$${cost.avg_cost_usd.toFixed(4)}` : '—'}
          </div>
        </div>
        <div>
          <div className="text-xs text-zinc-600 mb-1">Builds</div>
          <div className="text-xl font-display font-bold text-zinc-300">{cost.total_builds}</div>
        </div>
      </div>
    </div>
  )
}

// Ensure ChevronRight is used (imported but only needed if we add links later)
void ChevronRight
