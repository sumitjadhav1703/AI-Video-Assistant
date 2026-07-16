import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api -> the backend so browser calls are same-origin
// in development (no CORS wall). Production builds ignore this entirely and use
// VITE_BACKEND_URL directly. Set VITE_BACKEND_URL in a .env to point dev at a
// different backend; otherwise it falls back to the deployed Render URL.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_BACKEND_URL || 'https://ai-video-assistant-backend.onrender.com'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          secure: true,
          rewrite: (p) => p.replace(/^\/api/, ''),
        },
      },
    },
  }
})
