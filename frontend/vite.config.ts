import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // API_TARGET lets the dev server point at a backend on another port.
  server: { port: 5173, proxy: { '/api': process.env.API_TARGET || 'http://localhost:8000' } },
})
