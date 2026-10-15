import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the FastAPI backend (../backend) is listening. This project uses
// port 8010 (not 8000, which other local apps often use). If the backend is
// on another port, run:  BACKEND_PORT=<port> npm run dev
const backendUrl = process.env.BACKEND_URL ?? `http://127.0.0.1:${process.env.BACKEND_PORT ?? '8010'}`

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
