import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// Ports are doc 0 defaults: web dev server 5173, ingest API 8080.
export default defineConfig({
  plugins: [react()],

  // /fixtures/ is served as the static root so the fixture client can fetch the golden set
  // -- and, importantly, so segment.mp4 is served by Vite's static handler, which answers
  // HTTP range requests. The <video> element cannot seek without them.
  publicDir: resolve(__dirname, '..', 'fixtures'),

  server: {
    port: 5173,
    strictPort: true,
    // Only used when VITE_API_MODE=http. Component 3 talks to component 2 and nothing else.
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
    fs: {
      // The season config and fixtures live above web/ in the monorepo.
      allow: [resolve(__dirname, '..')],
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
