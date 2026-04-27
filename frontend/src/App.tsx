import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import PipelineEditor from './pages/PipelineEditor';
import BuildList from './pages/BuildList';
import BuildGraph from './pages/BuildGraph';
import AgentStatus from './pages/AgentStatus';
import './index.css';

type Tab = 'pipeline' | 'builds' | 'graph' | 'agents';

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('pipeline');

  const tabs: { id: Tab; label: string }[] = [
    { id: 'pipeline', label: 'Pipeline Editor' },
    { id: 'builds', label: 'Builds' },
    { id: 'graph', label: 'Build Graph' },
    { id: 'agents', label: 'Agents' },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case 'pipeline':
        return <PipelineEditor />;
      case 'builds':
        return <BuildList />;
      case 'graph':
        return <BuildGraph />;
      case 'agents':
        return <AgentStatus />;
      default:
        return <PipelineEditor />;
    }
  };

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header
        style={{
          padding: '12px 24px',
          background: '#0d0d0d',
          borderBottom: '1px solid #333',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <h1 style={{ color: '#fff', margin: 0, fontSize: 18 }}>
          CI Engine
        </h1>
        <nav style={{ display: 'flex', gap: 4 }}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '8px 16px',
                background: activeTab === tab.id ? '#333' : 'transparent',
                border: 'none',
                borderRadius: 4,
                color: activeTab === tab.id ? '#fff' : '#888',
                cursor: 'pointer',
                fontSize: 13,
                transition: 'all 0.2s',
              }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main style={{ flex: 1, overflow: 'hidden' }}>{renderContent()}</main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);