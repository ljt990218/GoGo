<script setup lang='ts'>
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import Board from '@sabaki/go-board'
import type { SignMap } from '@sabaki/go-board'
import GoBoard from './components/GoBoard.vue'
import AnalysisPanel from './components/AnalysisPanel.vue'
import AppDialog from './components/AppDialog.vue'
import AnalysisSettings from './components/AnalysisSettings.vue'
import { useReview } from './composables/useReview'
import { positionAt, trialSgf, validKomi } from './domain/sgf'
import { analyzePosition, explainPosition } from './services/api'
import { validateAnalysis } from './domain/results'
import type { AnalysisRecord, Candidate, GameRecord, Point, PositionRequest, Rules } from './domain/types'

const {
  games, counts, currentGame, parsed, moveIndex, position, currentRecord, currentBusy, currentError,
  batch, batchMessage, batchStopMove, batchSettingsLoading, batchSettingsError, loadBatchSettings, runBatch, stopBatch, busy, initializing, loadingGame, importing, importError, draft, storageError, deleteTarget,
  deletingId, saving, unsaved, dirtyGames, source, key, initialize, openGame, navigate,
  importFile, confirmImport, runAnalysis, retrySave, confirmDelete
} = useReview()
// 试下仅保存在当前页面内存，不修改真实棋谱或分析记录。
const trialPositions = shallowRef<NonNullable<typeof position.value>[]>([])
const trialError = ref('')
const trying = computed(() => trialPositions.value.length > 0)
const boardPosition = computed(() => trialPositions.value.at(-1) ?? position.value)
const trialRecord = shallowRef<AnalysisRecord | null>(null)
const trialStage = ref<'analyzing' | 'explaining' | null>(null)
const trialAnalysisError = ref('')
let trialVersion = 0
const displayedRecord = computed(() => trying.value ? trialRecord.value : currentRecord.value)
const candidateRequest = shallowRef<{ analysis: AnalysisRecord['analysis'], candidateIndex: number } | null>(null)
const pendingCandidateIndex = computed(() => {
  const request = candidateRequest.value
  return request && request.analysis === displayedRecord.value?.analysis ? request.candidateIndex : null
})
const displayedMoveIndex = computed(() => moveIndex.value + Math.max(0, trialPositions.value.length - 1))
watch(trialPositions, () => {
  trialVersion++
  trialRecord.value = null
  trialAnalysisError.value = ''
  analysisDetailsOpen.value = false
  selectedCandidateIndex.value = 0
  clearPreview()
}, { flush: 'sync' })
onUnmounted(() => { trialVersion++ })
async function analyzeTrial(explanationOnly = false, candidateIndex = 0) {
  const game = currentGame.value
  const gameParsed = parsed.value
  const snapshot = boardPosition.value
  if (!trying.value || !game || !gameParsed || !snapshot || trialStage.value || busy.value || batch.value || loadingGame.value || saving.value) return
  if (explanationOnly && !trialRecord.value) return
  if (explanationOnly && !trialRecord.value!.analysis.candidates[candidateIndex]) return
  const version = trialVersion
  const moves = trialPositions.value.slice(1).map(item => item.lastMove!)
  const request: PositionRequest = {
    sgfText: trialSgf(gameParsed, moveIndex.value, moves, game.rules, game.komi),
    moveIndex: displayedMoveIndex.value, rules: game.rules, komi: game.komi
  }
  trialStage.value = explanationOnly ? 'explaining' : 'analyzing'
  trialAnalysisError.value = ''
  try {
    let record = trialRecord.value
    if (!explanationOnly) {
      const analysis = await analyzePosition(request)
      if (version !== trialVersion) return
      validateAnalysis(analysis, game.boardSize, request.moveIndex, snapshot.toPlay)
      record = { gameId: game.gameId, moveIndex: request.moveIndex, analysis, candidateIndex: 0, explanation: null, aiModel: null, explainedAt: null }
      trialRecord.value = record
      selectedCandidateIndex.value = 0
      clearPreview()
    }
    if (!record || version !== trialVersion) return
    trialStage.value = 'explaining'
    const explanation = await explainPosition(request, record.analysis, candidateIndex)
    if (version !== trialVersion) return
    if (explanation.candidateIndex !== candidateIndex ||
        typeof explanation.explanation !== 'string' || !explanation.explanation.trim() ||
        typeof explanation.aiModel !== 'string' || !explanation.aiModel.trim() ||
        typeof explanation.explainedAt !== 'string' || !Number.isFinite(Date.parse(explanation.explainedAt))) {
      throw new Error('AI 返回了空解释或无效结果，请重新生成解释')
    }
    trialRecord.value = { ...record, ...explanation }
  } catch (error) {
    if (version === trialVersion) {
      trialAnalysisError.value = `${trialStage.value === 'explaining' ? '解释生成失败，已保留引擎结果。' : ''}${error instanceof Error ? error.message : '分析失败，请重试'}`
    }
  } finally {
    trialStage.value = null
  }
}
async function analyzeDisplayed(explanationOnly = false, candidateIndex = 0) {
  if (candidateRequest.value || trialStage.value || busy.value || batch.value || loadingGame.value || saving.value || deletingId.value === currentGame.value?.gameId) return
  const record = displayedRecord.value
  if (explanationOnly) {
    if (!record?.analysis.candidates[candidateIndex]) return
    candidateRequest.value = { analysis: record.analysis, candidateIndex }
  }
  try {
    if (trying.value) await analyzeTrial(explanationOnly, candidateIndex)
    else await runAnalysis(explanationOnly, candidateIndex)
  } finally {
    candidateRequest.value = null
  }
}
function returnToGame() {
  trialPositions.value = []
  trialError.value = ''
  clearPreview()
}
function playTrial(point: Point | null) {
  const current = boardPosition.value
  if (!current || loadingGame.value) return
  trialError.value = ''
  let board = new Board(current.board.map(row => [...row]) as SignMap)
  if (point) {
    const vertex: [number, number] = [point.x, point.y]
    const sign = current.toPlay === 'black' ? 1 : -1
    const legality = board.analyzeMove(sign, vertex)
    if (legality.overwrite || legality.suicide) {
      trialError.value = legality.overwrite ? '这里已有棋子，请选择空位' : '此处落子无气，请选择其他位置'
      return
    }
    board = board.makeMove(sign, vertex, { preventOverwrite: true, preventSuicide: true })
    const previous = trialPositions.value.length > 1
      ? trialPositions.value[trialPositions.value.length - 2].board
      : parsed.value && moveIndex.value > 0 ? positionAt(parsed.value, moveIndex.value - 1).board : null
    if (previous && JSON.stringify(board.signMap) === JSON.stringify(previous)) {
      trialError.value = '不能立即回提劫，请选择其他位置'
      return
    }
  }
  clearPreview()
  const history = trying.value ? trialPositions.value : [current]
  trialPositions.value = [...history, {
    board: board.signMap,
    toPlay: current.toPlay === 'black' ? 'white' : 'black',
    lastMove: { player: current.toPlay, point }
  }]
}
function undoTrial() {
  if (trialPositions.value.length <= 1) return
  trialPositions.value = trialPositions.value.slice(0, -1)
  trialError.value = ''
}
watch([key, loadingGame], returnToGame)
const settingsOpen = ref(false)
const analysisDetailsOpen = ref(false)
const batchOpen = ref(false)
const statusOpen = ref(false)
const statusSummary = computed(() => {
  if (storageError.value) return '存储异常'
  if (unsaved.value.size) return `${unsaved.value.size} 项未保存`
  if (importError.value) return '导入失败'
  if (batchMessage.value) return '批量分析结果'
  if (busy.value && !currentBusy.value && !batch.value) return `后台处理第 ${busy.value.moveIndex} 手`
  return ''
})
function openSettings() {
  batchOpen.value = false
  settingsOpen.value = true
}
function closeAnalysisDetails() {
  analysisDetailsOpen.value = false
  highlightedPoint.value = null
}
const settingsVersion = ref(0)
const selectedCandidateIndex = ref(0)
const batchEnd = computed(() => currentGame.value && batchStopMove.value !== null ? Math.min(batchStopMove.value, currentGame.value.totalMoves) : null)
const highlightedPoint = ref<Point | null>(null)
const previewVariation = shallowRef<Candidate | null>(null)
function clearPreview() {
  highlightedPoint.value = null
  previewVariation.value = null
}
function previewPoint(point: Point | null) {
  highlightedPoint.value = point
}
function selectCandidate(index: number) {
  if (!displayedRecord.value?.analysis.candidates[index]) return
  clearPreview()
  selectedCandidateIndex.value = index
}
function analyzeCandidate(index: number) {
  if (candidateRequest.value || trialStage.value || busy.value || batch.value || loadingGame.value || saving.value || deletingId.value === currentGame.value?.gameId) return
  if (!displayedRecord.value?.analysis.candidates[index]) return
  selectCandidate(index)
  void analyzeDisplayed(true, index)
}
function previewLine(candidate: Candidate) {
  if (previewVariation.value === candidate) {
    clearPreview()
    return
  }
  const index = displayedRecord.value?.analysis.candidates.indexOf(candidate) ?? -1
  if (index < 0 || !candidate.principalVariation.length) return
  clearPreview()
  selectedCandidateIndex.value = index
  previewVariation.value = candidate
}
function settingsSaved(source: 'home' | 'dialog') {
  if (source === 'dialog') settingsVersion.value++
  void loadBatchSettings()
}
function exitPreview(event: KeyboardEvent) {
  if (event.key === 'Escape' && !settingsOpen.value && !analysisDetailsOpen.value && !batchOpen.value && !statusOpen.value && !draft.value && !deleteTarget.value) clearPreview()
}
const page = ref(window.location.hash === '#analysis' ? 'analysis' : 'home')
watch([key, () => currentRecord.value?.analysis, page], () => {
  clearPreview()
  selectedCandidateIndex.value = 0
}, { flush: 'sync' })
watch([key, page], () => {
  returnToGame()
  analysisDetailsOpen.value = false
  batchOpen.value = false
  statusOpen.value = false
})
const syncPage = () => { page.value = window.location.hash === '#analysis' ? 'analysis' : 'home' }
function goHome() {
  window.location.hash = 'home'
  page.value = 'home'
}
function showAnalysis() {
  window.location.hash = 'analysis'
  page.value = 'analysis'
}
async function enterGame(game: GameRecord) {
  await openGame(game)
  if (currentGame.value?.gameId === game.gameId) showAnalysis()
}
onMounted(() => window.addEventListener('hashchange', syncPage))
onUnmounted(() => window.removeEventListener('hashchange', syncPage))
onMounted(() => window.addEventListener('keydown', exitPreview))
onUnmounted(() => window.removeEventListener('keydown', exitPreview))
const fileInput = ref<HTMLInputElement | null>(null)
const selectedRules = ref<Rules | ''>('')
const selectedKomi = ref<number | ''>('')
watch(draft, value => {
  selectedRules.value = value?.parsed.rules ?? ''
  selectedKomi.value = value?.parsed.komi ?? ''
})

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) {
    await importFile(file)
    if (!draft.value && !importError.value && currentGame.value) showAnalysis()
  }
}

async function submitImport() {
  if (selectedRules.value && typeof selectedKomi.value === 'number' && validKomi(selectedKomi.value)) {
    await confirmImport(selectedRules.value, selectedKomi.value)
    if (!draft.value && !importError.value && currentGame.value) showAnalysis()
  }
}
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <div :class='["app-shell", { "review-shell": page === "analysis", "home-shell": page === "home" }]' :inert='draft || deleteTarget || settingsOpen || analysisDetailsOpen || batchOpen || statusOpen ? true : undefined'>
    <header class='app-header'>
      <a class='brand' href='#home' @click.prevent='goHome' aria-label='GoGo 围棋局面分析助手'>
        <span class='brand-mark' aria-hidden='true'><i></i><i></i></span>
        <span>GoGo<span class='brand-caption'>围棋局面分析</span></span>
      </a>
      <div class='header-actions'>
        <button v-if='page === "analysis" && trying' type='button' class='button primary' @click='returnToGame'>回到真实棋谱</button>
        <button v-if='page === "analysis" && statusSummary' type='button' class='review-status-button' @click='statusOpen = true'><span class='status-dot'></span>{{ statusSummary }}</button>
        <button v-if='page === "analysis" && currentGame' type='button' class='button secondary batch-toolbar-button' :disabled='loadingGame || !!trialStage' @click='batchOpen = true'>{{ batch ? batch.end ? `批量分析 ${batch.index} / ${batch.end}` : '批量分析中…' : '批量分析' }}</button>
        <button class='icon-button settings-button' :disabled='!!busy || !!batch || !!trialStage' aria-label='分析设置' title='分析设置' @click='openSettings'>
          <svg viewBox='0 0 24 24' width='22' height='22' fill='none' aria-hidden='true'><path d='m10 3-.6 2.3-2 .9L5.3 5.5 3.5 8.6l1.7 1.6v2.4l-1.7 1.6 1.8 3.1 2.1-.7 2 .9.6 2.3h3.6l.6-2.3 2-.9 2.1.7 1.8-3.1-1.7-1.6v-2.4l1.7-1.6-1.8-3.1-2.1.7-2-.9L13.6 3Z' stroke='currentColor' stroke-width='1.5' stroke-linejoin='round' /><circle cx='11.8' cy='11.4' r='3' stroke='currentColor' stroke-width='1.5' /></svg>
        </button>
        <button v-if='page === "analysis"' class='button secondary' @click='goHome'>← 我的棋谱</button>
        <span v-else class='local-caption'><span class='status-dot'></span>棋谱保存在本机</span>
        <button v-if='page === "home"' class='button primary' :disabled='importing || initializing || !!deletingId' @click='fileInput?.click()'>
          <svg viewBox='0 0 20 20' width='17' height='17' fill='none' aria-hidden='true'><path d='M10 13V3m-4 4 4-4 4 4M4 12v5h12v-5' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' /></svg>
          {{ importing ? '导入中…' : '导入棋谱' }}
        </button>
        <input ref='fileInput' type='file' accept='.sgf' class='visually-hidden' tabindex='-1' @change='selectFile' />
      </div>
    </header>

    <div v-if='page !== "analysis"' class='global-notices'>
      <div v-if='importError && !draft' class='global-notice notice error' role='alert'>{{ importError }}<button class='text-button' @click='importError = ""'>关闭</button></div>
      <div v-if='storageError' class='global-notice notice warning' role='alert'>
        <span>{{ storageError }}</span>
        <button class='text-button' :disabled='saving || !!busy' @click='dirtyGames.size || unsaved.size ? retrySave() : initialize()'>重试</button>
      </div>
      <div v-if='batch || batchMessage' class='global-notice notice warning' role='status'>
        <span v-if='batch'>「{{ batch.fileName }}」{{ batch.end ? `正在分析第 ${batch.index} / ${batch.end} 手` : '正在读取配置…' }}{{ batch.stopping ? '，当前手完成后停止' : '' }}</span>
        <span v-else>{{ batchMessage }}</span>
        <button v-if='batch' class='text-button' :disabled='batch.stopping' @click='stopBatch'>停止</button>
        <button v-else class='text-button' @click='batchMessage = ""'>关闭</button>
      </div>
      <div v-if='unsaved.size' class='global-notice notice warning' role='status'>
        <span>有 {{ unsaved.size }} 个局面结果尚未保存，请在关闭页面前重试保存。</span>
        <button class='text-button' :disabled='saving || !!busy' @click='retrySave'>{{ saving ? '保存中…' : '重试保存' }}</button>
      </div>
    </div>

    <main :class='page === "home" ? "home-page" : "workspace"'>
      <section v-if='page === "home"' class='home-intro'>
        <div class='home-intro-copy'>
          <span class='section-label'>GoGo · 围棋复盘</span>
          <h1>每一盘，都值得再看一遍。</h1>
          <p>从一盘棋开始，找到下一手的方向。</p>
        </div>
        <div class='home-intro-actions'>
          <button class='button primary' :disabled='importing || initializing || !!deletingId' @click='fileInput?.click()'>＋ 导入 SGF 棋谱</button>
          <span class='micro'>支持 9 / 13 / 19 路 · 最大 2 MB</span>
        </div>
      </section>
      <section v-if='page === "home"' class='home-settings'>
        <details>
          <summary>项目分析配置<span class='home-settings-caption'>引擎、AI 与分析参数</span></summary>
          <div :inert='!!batch || !!busy || !!trialStage'><AnalysisSettings :key='settingsVersion' @saved='settingsSaved("home")' /></div>
        </details>
      </section>
      <aside v-if='page === "home"' class='library' aria-label='本地棋谱列表'>
        <div class='library-heading'><h2>历史棋谱</h2><span>{{ games.length.toString().padStart(2, '0') }}</span></div>
        <p class='micro library-caption'>继续上次复盘，或导入新的棋谱。</p>
        <p v-if='initializing' class='muted library-placeholder' role='status'>正在读取本地棋谱…</p>
        <p v-else-if='!games.length' class='muted library-placeholder'>还没有棋谱。<br />导入第一盘，开始复盘。</p>
        <ul v-else class='game-list'>
          <li v-for='game in games' :key='game.gameId' :class='["game-item", { selected: game.gameId === currentGame?.gameId }]'>
            <button class='game-open' :disabled='deletingId === game.gameId' :aria-current='game.gameId === currentGame?.gameId ? "true" : undefined' @click='enterGame(game)'>
              <span class='game-file-name'>{{ game.fileName }}</span>
              <span class='game-meta'>{{ game.boardSize }} 路 · {{ game.totalMoves }} 手</span>
              <span class='game-saved'>{{ counts[game.gameId] ?? 0 }} 个已保存分析</span>
              <span class='game-date'>最近打开 {{ time(game.lastOpenedAt) }}</span>
            </button>
            <button class='delete-game' :disabled='busy?.gameId === game.gameId || batch?.gameId === game.gameId || !!trialStage || !!deletingId || saving || loadingGame || importing' :aria-label='`删除 ${game.fileName}`' title='删除棋谱' @click='deleteTarget = game'>
              <svg viewBox='0 0 20 20' width='16' height='16' fill='none' aria-hidden='true'><path d='M4 5h12M8 3h4M6 5l1 12h6l1-12M9 8v6M11 8v6' stroke='currentColor' stroke-width='1.3' stroke-linecap='round' /></svg>
            </button>
          </li>
        </ul>
        <div class='library-footer'><span class='section-label'>本地棋谱库</span><p>棋谱与分析保存在当前浏览器。清除网站数据会同时删除这些记录。</p></div>
      </aside>

      <template v-if='page === "analysis" && currentGame && parsed && position'>
        <section class='board-panel' aria-label='棋谱浏览'>
          <div class='board-stage'>
            <GoBoard :size='currentGame.boardSize' :board='boardPosition!.board' :last-point='boardPosition!.lastMove?.point ?? null' :candidates='displayedRecord?.analysis.candidates ?? []' :to-play='boardPosition!.toPlay' @play='playTrial' :selected-index='selectedCandidateIndex' :highlighted-point='highlightedPoint' :variation='previewVariation' @select-candidate='selectCandidate' @exit-preview='clearPreview' />
          </div>
          <section :inert='trying ? true : undefined' class='position-controls' aria-label='棋盘下方的手数导航'>
            <div class='playback-actions'>
              <button class='button secondary boundary-button' :disabled='moveIndex === 0 || loadingGame' aria-label='初始局面' title='初始局面（Home）' @click='navigate(0)'>
                <svg viewBox='0 0 24 24' width='20' height='20' fill='none' aria-hidden='true'><path d='M6 5v14m12-13-7 6 7 6' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' /></svg>
              </button>
              <button class='button secondary' :disabled='moveIndex === 0 || loadingGame' aria-label='上一手' title='上一手（←）' @click='navigate(moveIndex - 1)'>
                <svg viewBox='0 0 24 24' width='20' height='20' fill='none' aria-hidden='true'><path d='m15 6-6 6 6 6' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' /></svg>
              </button>
            </div>
            <span class='move-count'>{{ moveIndex }} / {{ currentGame.totalMoves }} 手</span>
            <input class='move-slider' type='range' min='0' :max='currentGame.totalMoves' :value='moveIndex' :disabled='loadingGame || !currentGame.totalMoves' aria-label='浏览手数' @input='navigate(Number(($event.target as HTMLInputElement).value))' />
            <div class='playback-actions'>
              <button class='button secondary' :disabled='moveIndex === currentGame.totalMoves || loadingGame' aria-label='下一手' title='下一手（→）' @click='navigate(moveIndex + 1)'>
                <svg viewBox='0 0 24 24' width='20' height='20' fill='none' aria-hidden='true'><path d='m9 6 6 6-6 6' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' /></svg>
              </button>
              <button class='button secondary boundary-button' :disabled='moveIndex === currentGame.totalMoves || loadingGame' aria-label='最后一手' title='最后一手（End）' @click='navigate(currentGame.totalMoves)'>
                <svg viewBox='0 0 24 24' width='20' height='20' fill='none' aria-hidden='true'><path d='m6 6 7 6-7 6m12-13v14' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' /></svg>
              </button>
            </div>
          </section>
        </section>
        <AnalysisPanel :record='displayedRecord' :temporary='trying' :size='currentGame.boardSize' :move-index='displayedMoveIndex' :to-play='boardPosition!.toPlay' :selected-index='selectedCandidateIndex' :pending-candidate-index='pendingCandidateIndex' :variation='previewVariation' :details-open='analysisDetailsOpen' :stage='trying ? trialStage : currentBusy' :disabled='!!busy || !!batch || !!trialStage || loadingGame || saving || deletingId === currentGame.gameId' :unsaved='!trying && unsaved.has(key)' :saving='saving' :source='trying ? "fresh" : source[key]' :error='trying ? trialAnalysisError : currentError' @analyze='analyzeDisplayed()' @explain='analyzeDisplayed(true, $event)' @analyze-candidate='analyzeCandidate' @save='retrySave' @select-candidate='selectCandidate' @preview-point='previewPoint' @preview-variation='previewLine' @open-details='analysisDetailsOpen = true' @close-details='closeAnalysisDetails'>
          <template v-if='trying' #controls>
            <div class='section-row'><h3>自由试下</h3><span class='micro' role='status'>试下 {{ trialPositions.length - 1 }} 手</span></div>
            <div class='trial-actions'>
              <button class='button secondary' :disabled='trialPositions.length <= 1' @click='undoTrial'>悔棋</button>
              <button class='button secondary' @click='playTrial(null)'>停一手</button>
              <button type='button' class='button primary' @click='returnToGame'>回到棋盘</button>
            </div>
            <p v-if='trialError' class='notice warning' role='alert'>{{ trialError }}</p>
            <p class='micro'>从棋谱第 {{ moveIndex }} 手开始试下，分析结果仅临时保留。</p>
          </template>
        </AnalysisPanel>
      </template>
      <section v-else-if='page === "analysis"' class='welcome'>
        <h1>选择一盘棋，开始复盘</h1>
        <p>从历史棋谱继续，或导入一盘新棋。</p>
        <button class='button primary' @click='goHome'>返回我的棋谱</button>
      </section>
    </main>
  </div>

  <AppDialog v-if='batchOpen && currentGame' title='批量分析' @close='batchOpen = false'>
    <p class='micro'>{{ batch ? batch.fileName : currentGame.fileName }}</p>
    <section class='batch-actions' aria-label='批量分析'>
      <div class='section-row'><h3>批量分析</h3><button class='text-button' :disabled='!!busy || !!batch || !!trialStage' @click='openSettings'>设置范围</button></div>
      <template v-if='batch'>
        <p v-if='batch.end' role='status'>已完成 {{ Math.max(0, batch.index - 1) }} / {{ batch.end }} 手 · {{ batch.stopping ? '当前手完成后停止' : `正在处理第 ${batch.index} 手` }}</p>
        <p v-else class='micro' role='status'>正在读取分析范围…</p>
        <progress v-if='batch.end' :value='Math.max(0, batch.index - 1)' :max='batch.end' aria-label='已完成的批量分析手数'></progress>
        <button class='button secondary' :disabled='batch.stopping' @click='stopBatch'>{{ batch.stopping ? '正在停止…' : '停止批量分析' }}</button>
      </template>
    </section>

    <div class='dialog-actions'><button class='button secondary' @click='batchOpen = false'>关闭</button></div>
  </AppDialog>
  <AppDialog v-if='statusOpen' title='运行状态' @close='statusOpen = false'>
    <div v-if='storageError' class='notice warning' role='alert'>{{ storageError }} <button class='text-button' :disabled='saving || !!busy' @click='dirtyGames.size || unsaved.size ? retrySave() : initialize()'>重试</button></div>
    <div v-if='importError' class='notice error' role='alert'>{{ importError }} <button class='text-button' @click='importError = ""'>清除提示</button></div>
    <div v-if='unsaved.size' class='notice warning' role='status'>有 {{ unsaved.size }} 个局面结果尚未保存。<button class='text-button' :disabled='saving || !!busy || !!batch' @click='retrySave'>{{ saving ? '保存中…' : '重试保存' }}</button></div>
    <div v-if='batchMessage' class='notice warning' role='status'>{{ batchMessage }} <button class='text-button' @click='batchMessage = ""'>清除提示</button></div>
    <p v-if='busy && !currentBusy && !batch' class='micro' role='status'>正在处理「{{ games.find(game => game.gameId === busy?.gameId)?.fileName }}」第 {{ busy.moveIndex }} 手，结果将保存至对应局面。</p>
    <p v-if='!statusSummary' class='micro'>当前没有需要处理的运行提示。</p>
    <div class='dialog-actions'><button class='button secondary' @click='statusOpen = false'>关闭</button></div>
  </AppDialog>
  <AppDialog v-if='settingsOpen' title='分析设置' @close='settingsOpen = false'>
    <AnalysisSettings @saved='settingsSaved("dialog")' />
    <div class='dialog-actions'><button class='button secondary' @click='settingsOpen = false'>关闭</button></div>
  </AppDialog>
  <AppDialog v-if='draft' title='确认棋谱信息' :locked='importing' @close='draft = null'>
    <p class='muted'>棋谱缺少规则或贴目，或规则无法识别。请明确确认后导入。</p>
    <p class='micro'>文件：{{ draft.fileName }}<br />原始规则：{{ draft.parsed.originalRules ?? '未填写' }}</p>
    <form @submit.prevent='submitImport'>
      <label class='form-field'>规则<select v-model='selectedRules' required :disabled='draft.parsed.rules !== null'><option disabled value=''>请选择规则</option><option value='chinese'>中国规则</option><option value='japanese'>日本规则</option></select></label>
      <label class='form-field'>贴目<input v-model.number='selectedKomi' type='number' min='-50' max='50' step='.5' required :disabled='draft.parsed.komi !== null' placeholder='请输入贴目' /></label>
      <p class='micro'>不同规则或贴目的相同棋谱，会保存为独立记录。</p>
      <p v-if='importError' class='notice error' role='alert'>{{ importError }}</p>
      <div class='dialog-actions'><button type='button' class='button secondary' :disabled='importing' @click='draft = null'>取消</button><button class='button primary' type='submit' :disabled='importing'>{{ importing ? '保存中…' : '确认并导入' }}</button></div>
    </form>
  </AppDialog>
  <AppDialog v-if='deleteTarget' title='删除这盘棋谱？' :locked='!!deletingId' @close='deleteTarget = null'>
    <p>将删除「{{ deleteTarget.fileName }}」及其全部本地分析与解释，此操作无法撤销。</p>
    <p v-if='storageError' class='notice error' role='alert'>{{ storageError }}</p>
    <div class='dialog-actions'><button class='button secondary' :disabled='!!deletingId' @click='deleteTarget = null'>保留棋谱</button><button class='button danger' :disabled='!!deletingId || busy?.gameId === deleteTarget.gameId' @click='confirmDelete'>{{ deletingId ? '删除中…' : '确认删除' }}</button></div>
  </AppDialog>
</template>
