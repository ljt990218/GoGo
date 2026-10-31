<script setup lang='ts'>
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { downloadGameRecord, queryGameRecords } from '../services/api'
import type { OnlineRecordsPage, RecordPlatform } from '../services/api'

const props = defineProps<{
  importDisabled: boolean
  loadGame: (file: File) => Promise<void>
}>()

const platform = ref<RecordPlatform>('fox')
const account = ref('')
const platformStorageKey = 'gogo-records-platform'
const accountStorageKey = 'gogo-records-account'

try {
  const savedPlatform = localStorage.getItem(platformStorageKey)
  const savedAccount = localStorage.getItem(accountStorageKey)
  if (savedPlatform === 'fox') platform.value = savedPlatform
  if (savedAccount !== null && savedAccount.length <= 64) account.value = savedAccount
  if (savedPlatform !== platform.value) localStorage.setItem(platformStorageKey, platform.value)
} catch {
  // 本地存储不可用时保留默认表单值
}

const records = shallowRef<OnlineRecordsPage | null>(null)
const loading = ref(false)
const error = ref('')
const downloadingId = ref('')
const openingId = ref('')
const recordError = ref('')
const actionsBusy = computed(() => loading.value || !!downloadingId.value || !!openingId.value || props.importDisabled)
const totalPages = computed(() => records.value ? Math.max(1, Math.ceil(records.value.total / records.value.pageSize)) : 1)
const platformNames = { fox: '野狐围棋' }
const resultNames = { win: '胜', loss: '负', unknown: '未标注' }
let version = 0

watch([platform, account], () => {
  version++
  records.value = null
  error.value = ''
  recordError.value = ''
  downloadingId.value = ''
  openingId.value = ''
  try {
    localStorage.setItem(platformStorageKey, platform.value)
    localStorage.setItem(accountStorageKey, account.value)
  } catch {
    // 缓存失败不影响表单输入和查询
  }
}, { flush: 'sync' })

onUnmounted(() => { version++ })

async function query(page = 1) {
  if (actionsBusy.value) return
  const keyword = account.value.trim()
  if (!keyword) {
    error.value = '请输入围棋昵称或用户 ID'
    return
  }
  const requestVersion = ++version
  loading.value = true
  error.value = ''
  recordError.value = ''
  downloadingId.value = ''
  try {
    const response = await queryGameRecords(platform.value, keyword, page)
    if (requestVersion === version) records.value = response
  } catch (cause) {
    if (requestVersion === version) error.value = cause instanceof Error ? cause.message : '查询失败，请稍后重试'
  } finally {
    if (requestVersion === version) loading.value = false
  }
}

async function download(chessId: string) {
  if (!records.value || actionsBusy.value) return
  const requestVersion = version
  downloadingId.value = chessId
  recordError.value = ''
  try {
    const response = await downloadGameRecord(records.value.platform, chessId)
    if (requestVersion !== version) return
    const blob = new Blob([response.sgfText], { type: 'application/x-go-sgf;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${chessId}.sgf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    if (requestVersion === version) recordError.value = cause instanceof Error ? cause.message : '下载失败，请稍后重试'
  } finally {
    if (requestVersion === version) downloadingId.value = ''
  }
}

async function openRecord(chessId: string) {
  if (!records.value || actionsBusy.value) return
  const requestVersion = version
  openingId.value = chessId
  recordError.value = ''
  try {
    const response = await downloadGameRecord(records.value.platform, chessId)
    if (requestVersion !== version) return
    const file = new File([response.sgfText], `${chessId}.sgf`, { type: 'application/x-go-sgf;charset=utf-8' })
    await props.loadGame(file)
  } catch (cause) {
    if (requestVersion === version) recordError.value = cause instanceof Error ? cause.message : '打开棋谱失败，请稍后重试'
  } finally {
    if (requestVersion === version) openingId.value = ''
  }
}
</script>

<template>
  <section class='online-records' aria-labelledby='online-records-title' :aria-busy='loading || !!openingId'>
    <div class='records-heading'>
      <div>
        <h2 id='online-records-title'>近期对局</h2>
        <p class='micro'>按平台和账号查询公开棋谱，每页 10 条。</p>
      </div>
      <span class='section-label'>云端棋谱</span>
    </div>
    <form class='records-form' @submit.prevent='query(1)'>
      <fieldset :disabled='actionsBusy'>
        <label>围棋平台
          <span class='platform-select'>
            <select v-model='platform' name='record-platform'>
              <option value='fox'>野狐围棋</option>
            </select>
            <svg viewBox='0 0 12 12' fill='none' aria-hidden='true'><path d='m2 4 4 4 4-4' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round' /></svg>
          </span>
        </label>
        <label>账号
          <input v-model='account' name='record-account' type='text' maxlength='64' required autocomplete='off' spellcheck='false' placeholder='输入围棋昵称或用户 ID' />
        </label>
        <button type='submit' class='button primary' :disabled='!account.trim()'>{{ loading ? '查询中…' : '查询对局' }}</button>
      </fieldset>
    </form>
    <p v-if='loading' class='micro records-status' role='status'>正在查询对局记录…</p>
    <p v-if='error' class='notice error records-status' role='alert'>{{ error }}</p>
    <template v-if='records'>
      <div class='records-summary' role='status'>
        <p><strong>{{ records.accountName ?? records.accountId }}</strong><span> · {{ platformNames[records.platform] }} · ID {{ records.accountId }}</span></p>
        <span>已获取 {{ records.total }} 条公开记录</span>
      </div>
      <p v-if='!records.total' class='muted records-empty'>暂未查询到该账号的公开对局记录，请确认平台和账号。</p>
      <template v-else>
        <div class='records-table-wrap' role='region' aria-label='近期对局列表，可横向滚动' tabindex='0'>
          <table class='records-table'>
            <caption class='visually-hidden'>{{ records.accountName ?? records.accountId }}的近期对局，第 {{ records.page }} 页，胜负以查询账号为准</caption>
            <thead><tr><th scope='col'>对局时间</th><th scope='col'>黑方</th><th scope='col'>白方</th><th scope='col'>胜负</th><th scope='col'>棋局</th><th scope='col'>棋谱</th></tr></thead>
            <tbody>
              <tr v-for='item in records.items' :key='item.chessId'>
                <td class='records-time'>{{ item.playedAt }}</td>
                <td><span class='record-player'><span class='record-stone black' aria-hidden='true'></span>{{ item.blackName }}</span></td>
                <td><span class='record-player'><span class='record-stone white' aria-hidden='true'></span>{{ item.whiteName }}</span></td>
                <td><span class='record-result' :class='item.result'>{{ resultNames[item.result] }}</span></td>
                <td class='records-meta'>{{ item.boardSize }} 路 · {{ item.moveCount }} 手</td>
                <td class='record-actions'>
                  <button type='button' class='text-button' :disabled='actionsBusy' :aria-label='`打开 ${item.blackName} 对 ${item.whiteName} 的复盘`' @click='openRecord(item.chessId)'>{{ openingId === item.chessId ? '打开中…' : '打开复盘' }}</button>
                  <button type='button' class='text-button' :disabled='actionsBusy' :aria-label='`下载 ${item.blackName} 对 ${item.whiteName} 的 SGF 棋谱`' @click='download(item.chessId)'>{{ downloadingId === item.chessId ? '下载中…' : '下载 SGF' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav class='records-pagination' aria-label='对局记录分页'>
          <span class='micro'>每页 10 条 · 第 {{ records.page }} / {{ totalPages }} 页</span>
          <div>
            <button type='button' class='button secondary' :disabled='actionsBusy || records.page <= 1' @click='query(records.page - 1)'>上一页</button>
            <button type='button' class='button secondary' :disabled='actionsBusy || records.page >= totalPages' @click='query(records.page + 1)'>下一页</button>
          </div>
        </nav>
        <p class='micro'>胜负以查询账号为准。打开复盘后棋谱保存在本地，格式不兼容时会提示原因；下载 SGF 保留平台原文。</p>
      </template>
      <p v-if='recordError' class='notice error records-status' role='alert'>{{ recordError }}</p>
    </template>
  </section>
</template>

<style scoped>
.online-records { padding: 24px 0; border-bottom: 1px solid var(--line); }
.records-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.records-heading h2 { margin-bottom: 5px; font-size: 18px; }
.records-form { margin-top: 18px; }
.records-form fieldset { display: grid; grid-template-columns: 160px minmax(0, 320px) auto; justify-content: start; align-items: end; gap: 14px; min-width: 0; margin: 0; padding: 0; border: 0; }
.records-form label { display: flex; flex-direction: column; gap: 7px; min-width: 0; font-size: 12px; color: var(--muted); }
.records-form input, .records-form select { width: 100%; min-height: 41px; padding: 9px 12px; border: 1px solid #c5cebe; border-radius: 6px; background: var(--paper); color: #27382d; font-size: 13px; }
.platform-select { position: relative; display: block; }
.platform-select select { appearance: none; padding-right: 38px; }
.platform-select svg { position: absolute; top: 50%; right: 14px; width: 12px; height: 12px; transform: translateY(-50%); color: #27382d; pointer-events: none; }
.records-status { margin-top: 14px; }
.records-summary { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 6px 16px; margin-top: 20px; font-size: 12px; color: var(--muted); }
.records-summary strong { font-size: 13px; font-weight: 600; color: var(--green); }
.records-empty { padding: 22px 0 4px; line-height: 1.8; }
.records-table-wrap { margin-top: 12px; overflow-x: auto; border: 1px solid var(--line); border-radius: 7px; }
.records-table-wrap:focus-visible { outline: 3px solid #57764e; outline-offset: 3px; }
.records-table { width: 100%; min-width: 690px; border-collapse: collapse; background: var(--paper); font-size: 13px; text-align: left; }
.records-table th { padding: 11px 14px; background: #edf0e7; color: var(--muted); font-size: 11px; font-weight: 500; white-space: nowrap; }
.records-table td { padding: 12px 14px; border-top: 1px solid var(--line); }
.records-table tbody tr:hover { background: #f0f3e9; }
.records-time { font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--muted); }
.record-player { display: flex; align-items: center; gap: 7px; min-width: 85px; overflow-wrap: anywhere; }
.record-stone { width: 10px; height: 10px; flex-shrink: 0; border-radius: 50%; }
.record-stone.black { background: #27382d; border: 1px solid #27382d; }
.record-stone.white { background: #fff; border: 1px solid #a8b2a1; }
.record-result { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 12px; white-space: nowrap; color: var(--muted); }
.record-result.win { background: #e5eddf; color: #315d49; }
.record-result.loss { background: #f2e8df; color: #8b5b44; }
.records-meta, .records-table .text-button { white-space: nowrap; font-size: 12px; }
.records-meta { color: var(--muted); }
.records-table .text-button { color: var(--green); }
.record-actions { white-space: nowrap }
.record-actions .text-button + .text-button { margin-left: 12px }
.records-pagination { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 14px 0 10px; }
.records-pagination > div { display: flex; gap: 8px; }
.records-pagination .button { min-height: 34px; padding: 6px 12px; font-size: 12px; }
@media (max-width: 600px) {
  .records-form fieldset { grid-template-columns: 1fr; gap: 12px; }
  .records-heading > .section-label { display: none; }
  .records-summary p span { display: block; }
}
</style>
