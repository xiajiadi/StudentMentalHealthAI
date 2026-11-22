import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(() => {
  const backend = new URL(process.env.PSYNOVA_BACKEND_ORIGIN || 'http://127.0.0.1:8088')
  if (backend.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(backend.hostname) ||
    backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash) {
    throw new Error('PSYNOVA_BACKEND_ORIGIN must be a loopback HTTP origin')
  }
  const proxy = { '/api/v1': { target: backend.origin, changeOrigin: true } }
  return {
    plugins: [vue(), tailwindcss()],
    server: {
      host: '127.0.0.1',
      port: 4173,
      proxy,
    },
    preview: {
      host: '127.0.0.1',
      port: 4174,
      proxy,
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
  }
})
