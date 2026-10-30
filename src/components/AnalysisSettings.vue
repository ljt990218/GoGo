<script setup lang='ts'>
import { onMounted, ref } from 'vue'
import { readSettings, saveSettings } from '../services/api'
import type { AnalysisSettings } from '../services/api'

const emit = defineEmits<{ saved: [] }>()
const settings = ref<AnalysisSettings | null>(null)
const apiKey = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const success = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try { settings.value = await readSettings() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取配置失败' }
  finally { loading.value = false }
}

async function submit() {
  if (!settings.value || saving.value) return
  saving.value = true
  error.value = ''
  success.value = false
  try {
    const { apiKeyConfigured, ...values } = settings.value
    settings.value = await saveSettings({ ...values, apiKey: apiKey.value })
    apiKey.value = ''
    success.value = true
    emit('saved')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存配置失败' }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section class='settings-panel' aria-label='分析配置' :aria-busy='loading || saving'>
    <p v-if='loading' class='muted' role='status'>正在读取配置…</p>
    <form v-if='settings' @submit.prevent='submit'>
      <p class='micro'>首页与棋谱页共用配置，保存后用于后续分析。AI 接口需兼容当前 DeepSeek 请求协议。</p>
      <fieldset :disabled='saving' class='settings-fields'>
        <label class='form-field'>AI 分析 URL<input v-model.trim='settings.aiUrl' type='url' required placeholder='https://api.deepseek.com/chat/completions' /></label>
        <label class='form-field'>API 密钥<input v-model='apiKey' type='password' autocomplete='new-password' :placeholder='settings.apiKeyConfigured ? "已配置，留空保留现有密钥" : "请输入 API 密钥"' /><span class='micro'>密钥保存在本机后端，不写入浏览器存储。</span></label>
        <label class='form-field'>最大 token 数<input v-model.number='settings.maxTokens' type='number' min='1' step='1' required /></label>
        <label class='form-field'>KataGo（Cutgo）程序路径<input v-model.trim='settings.katagoPath' type='text' placeholder='/opt/homebrew/bin/katago' /></label>
        <label class='form-field'>KataGo 权重路径<input v-model.trim='settings.katagoModelPath' type='text' placeholder='模型文件的绝对路径' /><span class='micro'>程序与权重同时填写。两项留空时使用原本的本机引擎服务。</span></label>
        <div class='settings-numbers'>
          <label class='form-field'>每手分析深度（搜索次数）<input v-model.number='settings.visits' type='number' min='1' step='1' required /></label>
          <label class='form-field'>分析选点数量<input v-model.number='settings.candidateCount' type='number' min='1' max='3' step='1' required /><span class='micro'>按引擎推荐顺序取前 1～3 个点。</span></label>
        </div>
        <label class='form-field'>批量分析到第几手停止<input v-model.number='settings.stopMove' type='number' min='1' step='1' required /><span class='micro'>从第 1 手开始，包含指定手数；超过棋谱总手数时在最后一手停止。保存后在棋谱页点击“开始批量分析”。</span></label>
      </fieldset>
      <div class='settings-footer'><span v-if='success' class='micro' role='status'>配置已保存，下次分析生效。</span><button type='submit' class='button primary' :disabled='saving'>{{ saving ? '保存中…' : '保存配置' }}</button></div>
    </form>
    <p v-if='error' class='notice error' role='alert'>{{ error }}</p>
    <button v-if='!settings && !loading' class='button secondary' @click='load'>重新读取</button>
  </section>
</template>
