import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.env, '');
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8000';
  
  return {
    plugins: [react()],
    server: {
      port: parseInt(env.VITE_PORT || '3000', 10),
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws': {
          target: apiTarget.replace('http', 'ws'),
          ws: true,
        },
      },
    },
  };
});