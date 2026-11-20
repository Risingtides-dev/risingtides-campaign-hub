import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api/sound-assignments': {
        target: 'http://127.0.0.1:5055',
        changeOrigin: true,
        configure(proxy) {
          // The browser talks to Vite on one origin; Flask sees the proxy target.
          proxy.on('proxyReq', (request) => request.setHeader('Origin', 'http://127.0.0.1:5055'))
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split heavy vendors into their own chunks so the initial payload
        // doesn't carry recharts (only 2 of 19 routes use it) on first paint.
        manualChunks: {
          recharts: ['recharts'],
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query', '@tanstack/react-table'],
        },
      },
    },
  },
})
