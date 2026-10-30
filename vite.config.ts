import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'

const browserOnly = fileURLToPath(new URL('./src/domain/browser-only.ts', import.meta.url))

const apiProxy: ProxyOptions = {
  target: 'http://127.0.0.1:8008',
  configure(proxy) {
    proxy.on('error', (_error, _request, response) => {
      if (!('writeHead' in response) || response.headersSent || response.destroyed) return
      response.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' })
      response.end(JSON.stringify({
        code: 'BACKEND_UNAVAILABLE',
        message: '无法连接 GoGo 后端（127.0.0.1:8008），请先在 backend 目录启动后端服务'
      }))
    })
  }
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { fs: browserOnly, 'iconv-lite': browserOnly, jschardet: browserOnly }
  },
  server: {
    host: '127.0.0.1',
    port: 5178,
    strictPort: true,
    proxy: { '/api': apiProxy }
  },
  preview: {
    host: '127.0.0.1',
    port: 5178,
    strictPort: true,
    proxy: { '/api': apiProxy }
  }
})
