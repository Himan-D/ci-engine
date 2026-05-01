import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, RefreshCw, XCircle, ChevronRight,
  Clock, GitBranch, Hash, Terminal as TerminalIcon,
} from 'lucide-react'
import { buildsApi, type Build, type Job } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { Terminal } from '../components/Terminal'
import { useJobLogs, useBuildUpdates } from '../hooks/useJobLogs'
import { formatDistanceToNow, format } from 'date-fns'
import { AIAnalysisPanel } from '../components/AIAnalysisPanel'
import { BuildAISummaryPanel } from '../components/BuildAISummaryPanel'
import { BuildAnnotationsPanel } from '../components/BuildAnnotationsPanel'
import { BuildMetadataPanel } from '../components/BuildMetadataPanel'

function JobStep({ job, selected, onClick }: { job: Job; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2.5 w-full text-left px-3 py-2.5 rounded-lg transition-colors text-sm ${
        selected
          ? 'bg-zinc-800 border border-zinc-700 text-zinc-100'
          : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
      }`}
    >
      <span className={`status-dot flex-shrink-0 ${
        job.status === 'running'     ? 'bg-blue-400 animate-pulse-slow' :
        job.status === 'passed'      ? 'bg-green-400' :
        job.status === 'failed'      ? 'bg-red-400' :
        job.status === 'soft_failed' ? 'bg-amber-400' :
        job.status === 'cancelled'   ? 'bg-zinc-600' :
        job.status === 'skipped'     ? 'bg-zinc-700' :
        'bg-zinc-600'
      }`} />
      <span className="flex-1 truncate font-medium">{job.label ?? job.name}</span>
      {selected && <ChevronRight size={12} className="text-zinc-600 flex-shrink-0" />}
    </button>
  )
}

export default function BuildDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate  = useNavigate()
  const buildId   = id ? parseInt(id) : null

  const [build, setBuild]             = useState<Build | null>(null)
  const [jobs, setJobs]               = useState<Job[]>([])
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const [loading, setLoading]         = useState(true)
  const [cancelling, setCancelling]   = useState(false)

  const { logs, connected } = useJobLogs(selectedJobId)
  const { lastUpdate }      = useBuildUpdates(buildId)

  const load = useCallback(() => {
    if (!buildId) return
    Promise.all([
      buildsApi.get(buildId),
      buildsApi.getJobs(buildId),
    ]).then(([b, j]) => {
      setBuild(b)
      setJobs(j)
      // Auto-select running job, else first failed, else first job
      if (selectedJobId === null) {
        const running = j.find(x => x.status === 'running')
        const failed  = j.find(x => x.status === 'failed')
        if (running) setSelectedJobId(running.id)
        else if (failed) setSelectedJobId(failed.id)
        else if (j[0]) setSelectedJobId(j[0].id)
      }
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [buildId, selectedJobId])

  useEffect(() => { load() }, [buildId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch jobs when build updates come in
  useEffect(() => {
    if (lastUpdate) load()
  }, [lastUpdate]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCancel = async () => {
    if (!buildId) return
    setCancelling(true)
    try { await buildsApi.cancel(buildId); load() }
    finally { setCancelling(false) }
  }

  const selectedJob = jobs.find(j => j.id === selectedJobId)
  const duration = (job: Job): string => {
    if (!job.started_at) return '—'
    const end = job.completed_at ? new Date(job.completed_at) : new Date()
    const secs = Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000)
    if (secs < 60) return `${secs}s`
    return `${Math.floor(secs / 60)}m ${secs % 60}s`
  }

  if (loading) {
    return (
      <div className="p-6 animate-fade-in">
        <div className="flex items-center gap-3 mb-6">
          <div className="h-6 w-32 bg-zinc-800 rounded animate-pulse" />
        </div>
        <div className="h-24 card animate-pulse" />
      </div>
    )
  }

  if (!build) {
    return (
      <div className="p-6 text-center">
        <p className="text-zinc-500">Build not found.</p>
        <button onClick={() => navigate('/builds')} className="btn-secondary btn-sm mt-4">
          ← Back to builds
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Top bar */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-zinc-800/60 bg-zinc-950/60 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/builds')}
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <ArrowLeft size={18} />
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-lg font-display font-bold text-zinc-100">
                Build <span className="text-zinc-500">#{build.id}</span>
              </h1>
              <StatusBadge status={build.status} />
            </div>
            <div className="flex items-center gap-4 mt-1 flex-wrap">
              {build.repository && (
                <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <Hash size={11} />
                  {build.repository}
                </span>
              )}
              {build.branch && (
                <span className="flex items-center gap-1.5 text-xs text-zinc-500 font-mono">
                  <GitBranch size={11} />
                  {build.branch}
                </span>
              )}
              {build.commit_sha && (
                <span className="flex items-center gap-1.5 text-xs text-zinc-600 font-mono">
                  {build.commit_sha.slice(0, 8)}
                </span>
              )}
              <span className="flex items-center gap-1.5 text-xs text-zinc-600">
                <Clock size={11} />
                {format(new Date(build.created_at), 'MMM d, HH:mm')}
                {' · '}
                {formatDistanceToNow(new Date(build.created_at), { addSuffix: true })}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            <button onClick={load} className="btn-secondary btn-sm">
              <RefreshCw size={12} />
            </button>
            {(build.status === 'running' || build.status === 'pending') && (
              <button
                onClick={handleCancel}
                disabled={cancelling}
                className="btn-danger btn-sm"
              >
                <XCircle size={12} />
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Pipeline steps strip */}
      {jobs.length > 0 && (
        <div className="flex-shrink-0 px-6 py-3 border-b border-zinc-800/40 bg-zinc-900/30 overflow-x-auto">
          <div className="flex items-center gap-1 min-w-max">
            {jobs.map((job, idx) => (
              <div key={job.id} className="flex items-center">
                {idx > 0 && (
                  <div className={`w-8 h-px ${
                    job.status === 'passed' ? 'bg-green-700' :
                    job.status === 'failed' ? 'bg-red-800' :
                    'bg-zinc-700'
                  }`} />
                )}
                <button
                  onClick={() => setSelectedJobId(job.id)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                    selectedJobId === job.id
                      ? 'bg-zinc-800 text-zinc-100 border border-zinc-600'
                      : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/40'
                  }`}
                >
                  <span className={`status-dot ${
                    job.status === 'running'     ? 'bg-blue-400 animate-pulse-slow' :
                    job.status === 'passed'      ? 'bg-green-400' :
                    job.status === 'failed'      ? 'bg-red-400' :
                    job.status === 'soft_failed' ? 'bg-amber-400' :
                    job.status === 'skipped'     ? 'bg-zinc-700' :
                    'bg-zinc-600'
                  }`} />
                  {job.label ?? job.name}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Build Annotations */}
      <div className="flex-shrink-0 px-6 pt-4">
        <BuildAnnotationsPanel buildId={build.id} />
      </div>

      {/* AI Build Summary */}
      {(build.status === 'passed' || build.status === 'failed') && (
        <div className="flex-shrink-0 px-6 pt-4">
          <BuildAISummaryPanel buildId={build.id} buildStatus={build.status} />
        </div>
      )}

      {/* Build Metadata */}
      <div className="flex-shrink-0 px-6 pt-2">
        <BuildMetadataPanel buildId={build.id} />
      </div>

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Jobs sidebar */}
        <div className="w-56 flex-shrink-0 border-r border-zinc-800/60 bg-zinc-950/40 p-3 overflow-y-auto">
          <div className="text-xs font-medium text-zinc-600 uppercase tracking-wider px-2 mb-2">
            Jobs · {jobs.length}
          </div>
          <div className="space-y-0.5">
            {jobs.map(job => (
              <div key={job.id}>
                <JobStep
                  job={job}
                  selected={selectedJobId === job.id}
                  onClick={() => setSelectedJobId(job.id)}
                />
                {selectedJobId === job.id && (
                  <div className="px-3 pb-1">
                    <div className="text-xs text-zinc-700 mt-0.5">
                      Duration: {duration(job)}
                    </div>
                    {job.exit_code !== null && job.exit_code !== undefined && (
                      <div className="text-xs text-zinc-700">
                        Exit: {job.exit_code}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {jobs.length === 0 && (
              <div className="text-xs text-zinc-700 px-2 py-4 text-center">
                No jobs yet
              </div>
            )}
          </div>
        </div>

        {/* Log terminal */}
        <div className="flex-1 flex flex-col min-w-0 p-4 gap-3">
          {/* Job header */}
          {selectedJob && (
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="flex items-center gap-2">
                <TerminalIcon size={14} className="text-zinc-500" />
                <span className="text-sm font-medium text-zinc-300">{selectedJob.label ?? selectedJob.name}</span>
                <StatusBadge status={selectedJob.status} size="sm" />
              </div>
              {selectedJob.command && (
                <code className="text-xs text-zinc-600 font-mono bg-zinc-900 px-2 py-0.5 rounded border border-zinc-800 max-w-md truncate">
                  {selectedJob.command}
                </code>
              )}
              {connected && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-green-600">
                  <span className="status-dot bg-green-500 animate-pulse-slow" />
                  Live
                </span>
              )}
            </div>
          )}

          {/* Terminal */}
          <Terminal
            logs={logs}
            connected={connected}
            className="flex-1 min-h-0"
            autoScroll
          />

          {/* AI failure analysis (shown below terminal for failed jobs) */}
          {selectedJob && (
            <AIAnalysisPanel
              jobId={selectedJob.id}
              jobStatus={selectedJob.status}
            />
          )}
        </div>
      </div>
    </div>
  )
}
