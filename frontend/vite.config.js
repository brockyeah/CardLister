import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During dev we run Vite on :5173 and proxy /api and /uploads to FastAPI on :8000.
// In production the FastAPI app serves the built bundle directly so the proxy is irrelevant.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
