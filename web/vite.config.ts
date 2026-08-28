import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // The API stays on FastAPI in dev; in production FastAPI serves dist/ too,
    // so the frontend never needs to know an absolute backend URL.
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
})
