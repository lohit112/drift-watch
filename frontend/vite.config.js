import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies the API to the FastAPI backend so `npm run dev`
// and `uvicorn backend.main:app` can run side by side. For the demo,
// `npm run build` + the backend's static mount serves everything on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/merchants': 'http://127.0.0.1:8000',
      '/episodes': 'http://127.0.0.1:8000',
    },
  },
})
