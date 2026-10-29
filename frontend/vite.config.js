import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/auth': { target: 'http://127.0.0.1:8001', changeOrigin: false },
      '/folders': { target: 'http://127.0.0.1:8001', changeOrigin: false },
      '/public': { target: 'http://127.0.0.1:8001', changeOrigin: false },
      '/files': { target: 'http://127.0.0.1:8001', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8001', changeOrigin: false },
    },
  },
})
