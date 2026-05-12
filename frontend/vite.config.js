import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Q4: Vite for product SPA. SSR is a separate Next.js app (out of POC scope).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy gateway calls so we can hit /api/* from the SPA without CORS friction
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, '')
      }
    }
  }
});
