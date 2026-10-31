import type { AnalysisResult, ExplanationResult, PositionRequest } from '../domain/types'

async function post<T>(path: string, body: unknown, timeout: number): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeout)
  try {
    let response: Response
    try {
      response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      })
    } catch {
      throw new Error(controller.signal.aborted ? '请求超时，请稍后手动重试' : '无法连接本地服务')
    }
    let data: unknown
    try { data = await response.json() } catch { throw new Error('无法连接本地服务，或服务返回了无效响应') }
    if (!response.ok) {
      const error = data as { code?: string, message?: string }
      if (path.startsWith('/api/settings/') && (
        response.status === 404 || response.status === 405 ||
        (response.status === 400 && error.message === '接口路径或请求方法不正确')
      )) {
        throw new Error('当前后端尚未提供配置接口。请停止旧后端，在 backend 目录重新运行 uv run --frozen python run.py，然后点击“重新读取”')
      }
      throw new Error(typeof error.message === 'string' ? error.message : '本地服务请求失败，请稍后重试')
    }
    return data as T
  } finally {
    window.clearTimeout(timer)
  }
}

export function analyzePosition(request: PositionRequest) {
  return post<AnalysisResult>('/api/analyze', request, 130_000)
}

export function explainPosition(request: PositionRequest, analysis: AnalysisResult, candidateIndex = 0) {
  return post<ExplanationResult>('/api/explain', { ...request, analysis, candidateIndex }, 70_000)
}

export interface AnalysisSettings {
  aiUrl: string
  maxTokens: number
  katagoPath: string
  katagoModelPath: string
  visits: number
  candidateCount: number
  stopMove: number
  apiKeyConfigured: boolean
}

export function readSettings() {
  return post<AnalysisSettings>('/api/settings/read', {}, 10_000)
}

export function saveSettings(settings: Omit<AnalysisSettings, 'apiKeyConfigured'> & { apiKey: string }) {
  return post<AnalysisSettings>('/api/settings/save', settings, 10_000)
}

export type EngineTier = 'light' | 'balanced' | 'advanced'

export interface EngineStatus {
  platform: 'macos-arm64' | 'macos-x64' | 'windows-x64' | 'unsupported'
  options: {
    tier: EngineTier
    name: string
    description: string
    available: boolean
    message: string
  }[]
  installedTier: EngineTier | null
  state: 'idle' | 'downloading-engine' | 'extracting' | 'downloading-model' | 'configuring' | 'completed' | 'failed'
  tier: EngineTier | null
  downloadedBytes: number
  totalBytes: number | null
  message: string
  katagoPath: string
  katagoModelPath: string
}

export interface SettingsTestStage {
  state: 'passed' | 'failed' | 'skipped'
  elapsedMs: number
  message: string
}

export interface SettingsTestResult {
  katago: SettingsTestStage
  ai: SettingsTestStage
}

export function readEngineStatus() {
  return post<EngineStatus>('/api/engine/status', {}, 10_000)
}

export function installEngine(tier: EngineTier) {
  return post<EngineStatus>('/api/engine/install', { tier }, 10_000)
}

export function testSettings() {
  return post<SettingsTestResult>('/api/settings/test', {}, 200_000)
}
