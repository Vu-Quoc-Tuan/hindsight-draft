/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/mock-studio': {
        target: 'http://127.0.0.1:8085',
        changeOrigin: true,
      },
    },
  },
  test: {
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
