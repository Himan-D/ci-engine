import { useEffect, useRef } from 'react'
import type { LogLine } from '../hooks/useJobLogs'

interface Props {
  logs: LogLine[]
  connected: boolean
  className?: string
  autoScroll?: boolean
}

export function Terminal({ logs, connected, className = '', autoScroll = true }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const userScrolledRef = useRef(false)

  // Auto-scroll only if user hasn't scrolled up
  useEffect(() => {
    if (autoScroll && !userScrolledRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    userScrolledRef.current = !atBottom
  }

  if (logs.length === 0) {
    return (
      <div className={`terminal flex items-center justify-center ${className}`}>
        <div className="text-zinc-600 text-sm flex items-center gap-2">
          <span className={`status-dot ${connected ? 'bg-green-500 animate-pulse-slow' : 'bg-zinc-700'}`} />
          {connected ? 'Waiting for output…' : 'Not connected'}
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className={`terminal ${className}`}
    >
      <div className="py-2">
        {logs.map((log, i) => (
          <div
            key={i}
            className={`terminal-line ${log.stream === 'stderr' ? 'stderr' : ''}`}
          >
            <span className="text-zinc-700 select-none mr-3 text-xs">
              {log.lineNumber ?? i + 1}
            </span>
            {log.line}
          </div>
        ))}
        {connected && (
          <div className="terminal-line text-zinc-600">
            <span className="text-zinc-700 select-none mr-3 text-xs">{logs.length + 1}</span>
            <span className="animate-blink">▊</span>
          </div>
        )}
      </div>
      <div ref={bottomRef} />
    </div>
  )
}
