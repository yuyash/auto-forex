import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'));

// Group large vendor dependencies into separate chunks. Vite 8 / Rollup 4
// type `output.manualChunks` as a function (the legacy object form is no
// longer accepted by the types), so we map module ids (node_modules paths)
// to chunk names instead.
const vendorChunks: Record<string, string[]> = {
  react: ['react', 'react-dom', 'react-router-dom'],
  mui: [
    '@mui/material',
    '@mui/icons-material',
    '@emotion/react',
    '@emotion/styled',
  ],
  charts: ['@mui/x-charts', 'lightweight-charts', 'd3-scale'],
  query: ['@tanstack/react-query'],
  forms: ['react-hook-form', '@hookform/resolvers', 'zod'],
  i18n: ['i18next', 'react-i18next'],
};

function manualChunks(id: string): string | undefined {
  if (!id.includes('/node_modules/')) return undefined;
  for (const [chunk, packages] of Object.entries(vendorChunks)) {
    if (packages.some((name) => id.includes(`/node_modules/${name}/`))) {
      return chunk;
    }
  }
  return undefined;
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    exclude: ['node_modules', 'dist', 'tests/e2e'],
    testTimeout: 60000,
    hookTimeout: 30000,
    slowTestThreshold: 1000,
  },
});
