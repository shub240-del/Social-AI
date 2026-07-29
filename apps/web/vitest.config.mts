import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, '.') } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.tsx'],
    testTimeout: 30000,
    hookTimeout: 30000,
    env: { NEXT_PUBLIC_API_URL: 'http://127.0.0.1:8000' },
  },
});
