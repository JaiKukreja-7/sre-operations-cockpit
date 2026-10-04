import { defineConfig } from 'vitest/config';
export default defineConfig({
  build: { outDir: '../cockpit/static/dashboard', emptyOutDir: true, target: 'es2020' },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/docs': 'http://127.0.0.1:8000', '/openapi.json': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], exclude: ['e2e/**', 'node_modules/**'] },
});
