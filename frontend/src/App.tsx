import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import PipelineEditor from './pages/PipelineEditor';
import './index.css';

function App() {
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
        <span style={{ color: '#666', fontSize: 12 }}>
          Pipeline Editor
        </span>
      </header>
      
      <main style={{ flex: 1 }}>
        <PipelineEditor
          onSave={(pipeline) => {
            console.log('Saving pipeline:', pipeline);
            alert('Pipeline saved! Check console for output.');
          }}
        />
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);