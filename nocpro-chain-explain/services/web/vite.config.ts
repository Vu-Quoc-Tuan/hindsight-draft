/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Defaults preserve `make dev`; dev-demo can run independently by
      // overriding these two local proxy targets.
      '/api': process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
      '/mock-studio': {
        target: process.env.VITE_MOCK_PROXY_TARGET || 'http://127.0.0.1:8085',
        changeOrigin: true,
      },
    },
  },
  test: {
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
