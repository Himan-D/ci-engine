import { useEffect, useState } from 'react'
import { aiApi, type JobAIAnalysis } from '../api/client'

const CATEGORY_LABELS: Record<string, string> = {
  dependency_missing: 'Missing Dependency',
  syntax_error: 'Syntax Error',
  test_failure: 'Test Failure',
  permission_error: 'Permission Error',
  network_error: 'Network Error',
  timeout: 'Timeout',
  config_error: 'Config Error',
  unknown: 'Unknown',
}

const CATEGORY_COLORS: Record<string, string> = {
  dependency_missing: '#f59e0b',
  syntax_error: '#ef4444',
  test_failure: '#ef4444',
  permission_error: '#f97316',
  network_error: '#3b82f6',
  timeout: '#8b5cf6',
  config_error: '#f59e0b',
  unknown: '#6b7280',
}

interface Props {
  jobId: number | undefined
  jobStatus: string | undefined
}

export function AIAnalysisPanel({ jobId, jobStatus }: Props) {
  const [analysis, setAnalysis] = useState<JobAIAnalysis | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jobId || jobStatus !== 'failed') {
      setAnalysis(null)
      return
    }

    setLoading(true)
    const poll = () => {
      aiApi.getJobAnalysis(jobId)
        .then(data => { setAnalysis(data); setLoading(false) })
        .catch(() => setLoading(false))
    }

    poll()
    // Poll every 4 s for up to 60 s (analysis takes a moment)
    const interval = setInterval(poll, 4000)
    const timeout = setTimeout(() => clearInterval(interval), 60_000)
    return () => { clearInterval(interval); clearTimeout(timeout) }
  }, [jobId, jobStatus])

  if (jobStatus !== 'failed') return null
  if (!analysis && !loading) return null

  if (loading && !analysis) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <span style={styles.sparkle}>✦</span>
          <span style={styles.title}>AI Analyzing failure…</span>
          <span style={styles.spinner} />
        </div>
      </div>
    )
  }

  if (!analysis) return null

  const catColor = CATEGORY_COLORS[analysis.error_category ?? 'unknown'] ?? '#6b7280'
  const catLabel = CATEGORY_LABELS[analysis.error_category ?? 'unknown'] ?? analysis.error_category

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.sparkle}>✦</span>
        <span style={styles.title}>AI Failure Analysis</span>
        {analysis.confidence != null && (
          <span style={{ ...styles.confidence, opacity: analysis.confidence }}>
            {Math.round(analysis.confidence * 100)}% confidence
          </span>
        )}
        {(analysis as any).provider && (
          <span style={styles.providerBadge}>
            {(analysis as any).provider}
          </span>
        )}
      </div>

      <div style={styles.body}>
        {/* Error category badge */}
        <div style={{ ...styles.badge, background: `${catColor}22`, color: catColor, borderColor: `${catColor}44` }}>
          {catLabel}
        </div>

        {/* Root cause */}
        {analysis.root_cause && (
          <div style={styles.section}>
            <div style={styles.label}>Root Cause</div>
            <div style={styles.value}>{analysis.root_cause}</div>
          </div>
        )}

        {/* Explanation */}
        {analysis.explanation && (
          <div style={styles.section}>
            <div style={styles.label}>Explanation</div>
            <div style={{ ...styles.value, color: '#a1a1aa' }}>{analysis.explanation}</div>
          </div>
        )}

        {/* Fixed command */}
        {analysis.fixed_command && (
          <div style={styles.section}>
            <div style={styles.label}>
              {analysis.fix_applied
                ? <><span style={{ color: '#22c55e' }}>✓</span> Auto-fix Applied</>
                : 'Suggested Fix'}
            </div>
            <code style={styles.code}>{analysis.fixed_command}</code>
          </div>
        )}

        {/* Pipeline suggestion */}
        {analysis.pipeline_suggestion && (
          <div style={styles.section}>
            <div style={styles.label}>Pipeline Suggestion</div>
            <div style={{ ...styles.value, color: '#a1a1aa', fontStyle: 'italic' }}>
              {analysis.pipeline_suggestion}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    marginTop: 12,
    border: '1px solid #27272a',
    borderRadius: 8,
    background: '#0f0f11',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 14px',
    borderBottom: '1px solid #27272a',
    background: '#18181b',
  },
  sparkle: {
    fontSize: 14,
    color: '#a78bfa',
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: '#e4e4e7',
    flex: 1,
  },
  confidence: {
    fontSize: 11,
    color: '#71717a',
  },
  spinner: {
    width: 12,
    height: 12,
    borderRadius: '50%',
    border: '2px solid #3f3f46',
    borderTopColor: '#a78bfa',
    animation: 'spin 0.8s linear infinite',
  },
  body: {
    padding: 14,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  badge: {
    display: 'inline-flex',
    alignSelf: 'flex-start',
    padding: '2px 10px',
    borderRadius: 100,
    fontSize: 11,
    fontWeight: 600,
    border: '1px solid',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  label: {
    fontSize: 11,
    fontWeight: 600,
    color: '#71717a',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  value: {
    fontSize: 13,
    color: '#e4e4e7',
    lineHeight: 1.5,
  },
  providerBadge: {
    fontSize: 10,
    color: '#52525b',
    background: '#27272a',
    padding: '1px 6px',
    borderRadius: 4,
    fontFamily: 'monospace',
    letterSpacing: '0.04em',
  },
  code: {
    display: 'block',
    background: '#0a0a0d',
    border: '1px solid #22c55e33',
    color: '#86efac',
    borderRadius: 6,
    padding: '6px 10px',
    fontSize: 12,
    fontFamily: 'monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
}
