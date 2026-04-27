import { useEffect, useState } from 'react';
import { Agent, agentsApi } from '../api/client';

const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  online: { bg: '#d1fae5', text: '#065f46', border: '#22c55e' },
  offline: { bg: '#fee2e2', text: '#991b1b', border: '#ef4444' },
  draining: { bg: '#fef3c7', text: '#92400e', border: '#f59e0b' },
};

export default function AgentStatus() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAgents = async () => {
    try {
      setLoading(true);
      const data = await agentsApi.list();
      setAgents(data);
      setError(null);
    } catch (e) {
      setError('Failed to load agents. Is the server running?');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgents();
    const interval = setInterval(loadAgents, 10000);
    return () => clearInterval(interval);
  }, []);

  const stats = {
    total: agents.length,
    online: agents.filter((a) => a.status === 'online').length,
    offline: agents.filter((a) => a.status === 'offline').length,
    draining: agents.filter((a) => a.status === 'draining').length,
  };

  if (loading && agents.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>
        Loading agents...
      </div>
    );
  }

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ color: '#fff', margin: 0 }}>Agents</h2>
        <button
          onClick={loadAgents}
          style={{
            padding: '8px 16px',
            background: '#333',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          Refresh
        </button>
      </div>

      {error && (
        <div style={{ color: '#ef4444', marginBottom: 16 }}>{error}</div>
      )}

      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        <div
          style={{
            padding: 16,
            background: '#1a1a1a',
            borderRadius: 8,
            minWidth: 100,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{stats.total}</div>
          <div style={{ fontSize: 12, color: '#888' }}>Total</div>
        </div>
        <div
          style={{
            padding: 16,
            background: '#1a1a1a',
            borderRadius: 8,
            minWidth: 100,
            borderLeft: `3px solid ${STATUS_COLORS.online.border}`,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 'bold', color: STATUS_COLORS.online.text }}>
            {stats.online}
          </div>
          <div style={{ fontSize: 12, color: '#888' }}>Online</div>
        </div>
        <div
          style={{
            padding: 16,
            background: '#1a1a1a',
            borderRadius: 8,
            minWidth: 100,
            borderLeft: `3px solid ${STATUS_COLORS.offline.border}`,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 'bold', color: STATUS_COLORS.offline.text }}>
            {stats.offline}
          </div>
          <div style={{ fontSize: 12, color: '#888' }}>Offline</div>
        </div>
        <div
          style={{
            padding: 16,
            background: '#1a1a1a',
            borderRadius: 8,
            minWidth: 100,
            borderLeft: `3px solid ${STATUS_COLORS.draining.border}`,
          }}
        >
          <div style={{ fontSize: 24, fontWeight: 'bold', color: STATUS_COLORS.draining.text }}>
            {stats.draining}
          </div>
          <div style={{ fontSize: 12, color: '#888' }}>Draining</div>
        </div>
      </div>

      {agents.length === 0 ? (
        <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
          No agents registered. Start an agent to see it here.
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280, 1fr))',
            gap: 16,
          }}
        >
          {agents.map((agent) => (
            <div
              key={agent.id}
              style={{
                padding: 16,
                background: '#1a1a1a',
                borderRadius: 8,
                border: `1px solid ${STATUS_COLORS[agent.status]?.border || '#333'}`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontWeight: 'bold', color: '#fff' }}>{agent.name}</span>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    fontWeight: 500,
                    background: STATUS_COLORS[agent.status]?.bg || '#eee',
                    color: STATUS_COLORS[agent.status]?.text || '#333',
                  }}
                >
                  {agent.status}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>
                Last seen: {new Date(agent.last_seen).toLocaleString()}
              </div>
              <div style={{ fontSize: 12, color: '#888' }}>
                Current jobs: {agent.current_jobs || 0}
              </div>
              {agent.labels && agent.labels.length > 0 && (
                <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {agent.labels.map((label, i) => (
                    <span
                      key={i}
                      style={{
                        padding: '2px 6px',
                        background: '#333',
                        borderRadius: 4,
                        fontSize: 11,
                        color: '#aaa',
                      }}
                    >
                      {label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}