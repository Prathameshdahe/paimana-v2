import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// /api goes to the backend through the dev server, so the session cookie is same-origin (as it is behind nginx in
// production) and the browser needs no CORS. The alert stream and the chat stream pass through it unbuffered.
// VITE_PROXY_TARGET points the dev server at another backend (a second checkout on 8010, say).
const proxy = {
  '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: false },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // one .env at the repo root is shared by the frontend and the backend
  envDir: path.resolve(__dirname, '..'),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    strictPort: true,
    proxy,
  },
  preview: {
    port: 3000,
    strictPort: true,
    proxy,
  },
})
