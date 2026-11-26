import { defineConfig, searchForWorkspaceRoot, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { createReadStream, readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

const educationArticles = fileURLToPath(new URL(
  '../09_backend/src/smhai_backend/domains/student_education_articles.json', import.meta.url,
))

function workspaceImageAssets(): Plugin {
  const directory = 'assets/ocr-v7'
  const files = new Map(Object.entries({
    'worker.min.js': 'tesseract.js/dist/worker.min.js',
    'worker.min.js.LICENSE.txt': 'tesseract.js/dist/worker.min.js.LICENSE.txt',
    'tesseract-core-lstm.wasm.js': 'tesseract.js-core/tesseract-core-lstm.wasm.js',
    'tesseract-core-simd-lstm.wasm.js': 'tesseract.js-core/tesseract-core-simd-lstm.wasm.js',
    'tesseract-core-relaxedsimd-lstm.wasm.js': 'tesseract.js-core/tesseract-core-relaxedsimd-lstm.wasm.js',
    'tesseract-core.LICENSE.txt': 'tesseract.js-core/LICENSE',
    'eng.traineddata.gz': '@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz',
    'chi_sim.traineddata.gz': '@tesseract.js-data/chi_sim/4.0.0_best_int/chi_sim.traineddata.gz',
  }))
  const source = (path: string) => new URL(`./node_modules/${path}`, import.meta.url)
  return {
    name: 'workspace-image-assets',
    configureServer(server) {
      server.middlewares.use(`/${directory}`, (request, response, next) => {
        const name = (request.url || '').slice(1).split('?')[0]
        const path = files.get(name)
        if (!path) return next()
        response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : 'application/octet-stream')
        createReadStream(source(path)).on('error', next).pipe(response)
      })
    },
    generateBundle() {
      for (const [name, path] of files) {
        this.emitFile({ type: 'asset', fileName: `${directory}/${name}`, source: readFileSync(source(path)) })
      }
    },
  }
}

export default defineConfig(() => {
  const backend = new URL(process.env.PSYNOVA_BACKEND_ORIGIN || 'http://127.0.0.1:8088')
  if (backend.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(backend.hostname) ||
    backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash) {
    throw new Error('PSYNOVA_BACKEND_ORIGIN must be a loopback HTTP origin')
  }
  const proxy = { '/api/v1': { target: backend.origin, changeOrigin: true } }
  return {
    plugins: [vue(), tailwindcss(), workspaceImageAssets()],
    server: {
      host: '127.0.0.1',
      port: 4173,
      proxy,
      fs: { allow: [searchForWorkspaceRoot(process.cwd()), educationArticles] },
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
