<script setup lang='ts'>
import { computed } from 'vue'
import AppDialog from './AppDialog.vue'
import { columns, coordinate } from '../domain/coordinates'
import { formatScoreLead, formatWinRate } from '../domain/evaluation'
import type { Move } from '../domain/sgf'
import type { AnalysisResult, MoveReviewRecord, Point } from '../domain/types'

const props = defineProps<{
  review: MoveReviewRecord | null
  playedMove: Move | null
  moveIndex: number
  size: number
  temporary?: boolean
  stage: 'analyzing' | 'explaining' | null
  disabled: boolean
  unsaved: boolean
  saving: boolean
  source: 'local' | 'fresh' | undefined
  error: string
  detailsOpen: boolean
}>()
const emit = defineEmits<{
  refresh: []
  explain: []
  save: []
  openDetails: []
  closeDetails: []
  previewPoint: [point: Point | null]
}>()
const playerLabel = computed(() => props.playedMove?.player === 'black' ? '黑棋' : '白棋')
const title = computed(() => props.playedMove
  ? `第 ${props.moveIndex} 手 · ${playerLabel.value} · ${coordinate(props.playedMove.point, props.size)}`
  : '尚无可点评的着手')
const sign = computed(() => props.playedMove?.player === 'black' ? 1 : -1)
function evaluation(analysis: AnalysisResult) {
  const candidate = analysis.candidates[0]
  return {
    winRate: props.playedMove?.player === 'black' ? candidate.blackWinRate : 1 - candidate.blackWinRate,
    scoreLead: sign.value * candidate.blackScoreLead
  }
}
const before = computed(() => props.review ? evaluation(props.review.beforeAnalysis) : null)
const after = computed(() => props.review ? evaluation(props.review.afterAnalysis) : null)
const changes = computed(() => before.value && after.value ? {
  winRate: (after.value.winRate - before.value.winRate) * 100,
  scoreLead: after.value.scoreLead - before.value.scoreLead
} : null)
const explanationParts = computed(() => {
  const text = props.review?.explanation ?? ''
  const parts: { text: string, point: Point | null }[] = []
  let offset = 0
  for (const match of text.matchAll(/(?<![A-Za-z0-9_])[A-HJ-T](?:[1-9][0-9]*)(?![A-Za-z0-9_])/gi)) {
    const x = columns.indexOf(match[0][0].toUpperCase())
    const row = Number(match[0].slice(1))
    if (x < 0 || x >= props.size || row > props.size) continue
    if (match.index > offset) parts.push({ text: text.slice(offset, match.index), point: null })
    parts.push({ text: match[0], point: { x, y: props.size - row } })
    offset = match.index + match[0].length
  }
  if (offset < text.length) parts.push({ text: text.slice(offset), point: null })
  return parts
})
const time = (value: string) => new Date(value).toLocaleString('zh-CN')
</script>

<template>
  <header class='move-review-heading'>
    <div class='section-row'>
      <span class='section-label'>着手点评<span v-if='review'> · {{ source === 'local' ? '本地记录' : '本次点评' }}</span></span>
      <button v-if='review' type='button' class='text-button' :disabled='disabled' @click='emit("refresh")'>重新点评</button>
    </div>
    <h2>{{ title }}</h2>
  </header>

  <section v-if='before && after && changes' class='move-review-metrics' aria-label='落子方视角的引擎评估对比'>
    <table class='review-comparison'>
      <caption>{{ playerLabel }}视角 · 引擎估计</caption>
      <thead><tr><th scope='col'>评估</th><th scope='col'>落子前</th><th scope='col'>落子后</th></tr></thead>
      <tbody>
        <tr><th scope='row'>胜率</th><td>{{ formatWinRate(before.winRate) }}</td><td>{{ formatWinRate(after.winRate) }}</td></tr>
        <tr><th scope='row'>预计领先</th><td>{{ formatScoreLead(before.scoreLead) }} 目</td><td>{{ formatScoreLead(after.scoreLead) }} 目</td></tr>
      </tbody>
    </table>
    <p class='micro'>胜率变化 {{ formatScoreLead(changes.winRate) }} 个百分点 · 预计领先变化 {{ formatScoreLead(changes.scoreLead) }} 目</p>
    <p class='micro'>变化来自两次独立搜索的首选评估，仅供参考。</p>
  </section>

  <section v-if='review' class='move-alternatives' aria-label='落子前的引擎推荐'>
    <h3>落子前推荐</h3>
    <div class='move-alternative-points'>
      <button v-for='(candidate, index) in review.beforeAnalysis.candidates' :key='index' type='button' class='button secondary' @click='emit("previewPoint", candidate.point)' @mouseenter='emit("previewPoint", candidate.point)' @mouseleave='emit("previewPoint", null)' @focus='emit("previewPoint", candidate.point)' @blur='emit("previewPoint", null)'>{{ index === 0 ? '首选' : '候选' }} {{ coordinate(candidate.point, size) }}</button>
    </div>
  </section>

  <section class='explanation-section' aria-label='AI 着手点评' :aria-busy='!!stage'>
    <div class='section-row'>
      <h3>AI 点评</h3>
      <span v-if='stage' class='analysis-stage' role='status'><span class='spinner' aria-hidden='true'></span>{{ stage === 'analyzing' ? '落子前后分析中' : '点评生成中' }}</span>
      <button v-else-if='review?.explanation' type='button' class='text-button' :disabled='disabled' @click='emit("explain")'>重新生成点评</button>
    </div>
    <p v-if='review?.explanation' class='explanation core-explanation'><template v-for='(part, index) in explanationParts' :key='index'><button v-if='part.point' type='button' class='coordinate-link' :aria-label='`在棋盘定位 ${part.text}`' @click='emit("previewPoint", part.point)' @mouseenter='emit("previewPoint", part.point)' @mouseleave='emit("previewPoint", null)' @focus='emit("previewPoint", part.point)' @blur='emit("previewPoint", null)'>{{ part.text }}</button><template v-else>{{ part.text }}</template></template></p>
    <div v-else class='analysis-empty'>
      <h3>{{ stage === 'analyzing' ? '正在比较落子前后局面' : stage === 'explaining' ? '正在生成着手点评' : review ? '前后评估已就绪' : '了解这一手的作用与问题' }}</h3>
      <p>{{ review ? '结合实际着手与引擎推荐，解释作用、问题和可比较的选择。' : '点击“点评此手”，分析当前这一手。' }}</p>
      <button v-if='review && !stage' type='button' class='button secondary' :disabled='disabled' @click='emit("explain")'>{{ error ? '重试生成点评' : '生成点评' }}</button>
    </div>
  </section>

  <footer class='analysis-footer'>
    <div class='analysis-footer-status'>
      <button v-if='error' type='button' class='text-button analysis-error-link' @click='emit("openDetails")'><span role='alert'>本次点评失败 · 查看详情</span></button>
      <button v-if='unsaved' type='button' class='text-button save-warning' :disabled='disabled || saving' @click='emit("save")'>{{ saving ? '保存中…' : '尚未保存 · 重试' }}</button>
      <span v-else-if='review' class='save-status'><span class='status-dot'></span>{{ temporary ? '试下点评 · 仅临时保留' : '已保存到本地' }}</span>
    </div>
    <button v-if='review' type='button' class='text-button' @click='emit("openDetails")'>点评详情</button>
  </footer>

  <AppDialog v-if='detailsOpen' title='点评详情' placement='right' @close='emit("closeDetails")'>
    <div class='drawer-heading-row'><span class='micro'>{{ title }}</span><button type='button' class='button secondary' @click='emit("closeDetails")'>关闭</button></div>
    <p v-if='error' class='notice error' role='alert'>{{ error }}</p>
    <template v-if='review'>
      <section class='drawer-section'>
        <h3>完整 AI 点评</h3>
        <p class='explanation'>{{ review.explanation ?? '尚未生成点评，可关闭详情后重试。' }}</p>
        <p v-if='review.aiModel && review.explainedAt' class='micro'>{{ review.aiModel }} · {{ time(review.explainedAt) }}</p>
      </section>
      <section v-for='(analysis, index) in [review.beforeAnalysis, review.afterAnalysis]' :key='index' class='drawer-section'>
        <h3>{{ index === 0 ? '落子前' : '落子后' }}引擎结果</h3>
        <p class='micro'>{{ analysis.engineLabel }} · 搜索 {{ analysis.visitBudget }} 次 · {{ time(analysis.analyzedAt) }}</p>
        <p class='micro'>第 {{ analysis.moveIndex }} 手后 · {{ analysis.toPlay === 'black' ? '黑方' : '白方' }}行棋 · 以下指标为黑方视角</p>
        <div v-for='(candidate, candidateIndex) in analysis.candidates' :key='candidateIndex' class='review-candidate-detail'>
          <p>{{ 'ABC'[candidateIndex] }} · {{ coordinate(candidate.point, size) }} · 黑方胜率 {{ formatWinRate(candidate.blackWinRate) }} · 黑方预计领先 {{ formatScoreLead(candidate.blackScoreLead) }} 目</p>
          <p class='micro'>σ：{{ candidate.scoreStdev == null ? '未提供' : `${candidate.scoreStdev.toFixed(1)} 目` }}</p>
          <p class='micro'>{{ candidate.principalVariation.length ? candidate.principalVariation.map(point => coordinate(point, size)).join(' → ') : '引擎未提供变化' }}</p>
        </div>
      </section>
      <p class='micro'>σ 是最终目数预测标准差。点评用于辅助理解，不代表死活或胜负保证。</p>
    </template>
  </AppDialog>
</template>
