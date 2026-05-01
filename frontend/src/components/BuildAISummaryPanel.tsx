import { useEffect, useState } from 'react'
import { aiApi, type BuildAISummary } from '../api/client'

const HEALTH_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  healthy:    { label: 'Healthy',    color: '#22c55e', bg: '#22c55e18' },
  degraded:   { label: 'Degraded',   color: '#f59e0b', bg: '#f59e0b18' },
  failed:     { label: 'Failed',     color: '#ef4444', bg: '#ef444418' },
  recovering: { label: 'Recovering', color: '#3b82f6', bg: '#3b82f618' },
  unknown:    { label: 'Unknown',    color: '#71717a', bg: '#71717a18' },
}

function parseList(raw: string | null): string[] {
  if (!raw) return []
  try { return JSON.parse(raw) as string[] } catch { return [] }
}

interface Props {
  buildId: number | undefined
  buildStatus: string | undefined
}

export function BuildAISummaryPanel({ buildId, buildStatus }: Props) {
  const [summary, setSummary] = useState<BuildAISummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(true)

  const done = buildStatus === 'passed' || buildStatus === 'failed'

  useEffect(() => {
    if (!buildId || !done) return

    setLoading(true)
    const poll = () => {
      aiApi.getBuildSummary(buildId)
        .then(data => { setSummary(data); setLoading(false) })
        .catch(() => setLoading(false))
    }

    poll()
    const interval = setInterval(poll, 5000)
    const timeout = setTimeout(() => clearInterval(interval), 120_000)
    return () => { clearInterval(interval); clearTimeout(timeout) }
  }, [buildId, done])

  if (!done) return null
  if (!summary && !loading) return null

  if (loading && !summary) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <span style={styles.sparkle}>✦</span>
          <span style={styles.title}>Generating AI build summary…</span>
          <span style={styles.spinner} />
        </div>
      </div>
    )
  }

  if (!summary) return null

  const health = HEALTH_CONFIG[summary.overall_health ?? 'unknown'] ?? HEALTH_CONFIG.unknown
  const whatFailed = parseList(summary.what_failed)
  const whatFixed = parseList(summary.what_was_fixed)
  const recs = parseList(summary.recommendations)

  return (
    <div style={styles.container}>
      <div
        style={{ ...styles.header, cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
      >
        <span style={styles.sparkle}>✦</span>
        <span style={styles.title}>AI Build Summary</span>
        <span style={{
          ...styles.healthBadge,
          color: health.color,
          background: health.bg,
          border: `1px solid ${health.color}44`,
        }}>
          {health.label}
        </span>
        <span style={{ color: '#52525b', fontSize: 12, marginLeft: 4 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {expanded && (
        <div style={styles.body}>
          {summary.summary && (
            <p style={styles.summaryText}>{summary.summary}</p>
          )}

          <div style={styles.grid}>
            {whatFailed.length > 0 && (
              <div style={styles.gridCell}>
                <div style={styles.gridLabel}>Failed</div>
                {whatFailed.map(item => (
                  <div key={item} style={{ ...styles.listItem, color: '#fca5a5' }}>
                    ✗ {item}
                  </div>
                ))}
              </div>
            )}

            {whatFixed.length > 0 && (
              <div style={styles.gridCell}>
                <div style={styles.gridLabel}>Auto-fixed</div>
                {whatFixed.map(item => (
                  <div key={item} style={{ ...styles.listItem, color: '#86efac' }}>
                    ✓ {item}
                  </div>
                ))}
              </div>
            )}
          </div>

          {recs.length > 0 && (
            <div style={styles.recsSection}>
              <div style={styles.gridLabel}>Recommendations</div>
              {recs.map((rec, i) => (
                <div key={i} style={styles.recItem}>
                  <span style={{ color: '#a78bfa', fontSize: 10 }}>▶</span>
                  {rec}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    border: '1px solid #27272a',
    borderRadius: 8,
    background: '#0f0f11',
    overflow: 'hidden',
    marginBottom: 16,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 14px',
    background: '#18181b',
    userSelect: 'none',
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
  healthBadge: {
    fontSize: 11,
    fontWeight: 600,
    padding: '2px 10px',
    borderRadius: 100,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
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
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  summaryText: {
    margin: 0,
    fontSize: 13,
    color: '#a1a1aa',
    lineHeight: 1.6,
  },
  grid: {
    display: 'flex',
    gap: 24,
    flexWrap: 'wrap',
  },
  gridCell: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    flex: 1,
    minWidth: 140,
  },
  gridLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: '#52525b',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 2,
  },
  listItem: {
    fontSize: 12,
    lineHeight: 1.5,
  },
  recsSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  recItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    fontSize: 12,
    color: '#a1a1aa',
    lineHeight: 1.5,
  },
}
