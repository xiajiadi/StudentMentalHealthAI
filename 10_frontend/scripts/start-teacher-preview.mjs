import { spawn } from 'node:child_process'
import { closeSync, existsSync, mkdirSync, openSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:net'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(scriptDirectory, '..')
const viteEntry = join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
const port = 4206
const previewUrl = `http://127.0.0.1:${port}/teacher/overview`
const logRoot = join(tmpdir(), 'psynova-teacher-preview')
const stdoutPath = join(logRoot, '4206.stdout.log')
const stderrPath = join(logRoot, '4206.stderr.log')
const delay = (ms) => new Promise((resolveDelay) => setTimeout(resolveDelay, ms))

if (!existsSync(viteEntry)) {
  throw new Error(`Frontend dependencies are missing under ${frontendRoot}; install them once before using the fast start.`)
}

async function isTeacherPreviewReady() {
  try {
    const response = await fetch(previewUrl, { signal: AbortSignal.timeout(1000) })
    const html = await response.text()
    return response.status === 200 && html.includes('PsyNova 教育支持工作台') && html.includes('/@vite/client')
  } catch {
    return false
  }
}

async function waitForTeacherPreview(timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isTeacherPreviewReady()) return true
    await delay(200)
  }
  return false
}

function assertPortAvailable() {
  return new Promise((resolvePort, rejectPort) => {
    const probe = createServer()
    probe.once('error', rejectPort)
    probe.listen(port, '127.0.0.1', () => probe.close(resolvePort))
  })
}

async function main() {
  try {
    if (await isTeacherPreviewReady()) {
      process.stdout.write(`Teacher development preview is already ready: ${previewUrl}\n`)
      return
    }

    try {
      await assertPortAvailable()
    } catch (error) {
      if (error?.code === 'EADDRINUSE' && await waitForTeacherPreview(3000)) {
        process.stdout.write(`Teacher development preview is already ready: ${previewUrl}\n`)
        return
      }
      throw new Error(`Port ${port} is occupied by a service that is not the expected PsyNova Vite preview.`)
    }

    mkdirSync(logRoot, { recursive: true })
    const stdoutFd = openSync(stdoutPath, 'a')
    const stderrFd = openSync(stderrPath, 'a')
    try {
      const child = spawn(process.execPath, [
        viteEntry,
        '--host', '127.0.0.1',
        '--port', String(port),
        '--strictPort',
      ], {
        cwd: frontendRoot,
        detached: true,
        windowsHide: true,
        stdio: ['ignore', stdoutFd, stderrFd],
      })
      child.unref()
    } finally {
      closeSync(stdoutFd)
      closeSync(stderrFd)
    }

    if (await waitForTeacherPreview(8000)) {
      process.stdout.write(`Teacher development preview is ready: ${previewUrl}\n`)
      process.stdout.write(`Startup output is saved under '${logRoot}'.\n`)
      return
    }

    throw new Error(`Vite did not open port ${port}. Inspect '${stdoutPath}' and '${stderrPath}'.`)
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : 'Preview startup failed'}\n`)
    process.exitCode = 1
  }
}

await main()
