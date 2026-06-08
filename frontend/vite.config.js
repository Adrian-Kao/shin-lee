import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Q4: Vite for product SPA. SSR is a separate Next.js app (out of POC scope).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy gateway calls so we can hit /api/* from the SPA without CORS
      // friction. Gateway runs on :8010 (ai_engine on :8011) per
      // scripts/start_backend.sh — do NOT change to :8000.
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, '')
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        // Split heavy/independent deps into long-cacheable vendor chunks.
        // @sentry is intentionally listed: when a DSN is configured it loads
        // via dynamic import() and Rollup emits it as its own async chunk; in
        // DSN-less builds it is never imported and so never fetched.
        manualChunks: {
          'vendor-react': ['react', 'react-dom'],
          'vendor-router': ['react-router-dom'],
          'vendor-i18n': ['i18next', 'react-i18next'],
          'vendor-icons': ['lucide-react'],
          'vendor-sentry': ['@sentry/react']
        }
      }
    }
  }
});
