import { useEffect, useState } from 'react';
import { Build, buildsApi } from '../api/client';

export default function BuildList() {
  const [builds, setBuilds] = useState<Build[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBuilds = async () => {
    try {
      setLoading(true);
      const data = await buildsApi.list();
      setBuilds(data);
      setError(null);
    } catch (e) {
      setError('Failed to load builds. Is the server running?');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBuilds();
  }, []);

  const statusColors: Record<string, { bg: string; text: string }> = {
    pending: { bg: '#fef3c7', text: '#92400e' },
    running: { bg: '#dbeafe', text: '#1e40af' },
    passed: { bg: '#d1fae5', text: '#065f46' },
    failed: { bg: '#fee2e2', text: '#991b1b' },
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>
        Loading builds...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 40 }}>
        <div style={{ color: '#ef4444', marginBottom: 16 }}>{error}</div>
        <button
          onClick={loadBuilds}
          style={{
            padding: '8px 16px',
            background: '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ color: '#fff', margin: 0 }}>Builds</h2>
        <button
          onClick={loadBuilds}
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

      {builds.length === 0 ? (
        <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
          No builds yet. Create one in the Pipeline Editor tab.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #333' }}>
              <th style={{ textAlign: 'left', padding: 12, color: '#888', fontSize: 12 }}>#</th>
              <th style={{ textAlign: 'left', padding: 12, color: '#888', fontSize: 12 }}>Pipeline</th>
              <th style={{ textAlign: 'left', padding: 12, color: '#888', fontSize: 12 }}>Branch</th>
              <th style={{ textAlign: 'left', padding: 12, color: '#888', fontSize: 12 }}>Status</th>
              <th style={{ textAlign: 'left', padding: 12, color: '#888', fontSize: 12 }}>Created</th>
            </tr>
          </thead>
          <tbody>
            {builds.map((build) => (
              <tr
                key={build.id}
                style={{ borderBottom: '1px solid #222' }}
              >
                <td style={{ padding: 12, color: '#888' }}>{build.id}</td>
                <td style={{ padding: 12, color: '#fff', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {build.pipeline.substring(0, 50)}...
                </td>
                <td style={{ padding: 12, color: '#fff' }}>{build.branch}</td>
                <td style={{ padding: 12 }}>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '4px 8px',
                      borderRadius: 4,
                      fontSize: 12,
                      fontWeight: 500,
                      background: statusColors[build.status]?.bg || '#eee',
                      color: statusColors[build.status]?.text || '#333',
                    }}
                  >
                    {build.status}
                  </span>
                </td>
                <td style={{ padding: 12, color: '#888', fontSize: 12 }}>
                  {new Date(build.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}