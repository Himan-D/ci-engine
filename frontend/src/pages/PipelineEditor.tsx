import { useCallback, useEffect, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import StepNode from '../components/StepNode';
import { usePipelineStore } from '../hooks/usePipelineStore';
import { Pipeline } from '../types/pipeline';
import { pipelineApi } from '../api/client';

const nodeTypes = {
  step: StepNode,
};

interface PipelineEditorProps {
  initialPipeline?: Pipeline;
  onSave?: (pipeline: Pipeline) => void;
  readOnly?: boolean;
}

const defaultPipeline = `steps:
  - label: "Build"
    command: "npm run build"
  - label: "Test"
    command: "npm test"
  - label: "Deploy"
    command: "npm run deploy"
    depends_on: test`;

export default function PipelineEditor({
  initialPipeline,
  onSave,
  readOnly = false,
}: PipelineEditorProps) {
  const [yamlInput, setYamlInput] = useState(defaultPipeline);
  
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    loadFromYAML,
    toPipeline,
    setSelectedNode,
  } = usePipelineStore();

  // Load initial pipeline
  useEffect(() => {
    if (initialPipeline) {
      const yaml = pipelineToYaml(initialPipeline);
      setYamlInput(yaml);
      loadFromYAML(yaml);
    } else {
      loadFromYAML(defaultPipeline);
    }
  }, [initialPipeline]);

  const pipelineToYaml = (pipeline: Pipeline): string => {
    let yaml = 'steps:\n';
    for (const step of pipeline.steps) {
      yaml += `  - label: "${step.label}"\n`;
      if (step.command) {
        yaml += `    command: "${step.command}"\n`;
      }
      if (step.depends_on && step.depends_on.length > 0) {
        yaml += `    depends_on: ${step.depends_on.join(', ')}\n`;
      }
    }
    return yaml;
  };

  const handleYamlChange = useCallback((value: string) => {
    setYamlInput(value);
    try {
      loadFromYAML(value);
    } catch (e) {
      // Invalid YAML, don't update visual
    }
  }, [loadFromYAML]);

  const handleSave = useCallback(async () => {
    try {
      const pipeline = toPipeline();
      const build = await pipelineApi.create(pipelineToYaml(pipeline));
      alert(`Build #${build.id} created!`);
      onSave?.(pipeline);
    } catch (e) {
      console.error('Failed to create build:', e);
      alert('Failed to create build. Check console for details.');
    }
  }, [toPipeline, pipelineToYaml]);

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex' }}>
      {/* Canvas */}
      <div style={{ flex: 1, height: '100%' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, node) => setSelectedNode(node.id)}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
          defaultEdgeOptions={{
            type: 'smoothstep',
            style: { stroke: '#555', strokeWidth: 2 },
          }}
        >
          <Background color="#333" gap={20} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              const status = (node.data?.status as string) || 'pending';
              const colors: Record<string, string> = {
                pending: '#6b7280',
                running: '#3b82f6',
                passed: '#22c55e',
                failed: '#ef4444',
              };
              return colors[status] || colors.pending;
            }}
            style={{ background: '#1a1a1a' }}
          />
          
          <Panel position="top-right">
            <button
              onClick={handleSave}
              disabled={readOnly}
              style={{
                padding: '8px 16px',
                background: '#22c55e',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: readOnly ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                opacity: readOnly ? 0.5 : 1,
              }}
            >
              Save Pipeline
            </button>
          </Panel>
        </ReactFlow>
      </div>
      
      {/* YAML Editor Sidebar */}
      <div
        style={{
          width: 320,
          background: '#1a1a1a',
          borderLeft: '1px solid #333',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <h3 style={{ color: '#fff', marginBottom: 12, fontSize: 14 }}>
          Pipeline YAML
        </h3>
        <textarea
          value={yamlInput}
          onChange={(e) => handleYamlChange(e.target.value)}
          readOnly={readOnly}
          style={{
            flex: 1,
            background: '#0d0d0d',
            color: '#22c55e',
            border: '1px solid #333',
            borderRadius: 6,
            padding: 12,
            fontFamily: 'monospace',
            fontSize: 12,
            resize: 'none',
            outline: 'none',
          }}
        />
        <p style={{ color: '#666', fontSize: 11, marginTop: 12 }}>
          Edit YAML to update the visual graph. Changes are reflected in real-time.
        </p>
      </div>
    </div>
  );
}