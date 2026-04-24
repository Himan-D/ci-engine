import { create } from 'zustand';
import {
  Node,
  Edge,
  Connection,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  NodeChange,
  EdgeChange,
} from '@xyflow/react';
import { Pipeline, PipelineStep } from '../types/pipeline';

interface PipelineEditorState {
  nodes: Node[];
  edges: Edge[];
  pipeline: Pipeline | null;
  pipelineYAML: string;
  selectedNodeId: string | null;
  
  // Actions
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addStep: (step: PipelineStep) => void;
  updateStep: (id: string, data: Partial<PipelineStep>) => void;
  deleteStep: (id: string) => void;
  setPipeline: (pipeline: Pipeline) => void;
  setPipelineYAML: (yaml: string) => void;
  setSelectedNode: (id: string | null) => void;
  loadFromYAML: (yaml: string) => void;
  toPipeline: () => Pipeline;
}

const generateId = () => Math.random().toString(36).substring(2, 9);

// Parse YAML-like pipeline to nodes
function yamlToPipeline(yaml: string): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const steps = yaml.split('\n').filter(line => line.trim().startsWith('- label:'));
  
  let y = 0;
  const stepMap = new Map<string, string>();
  
  steps.forEach((stepLine, index) => {
    const labelMatch = stepLine.match(/- label: ["'](.+?)["']/);
    const label = labelMatch ? labelMatch[1] : `Step ${index + 1}`;
    const stepId = generateId();
    stepMap.set(label, stepId);
    
    nodes.push({
      id: stepId,
      type: 'step',
      position: { x: 250, y },
      data: { label, status: 'pending' },
    });
    
    y += 100;
  });
  
  // Add edges based on order
  const stepLabels = Array.from(stepMap.keys());
  for (let i = 0; i < stepLabels.length - 1; i++) {
    const source = stepMap.get(stepLabels[i])!;
    const target = stepMap.get(stepLabels[i + 1])!;
    edges.push({
      id: `${source}-${target}`,
      source,
      target,
      type: 'smoothstep',
    });
  }
  
  return { nodes, edges };
}

export const usePipelineStore = create<PipelineEditorState>((set, get) => ({
  nodes: [],
  edges: [],
  pipeline: null,
  pipelineYAML: '',
  selectedNodeId: null,

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  
  onNodesChange: (changes) => set({
    nodes: applyNodeChanges(changes, get().nodes),
  }),
  
  onEdgesChange: (changes) => set({
    edges: applyEdgeChanges(changes, get().edges),
  }),
  
  onConnect: (connection) => set({
    edges: addEdge({ ...connection, type: 'smoothstep' }, get().edges),
  }),
  
  addStep: (step) => {
    const newNode: Node = {
      id: step.id || generateId(),
      type: 'step',
      position: { x: 250, y: get().nodes.length * 100 },
      data: { 
        label: step.label,
        command: step.command,
        status: 'pending',
      },
    };
    set({ nodes: [...get().nodes, newNode] });
  },
  
  updateStep: (id, data) => set({
    nodes: get().nodes.map(node => 
      node.id === id 
        ? { ...node, data: { ...node.data, ...data } }
        : node
    ),
  }),
  
  deleteStep: (id) => set({
    nodes: get().nodes.filter(node => node.id !== id),
    edges: get().edges.filter(edge => 
      edge.source !== id && edge.target !== id
    ),
  }),
  
  setPipeline: (pipeline) => {
    const { nodes, edges } = yamlToPipeline(pipeline.steps.map(s => 
      `- label: ${s.label}`
    ).join('\n'));
    set({ pipeline, nodes, edges });
  },
  
  setPipelineYAML: (yaml) => {
    const { nodes, edges } = yamlToPipeline(yaml);
    set({ pipelineYAML: yaml, nodes, edges });
  },
  
  setSelectedNode: (id) => set({ selectedNodeId: id }),
  
  loadFromYAML: (yaml) => {
    const { nodes, edges } = yamlToPipeline(yaml);
    set({ nodes, edges, pipelineYAML: yaml });
  },
  
  toPipeline: () => {
    const { nodes } = get();
    const steps: PipelineStep[] = nodes.map(node => ({
      id: node.id,
      label: node.data.label as string,
      command: node.data.command as string,
    }));
    return { steps };
  },
}));