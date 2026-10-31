<script setup lang='ts'>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { installEngine, readEngineStatus, readSettings, saveSettings, testSettings } from '../services/api'
import type { AnalysisSettings, EngineStatus, EngineTier, SettingsTestResult } from '../services/api'

const emit = defineEmits<{ saved: [] }>()
const settings = ref<AnalysisSettings | null>(null)
const apiKey = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const success = ref(false)
const engine = ref<EngineStatus | null>(null)
const selectedTier = ref<EngineTier>('light')
const starting = ref(false)
const testing = ref(false)
const testResult = ref<SettingsTestResult | null>(null)
const engineError = ref('')
let pollTimer: ReturnType<typeof window.setTimeout> | undefined
let disposed = false

const installing = computed(() => engine.value !== null && [
  'downloading-engine', 'extracting', 'downloading-model', 'configuring'
].includes(engine.value.state))
const busy = computed(() => saving.value || testing.value || starting.value || installing.value)
const selectedOption = computed(() => engine.value?.options.find(option => option.tier === selectedTier.value))
const downloading = computed(() => engine.value?.state === 'downloading-engine' || engine.value?.state === 'downloading-model')
const showLightSwitch = computed(() => engine.value?.installedTier !== 'light' && testResult.value !== null && (
  testResult.value.katago.state === 'failed' || testResult.value.katago.elapsedMs >= 15_000
))

function clearResult() {
  testResult.value = null
  success.value = false
}

watch([settings, apiKey], clearResult, { deep: true, flush: 'sync' })

function sizeLabel(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function stageLabel(state: 'passed' | 'failed' | 'skipped') {
  return { passed: '通过', failed: '失败', skipped: '未执行' }[state]
}

function schedulePoll() {
  window.clearTimeout(pollTimer)
  if (!disposed && installing.value) {
    pollTimer = window.setTimeout(() => { void refreshEngine() }, 1000)
  }
}

async function refreshEngine(initial = false) {
  const wasInstalling = installing.value
  try {
    const next = await readEngineStatus()
    if (disposed) return
    engine.value = next
    engineError.value = ''
    if (initial) selectedTier.value = (installing.value ? next.tier : next.installedTier) ?? 'light'
    if ((wasInstalling || initial) && next.state === 'completed' && settings.value) {
      // 安装仅回填两个引擎字段，保留表单里尚未保存的 AI 配置与密钥。
      settings.value.katagoPath = next.katagoPath
      settings.value.katagoModelPath = next.katagoModelPath
      if (wasInstalling) emit('saved')
    }
  } catch (cause) {
    if (!disposed) engineError.value = cause instanceof Error ? cause.message : '读取安装状态失败'
  } finally {
    schedulePoll()
  }
}

async function startInstall(tier: EngineTier = selectedTier.value) {
  if (busy.value) return
  selectedTier.value = tier
  starting.value = true
  engineError.value = ''
  clearResult()
  try {
    const next = await installEngine(tier)
    if (disposed) return
    engine.value = next
  } catch (cause) {
    if (!disposed) {
      engineError.value = cause instanceof Error ? cause.message : '无法开始安装'
      // 请求中断不代表后台未启动，重新读取任务状态，避免误导用户重复安装。
      try { engine.value = await readEngineStatus() } catch { /* 保留启动错误，允许手动刷新。 */ }
    }
  } finally {
    starting.value = false
    schedulePoll()
  }
}

async function load() {
  loading.value = true
  error.value = ''
  success.value = false
  try {
    settings.value = await readSettings()
    if (!disposed) await refreshEngine(true)
  }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取配置失败' }
  finally { loading.value = false }
}

async function submit(event: Event) {
  if (!settings.value || busy.value) return
  const withTest = (event as SubmitEvent).submitter?.getAttribute('value') === 'test'
  saving.value = true
  error.value = ''
  clearResult()
  try {
    const { apiKeyConfigured, ...values } = settings.value
    settings.value = await saveSettings({ ...values, apiKey: apiKey.value })
    apiKey.value = ''
    success.value = true
    emit('saved')
    await refreshEngine()
    if (withTest) {
      testing.value = true
      testResult.value = await testSettings()
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存配置失败' }
  finally {
    saving.value = false
    testing.value = false
  }
}
onMounted(load)
onUnmounted(() => {
  disposed = true
  window.clearTimeout(pollTimer)
})
</script>

<template>
  <section class='settings-panel' aria-label='分析配置' :aria-busy='loading || busy'>
    <p v-if='loading' class='muted' role='status'>正在读取配置…</p>
    <form v-if='settings' @submit.prevent='submit'>
      <p class='micro'>首页与棋谱页共用配置，保存后用于后续分析。AI 接口需兼容当前 DeepSeek 请求协议。</p>
      <fieldset :disabled='loading || busy' class='settings-fields'>
        <section class='engine-setup' aria-label='围棋分析引擎'>
          <h3>围棋分析引擎</h3>
          <p class='micro'>选择档位 → 下载安装 → 保存并测试。无需 Homebrew，默认轻量版。Mac 使用 Metal / OpenCL，Windows 使用 CPU；已有 KataGo 将自动复用。</p>
          <template v-if='engine'>
            <div class='engine-options'>
              <label v-for='option in engine.options' :key='option.tier' class='engine-option' :class='{ selected: selectedTier === option.tier }'>
                <input v-model='selectedTier' type='radio' name='engine-tier' :value='option.tier' />
                <span><strong>{{ option.name }}{{ option.tier === 'light' ? ' · 默认' : '' }}</strong><small>{{ option.description }}</small><small v-if='engine.installedTier === option.tier'>当前已配置</small></span>
              </label>
            </div>
            <p class='micro'>档位不保证适合所有电脑。较大模型运行缓慢或失败时，可切换轻量版。</p>
            <p v-if='selectedOption?.message' class='notice' role='status'>{{ selectedOption.message }}</p>
            <button type='button' class='button secondary' :disabled='busy || !selectedOption?.available' @click='startInstall()'>{{ starting ? '正在准备…' : engine.state === 'failed' ? '重试下载安装' : '下载安装' }}</button>
            <button type='button' class='text-button' :disabled='busy' @click='refreshEngine()'>重新检测引擎</button>
          </template>
          <p v-else-if='!engineError' class='micro' role='status'>正在读取引擎安装信息…</p>
          <details class='engine-advanced'>
            <summary>高级设置 · 已有引擎或本机服务</summary>
            <label class='form-field'>KataGo 程序路径<input v-model.trim='settings.katagoPath' type='text' placeholder='KataGo 程序的绝对路径' /></label>
            <label class='form-field'>KataGo 权重路径<input v-model.trim='settings.katagoModelPath' type='text' placeholder='模型文件的绝对路径' /><span class='micro'>程序与权重同时填写。两项留空时使用原本的本机引擎服务。自动安装完成后将回填这两项。</span></label>
          </details>
        </section>
        <label class='form-field'>AI 分析 URL<input v-model.trim='settings.aiUrl' type='url' required placeholder='https://api.deepseek.com/chat/completions' /></label>
        <label class='form-field'>API 密钥<input v-model='apiKey' type='password' autocomplete='new-password' :placeholder='settings.apiKeyConfigured ? "已配置，留空保留现有密钥" : "请输入 API 密钥"' /><span class='micro'>密钥保存在本机后端，不写入浏览器存储。</span></label>
        <label class='form-field'>最大 token 数<input v-model.number='settings.maxTokens' type='number' min='1' step='1' required /></label>
        <div class='settings-numbers'>
          <label class='form-field'>每手分析深度（搜索次数）<input v-model.number='settings.visits' type='number' min='1' step='1' required /></label>
          <label class='form-field'>分析选点数量<input v-model.number='settings.candidateCount' type='number' min='1' max='3' step='1' required /><span class='micro'>按引擎推荐顺序取前 1～3 个点。</span></label>
        </div>
        <label class='form-field'>批量分析到第几手停止<input v-model.number='settings.stopMove' type='number' min='1' step='1' required /><span class='micro'>从第 1 手开始，包含指定手数；超过棋谱总手数时在最后一手停止。保存后在棋谱页点击“开始批量分析”。</span></label>
      </fieldset>
      <div v-if='engine && engine.state !== "idle"' class='engine-progress' :class='{ "notice error": engine.state === "failed" }' role='status' aria-live='polite'>
        <p>{{ engine.message }}</p>
        <template v-if='downloading'>
          <progress v-if='engine.totalBytes !== null' :value='engine.downloadedBytes' :max='engine.totalBytes' aria-label='当前文件下载进度'></progress>
          <p class='micro'>已下载 {{ sizeLabel(engine.downloadedBytes) }}<template v-if='engine.totalBytes !== null'> / {{ sizeLabel(engine.totalBytes) }} · {{ Math.floor(engine.downloadedBytes / engine.totalBytes * 100) }}%</template></p>
        </template>
        <p v-if='installing' class='micro'>刷新页面后仍可查看进度，请保持本机后端运行。</p>
      </div>
      <p v-if='engineError' class='notice error' role='alert'>{{ engineError }} <button type='button' class='text-button' :disabled='starting || saving || testing' @click='refreshEngine()'>重新读取安装状态</button></p>
      <div class='settings-footer'>
        <span v-if='success' class='micro' role='status'>配置已保存，下次分析生效。</span>
        <button type='submit' class='button secondary' :disabled='loading || busy'>{{ saving && !testing ? '保存中…' : '保存配置' }}</button>
        <button type='submit' value='test' class='button primary' :disabled='loading || busy'>{{ testing ? '正在测试…' : '保存并测试' }}</button>
      </div>
      <p class='micro'>“保存并测试”会分析一个内置局面，并产生一次 AI 解释用量。仅保存不会调用引擎或 AI。</p>
      <p v-if='testing' class='micro' role='status'>正在依次测试围棋引擎和 AI 解释，首次启动可能需要较长时间…</p>
      <section v-if='testResult' class='settings-test-results' aria-label='配置测试结果' aria-live='polite'>
        <div v-for='item in [{ label: "围棋引擎", result: testResult.katago }, { label: "AI 解释", result: testResult.ai }]' :key='item.label' class='settings-test-stage' :class='item.result.state'>
          <strong>{{ item.label }} · {{ stageLabel(item.result.state) }}<template v-if='item.result.state !== "skipped"'> · {{ (item.result.elapsedMs / 1000).toFixed(1) }} 秒</template></strong>
          <p>{{ item.result.message }}</p>
        </div>
        <p v-if='testResult.katago.state === "passed" && testResult.ai.state === "passed"'>配置成功，可以开始复盘。</p>
        <p v-if='testResult.katago.state === "passed"' class='micro'>快速测试通过（32 次搜索），实际复盘耗时取决于模型与搜索次数。</p>
        <button v-if='showLightSwitch' type='button' class='button secondary' :disabled='busy || !engine?.options.find(option => option.tier === "light")?.available' @click='startInstall("light")'>切换轻量版并下载安装</button>
      </section>
    </form>
    <p v-if='error' class='notice error' role='alert'>{{ error }}</p>
    <button v-if='!settings && !loading' class='button secondary' @click='load'>重新读取</button>
  </section>
</template>
