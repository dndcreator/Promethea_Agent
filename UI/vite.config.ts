import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  root: '.',
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.PROMETHEA_GATEWAY_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
