import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the FastAPI backend (../backend) is listening. Defaults to port 8000,
// as in the assignment. If the backend is on another port (e.g. 8010 because
// 8000 is busy), run:  BACKEND_PORT=8010 npm run dev -- --port 5180 --strictPort
const backendUrl = process.env.BACKEND_URL ?? `http://127.0.0.1:${process.env.BACKEND_PORT ?? '8000'}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Forward API calls to the FastAPI backend. The browser only ever talks
      // to /api on this dev server, so no keys or backend config reach it.
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
})
