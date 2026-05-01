import { useState, useEffect, useRef, useCallback } from 'react'

export interface LogLine {
  line: string
  stream: 'stdout' | 'stderr' | 'system'
  timestamp: number
  lineNumber?: number
}

export interface JobLogsState {
  logs: LogLine[]
  connected: boolean
  error: string | null
  clearLogs: () => void
  disconnect: () => void
}

function getWsBase(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export function useJobLogs(jobId: number | null): JobLogsState {
  const [logs, setLogs] = useState<LogLine[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const attemptRef = useRef(0)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const clearLogs = useCallback(() => setLogs([]), [])

  const disconnect = useCallback(() => {
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  useEffect(() => {
    if (!jobId) {
      setLogs([])
      setConnected(false)
      return
    }

    attemptRef.current = 0

    const connect = () => {
      if (!mountedRef.current) return
      const url = `${getWsBase()}/ws/jobs/${jobId}/logs`
      let ws: WebSocket
      try {
        ws = new WebSocket(url)
      } catch (e) {
        setError('Cannot connect to log stream')
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) { ws.close(); return }
        attemptRef.current = 0
        setConnected(true)
        setError(null)
      }

      ws.onmessage = (e) => {
        if (!mountedRef.current) return
        try {
          const msg = JSON.parse(e.data as string) as Record<string, unknown>
          if (msg.type === 'pong') return
          const logLine: LogLine = {
            line: String(msg.content ?? msg.line ?? msg.message ?? e.data),
            stream: (msg.stream as LogLine['stream']) ?? 'stdout',
            timestamp: Date.now(),
            lineNumber: msg.line_number as number | undefined,
          }
          setLogs(prev => [...prev, logLine])
        } catch {
          setLogs(prev => [...prev, { line: e.data as string, stream: 'stdout', timestamp: Date.now() }])
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setError('Connection error')
        setConnected(false)
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setConnected(false)
        const delay = Math.min(1000 * 2 ** attemptRef.current, 8000)
        attemptRef.current++
        reconnectRef.current = setTimeout(connect, delay)
      }

      // Ping every 25s to keep the connection alive through proxies
      const pingId = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 25_000)

      // Attach to ws so we can clear it on cleanup
      ;(ws as WebSocket & { _ping: ReturnType<typeof setInterval> })._ping = pingId
    }

    connect()

    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      const ws = wsRef.current as (WebSocket & { _ping?: ReturnType<typeof setInterval> }) | null
      if (ws) {
        clearInterval(ws._ping)
        ws.onclose = null
        ws.close()
      }
      wsRef.current = null
    }
  }, [jobId])

  return { logs, connected, error, clearLogs, disconnect }
}

// ─── Build-level status stream ───────────────────────────────────────────────

export interface BuildUpdate {
  type: string
  build_id?: number
  job_id?: number
  status?: string
  exit_code?: number
}

export function useBuildUpdates(buildId: number | null) {
  const [lastUpdate, setLastUpdate] = useState<BuildUpdate | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!buildId) return
    const url = `${getWsBase()}/ws/builds/${buildId}`
    let ws: WebSocket
    try { ws = new WebSocket(url) } catch { return }
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string) as BuildUpdate
        if (msg.type && msg.type !== 'pong') setLastUpdate(msg)
      } catch { /* ignore */ }
    }

    const pingId = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    }, 25_000)

    return () => {
      clearInterval(pingId)
      ws.onclose = null
      ws.close()
    }
  }, [buildId])

  return { lastUpdate }
}
