import { useEffect, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Build, buildsApi } from '../api/client';

const STATUS_COLORS: Record<string, string> = {
  pending: '#6b7280',
  running: '#3b82f6',
  passed: '#22c55e',
  failed: '#ef4444',
};

export default function BuildGraph() {
  const [builds, setBuilds] = useState<Build[]>([]);
  const [selectedBuild, setSelectedBuild] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const loadBuilds = async () => {
    try {
      setLoading(true);
      const data = await buildsApi.list();
      setBuilds(data);
      setError(null);
    } catch (e) {
      setError('Failed to load builds');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const loadJobs = async (buildId: number) => {
    try {
      const jobData = await buildsApi.getJobs(buildId);

      const newNodes: Node[] = jobData.map((job, i) => ({
        id: String(job.id),
        position: { x: (i % 3) * 200, y: Math.floor(i / 3) * 120 },
        data: { label: job.step, status: job.status },
        type: 'default',
      }));

      const newEdges: Edge[] = [];
      jobData.forEach((job, i) => {
        if (i > 0) {
          newEdges.push({
            id: `e${jobData[i - 1].id}-${job.id}`,
            source: String(jobData[i - 1].id),
            target: String(job.id),
            type: 'smoothstep',
          });
        }
      });

      setNodes(newNodes);
      setEdges(newEdges);
    } catch (e) {
      console.error('Failed to load jobs:', e);
    }
  };

  useEffect(() => {
    loadBuilds();
  }, []);

  useEffect(() => {
    if (selectedBuild) {
      loadJobs(selectedBuild);
    }
  }, [selectedBuild]);

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#888' }}>
        Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 20 }}>
        <div style={{ color: '#ef4444' }}>{error}</div>
        <button onClick={loadBuilds}>Retry</button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{ width: 250, borderRight: '1px solid #333', padding: 16, overflow: 'auto' }}>
        <h3 style={{ color: '#fff', marginBottom: 16 }}>Select Build</h3>
        {builds.length === 0 ? (
          <div style={{ color: '#666' }}>No builds</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {builds.map((build) => (
              <button
                key={build.id}
                onClick={() => setSelectedBuild(build.id)}
                style={{
                  padding: '12px',
                  background: selectedBuild === build.id ? '#333' : '#1a1a1a',
                  border: 'none',
                  borderRadius: 4,
                  color: '#fff',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <div style={{ fontSize: 12, color: '#888' }}>#{build.id}</div>
                <div style={{ fontSize: 14 }}>{build.branch}</div>
                <div
                  style={{
                    fontSize: 11,
                    color: STATUS_COLORS[build.status],
                    textTransform: 'uppercase',
                  }}
                >
                  {build.status}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: 1 }}>
        {selectedBuild ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            fitView
            style={{ background: '#0a0a0a' }}
          >
            <Background color="#333" gap={20} />
            <Controls />
            <MiniMap
              nodeColor={(node) => STATUS_COLORS[(node.data as { status: string }).status] || '#666'}
              style={{ background: '#1a1a1a' }}
            />
          </ReactFlow>
        ) : (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: '#666',
            }}
          >
            Select a build to view its job graph
          </div>
        )}
      </div>
    </div>
  );
}