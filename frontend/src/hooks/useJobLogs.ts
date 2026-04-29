import { useCallback, useEffect, useRef, useState } from 'react';

export interface LogLine {
  line: string;
  stream: 'stdout' | 'stderr';
  timestamp: number;
}

export function useJobLogs(jobId: number | null, serverBase: string) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!jobId) return;
    
    const wsUrl = serverBase.replace('http', 'ws') + `/ws/jobs/${jobId}/logs`;
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLogs(prev => [...prev, {
            line: data.line || data.message || '',
            stream: data.stream || 'stdout',
            timestamp: Date.now(),
          }]);
        } catch {
          setLogs(prev => [...prev, {
            line: event.data,
            stream: 'stdout',
            timestamp: Date.now(),
          }]);
        }
      };

      ws.onerror = () => {
        setError('WebSocket connection error');
        setConnected(false);
      };

      ws.onclose = () => {
        setConnected(false);
        // Auto-reconnect after 3 seconds if jobId still exists
        if (jobId) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 3000);
        }
      };
    } catch (e) {
      setError('Failed to connect to log stream');
    }
  }, [jobId, serverBase]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  useEffect(() => {
    if (jobId) {
      connect();
    } else {
      disconnect();
    }
    return () => disconnect();
  }, [jobId, connect, disconnect]);

  return { logs, connected, error, clearLogs, disconnect };
}

export function useBuildUpdates(buildId: number | null, serverBase: string) {
  const [buildStatus, setBuildStatus] = useState<string | null>(null);
  const [jobStatuses, setJobStatuses] = useState<Record<number, string>>({});
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    if (!buildId) return;
    
    const wsUrl = serverBase.replace('http', 'ws') + `/ws/builds/${buildId}/updates`;
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.build_status) {
            setBuildStatus(data.build_status);
          }
          if (data.job_statuses) {
            setJobStatuses(data.job_statuses);
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onerror = () => {
        // Silently ignore errors for build updates
      };

      ws.onclose = () => {
        // Silently reconnect
        if (buildId) {
          setTimeout(() => connect(), 3000);
        }
      };
    } catch {
      // Ignore connection errors
    }
  }, [buildId, serverBase]);

  useEffect(() => {
    if (buildId) {
      connect();
    }
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [buildId, connect]);

  return { buildStatus, jobStatuses };
}