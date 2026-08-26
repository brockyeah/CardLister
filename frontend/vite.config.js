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
  test: {
    // Tests run in a fixed *non-UTC* zone. CI runners default to UTC, where a
    // local date and a UTC date are the same thing — so a test for the
    // difference between them passes against the bug it is meant to catch
    // (soldDate.test.js asserts the zone is not UTC rather than trusting this).
    // America/New_York specifically: it is the owner's zone, it is west of UTC
    // where the mark-sold bug bit, and it observes DST, so a date helper that
    // quietly assumes a fixed offset has somewhere to fail.
    env: { TZ: 'America/New_York' },
  },
})
