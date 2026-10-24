import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// `vite --mode e2e` drops the devtools overlay so axe only sees the console itself.
export default defineConfig(({ mode }) => ({
  plugins: [vue(), ...(mode === 'e2e' ? [] : [vueDevTools()]), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: { '/api': 'http://localhost:8001', '/console': 'http://localhost:8001' },
  },
}))
