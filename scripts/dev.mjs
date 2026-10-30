import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const children = new Set()
let stopping = false

function stop(code) {
  if (stopping) return
  stopping = true
  process.exitCode = code
  for (const child of children) {
    try { process.kill(-child.pid, 'SIGTERM') } catch {}
  }
  const timer = setTimeout(() => {
    for (const child of children) {
      try { process.kill(-child.pid, 'SIGKILL') } catch {}
    }
  }, 5000)
  timer.unref()
}

function launch(command, args, cwd, label, service = true) {
  const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true })
  child.on('error', error => {
    console.error(`${label}启动失败：${error.code === 'ENOENT' ? `请先安装 ${command}` : error.message}`)
    stop(1)
  })
  child.on('exit', (code, signal) => {
    if (service && !stopping) {
      console.error(`${label}已退出（${signal || code}），正在停止其他服务`)
      stop(code || 1)
    }
  })
  child.on('close', () => children.delete(child))
  if (child.pid) children.add(child)
  return child
}

async function requireFreePort(port) {
  await new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', () => reject(new Error(`127.0.0.1:${port} 无法监听，请先停止占用该端口的服务`)))
    server.listen(port, '127.0.0.1', () => server.close(resolve))
  })
}

process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))

try {
  await requireFreePort(5178)
  await requireFreePort(8008)
  if (!existsSync(new URL('../node_modules/vite/bin/vite.js', import.meta.url))) {
    console.log('首次启动，正在安装前端依赖…')
    const installer = launch('npm', ['ci'], root, '依赖安装', false)
    await new Promise((resolve, reject) => {
      installer.once('error', reject)
      installer.once('exit', code => code === 0 ? resolve() : reject(new Error('前端依赖安装未完成')))
    })
  }
  if (!stopping) {
    launch('uv', ['run', '--frozen', 'python', 'run.py'], `${root}backend`, '后端')
    launch(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5178', '--strictPort'], root, '前端')
    console.log('正在启动 GoGo，请在 Google Chrome 打开 http://127.0.0.1:5178，按 Ctrl+C 停止全部服务')
  }
} catch (error) {
  console.error(error.message)
  stop(1)
}
