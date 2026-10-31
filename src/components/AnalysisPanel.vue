<script setup lang='ts'>
import { computed } from 'vue'
import AppDialog from './AppDialog.vue'
import MoveReviewContent from './MoveReviewContent.vue'
import type { Move } from '../domain/sgf'
import { columns, coordinate } from '../domain/coordinates'
import { formatScoreLead, formatWinRate } from '../domain/evaluation'
import type { AnalysisRecord, Candidate, MoveReviewRecord, Player, Point } from '../domain/types'

const props = defineProps<{
  mode: 'position' | 'move'
  review: MoveReviewRecord | null
  playedMove: Move | null
  temporary?: boolean
  record: AnalysisRecord | null
  size: number
  moveIndex: number
  toPlay: Player
  selectedIndex: number
  pendingCandidateIndex: number | null
  variation: Candidate | null
  detailsOpen: boolean
  stage: 'analyzing' | 'explaining' | null
  disabled: boolean
  unsaved: boolean
  saving: boolean
  source: 'local' | 'fresh' | undefined
  error: string
}>()
const emit = defineEmits<{
  analyze: []
  review: []
  refresh: []
  refreshReview: []
  explainReview: []
  explain: [candidateIndex: number]
  analyzeCandidate: [index: number]
  save: []
  openDetails: []
  closeDetails: []
  selectCandidate: [index: number]
  previewPoint: [point: Point | null]
  previewVariation: [candidate: Candidate]
}>()
const best = computed(() => props.record?.analysis.candidates[0] ?? null)
const selected = computed(() => props.record?.analysis.candidates[props.selectedIndex] ?? null)
const explanationIndex = computed(() => props.record?.candidateIndex ?? 0)
const explanationLabel = computed(() => {
  const candidate = props.record?.analysis.candidates[explanationIndex.value]
  return props.record?.explanation && candidate
    ? `${'ABC'[explanationIndex.value]} ${coordinate(candidate.point, props.size)}`
    : ''
})
function analyzeCandidate(index: number) {
  if (props.disabled || props.stage || props.pendingCandidateIndex !== null) return
  emit('analyzeCandidate', index)
}
const normalizedExplanation = computed(() => (props.record?.explanation?.trim() ?? '').replace(/\n\s*\n/g, '\n'))
const coreExplanation = computed(() => {
  const text = normalizedExplanation.value
  if (text.length <= 200) return text
  const sentences = text.match(/[^。！？!?]+[。！？!?]?/g) ?? []
  let excerpt = ''
  for (const sentence of sentences) {
    if (excerpt.length + sentence.length > 200) break
    excerpt += sentence
  }
  return excerpt.trim() || `${text.slice(0, 199)}…`
})
const isExcerpt = computed(() => coreExplanation.value !== normalizedExplanation.value)
function coordinateParts(text: string) {
  const parts: { text: string, point: Point | null }[] = []
  const pattern = /(?<![A-Za-z0-9_])[A-HJ-T](?:[1-9][0-9]*)(?![A-Za-z0-9_])/gi
  let offset = 0
  for (const match of text.matchAll(pattern)) {
    const x = columns.indexOf(match[0][0].toUpperCase())
    const row = Number(match[0].slice(1))
    if (x >= props.size || row > props.size) continue
    if (match.index > offset) parts.push({ text: text.slice(offset, match.index), point: null })
    parts.push({ text: match[0], point: { x, y: props.size - row } })
    offset = match.index + match[0].length
  }
  if (offset < text.length) parts.push({ text: text.slice(offset), point: null })
  return parts
}
const coreParts = computed(() => coordinateParts(coreExplanation.value))
const fullParts = computed(() => coordinateParts(props.record?.explanation ?? ''))
function previewCandidate(candidate: Candidate) {
  emit('previewVariation', candidate)
  emit('closeDetails')
}
function previewSelected() {
  if (selected.value?.principalVariation.length) emit('previewVariation', selected.value)
}
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <aside class='analysis-panel' aria-label='分析结果卡'>
    <slot name='controls' />
    <div class='analysis-actions' aria-label='选择分析方式'>
      <button type='button' :class='["button", "analyze-button", mode === "position" ? "primary" : "secondary"]' :aria-pressed='mode === "position"' :disabled='disabled' aria-keyshortcuts='a' title='分析局面（快捷键 A）' @click='emit("analyze")'>分析局面（A）</button>
      <button type='button' :class='["button", "analyze-button", mode === "move" ? "primary" : "secondary"]' :aria-pressed='mode === "move"' :disabled='disabled || moveIndex < 1' aria-keyshortcuts='s' :title='moveIndex < 1 ? "初始局面尚无可点评的着手" : "点评当前第 " + moveIndex + " 手（快捷键 S）"' @click='emit("review")'>点评此手（S）</button>
    </div>
    <MoveReviewContent v-if='mode === "move"' :review='review' :played-move='playedMove' :move-index='moveIndex' :size='size' :temporary='temporary' :stage='stage' :disabled='disabled' :unsaved='unsaved' :saving='saving' :source='source' :error='error' :details-open='detailsOpen' @refresh='emit("refreshReview")' @explain='emit("explainReview")' @save='emit("save")' @open-details='emit("openDetails")' @close-details='emit("closeDetails")' @preview-point='emit("previewPoint", $event)' />
    <template v-else>
    <header class='analysis-card-heading'>
      <div>
        <div class='section-row'><span class='section-label'>{{ record ? '推荐下一手' : '局面分析' }}</span><button v-if='record' type='button' class='text-button' :disabled='disabled' @click='emit("refresh")'>重新分析</button></div>
        <h2 class='recommendation-point'><span v-if='best' class='candidate-letter primary-letter'>A</span>{{ best ? coordinate(best.point, size) : '等待分析' }}</h2>
      </div>
      <div class='analysis-context'>
        <span class='turn-label'><span :class='["stone-dot", toPlay]' aria-hidden='true'></span>{{ toPlay === 'black' ? '黑方' : '白方' }}行棋</span>
        <span class='micro'>第 {{ moveIndex }} 手后<span v-if='record'> · {{ source === 'local' ? '本地记录' : '本次分析' }}</span></span>
      </div>
    </header>

    <section class='analysis-metrics' aria-label='首选候选的关键指标'>
      <div class='winrate-bar' role='img' :aria-label='best ? `引擎估计：黑棋胜率 ${formatWinRate(best.blackWinRate)}，白棋胜率 ${formatWinRate(1 - best.blackWinRate)}` : "黑白胜率等待分析"'>
        <div v-if='best' class='winrate-black-fill' :style='{ width: `${best.blackWinRate * 100}%` }' aria-hidden='true'></div>
        <span class='winrate-label'>黑棋 {{ best ? formatWinRate(best.blackWinRate) : '—' }}</span>
        <span class='winrate-label'>白棋 {{ best ? formatWinRate(1 - best.blackWinRate) : '—' }}</span>
      </div>
    </section>

    <section class='candidate-section' aria-label='候选比较'>
      <div class='section-row'>
        <h3>候选比较</h3>
        <button v-if='selected?.principalVariation.length' type='button' class='text-button candidate-preview' :aria-pressed='variation === selected' @click='previewSelected'>{{ variation === selected ? '退出预览' : `预览 ${'ABC'[selectedIndex]} 变化` }}</button>
        <span v-else class='micro'>按引擎顺序</span>
      </div>
      <div v-if='record' class='candidate-table' role='table' aria-label='候选点，全部数值为黑方视角'>
        <div class='candidate-row table-head' role='row'><span role='columnheader'>选点</span><span role='columnheader'>黑方胜率</span><span role='columnheader'>黑方预计领先</span></div>
        <div v-for='(candidate, index) in record.analysis.candidates' :key='index' :class='["candidate-row", { "candidate-selected": selectedIndex === index }]' role='row' @click='emit("selectCandidate", index)' @mouseenter='emit("previewPoint", candidate.point)' @mouseleave='emit("previewPoint", null)'>
          <span role='cell' class='candidate-point-cell'>
            <button type='button' class='candidate-select' :aria-pressed='selectedIndex === index' :aria-label='`选择候选 ${"ABC"[index]} ${coordinate(candidate.point, size)}`' @click.stop='emit("selectCandidate", index)' @focus='emit("previewPoint", candidate.point)' @blur='emit("previewPoint", null)'><span :class='["candidate-letter", { "primary-letter": index === 0 }]'>{{ 'ABC'[index] }}</span><strong>{{ coordinate(candidate.point, size) }}</strong></button>
            <button v-if='index > 0 || (selectedIndex === index && record.explanation && explanationIndex !== index) || pendingCandidateIndex === index' type='button' class='candidate-analyze' :disabled='disabled || !!stage || pendingCandidateIndex !== null' :aria-busy='pendingCandidateIndex === index' :aria-label='`分析候选 ${"ABC"[index]} ${coordinate(candidate.point, size)}`' @click.stop='analyzeCandidate(index)'>{{ pendingCandidateIndex === index ? '分析中…' : '分析此点' }}</button>
          </span>
          <span role='cell'>{{ formatWinRate(candidate.blackWinRate) }}</span>
          <span role='cell'>{{ formatScoreLead(candidate.blackScoreLead) }}<small> 目</small></span>
        </div>
      </div>
      <p v-else class='candidate-empty'>{{ stage === 'analyzing' ? '正在计算推荐选点…' : '分析后展示最多三个候选选点' }}</p>
    </section>

    <section class='explanation-section' aria-label='AI 分析结果' :aria-busy='stage === "explaining"'>
      <div class='section-row'>
        <h3>AI 分析<span v-if='explanationLabel'> · {{ explanationLabel }}</span></h3>
        <span v-if='stage' class='analysis-stage' role='status'><span class='spinner' aria-hidden='true'></span>{{ stage === 'analyzing' ? '引擎分析中' : '解释生成中' }}</span>
        <button v-else-if='record?.explanation' type='button' class='text-button' @click='emit("openDetails")'>{{ isExcerpt ? '节选 · 查看全文' : '查看详情' }}</button>
        <span v-else class='ai-tag'>AI 生成</span>
      </div>
      <p v-if='record?.explanation' class='explanation core-explanation'><template v-for='(part, index) in coreParts' :key='index'><button v-if='part.point' type='button' class='coordinate-link' :aria-label='`在棋盘定位 ${part.text}`' @mouseenter='emit("previewPoint", part.point)' @mouseleave='emit("previewPoint", null)' @focus='emit("previewPoint", part.point)' @blur='emit("previewPoint", null)'>{{ part.text }}</button><template v-else>{{ part.text }}</template></template></p>
      <div v-else class='analysis-empty'>
        <h3>{{ stage === 'explaining' ? '正在生成棋理解释' : record ? '引擎结果已就绪' : '从当前局面开始' }}</h3>
        <p>{{ stage === 'explaining' ? '推荐与指标已显示，解释将在此处直接呈现。' : record ? '生成中文解释，了解推荐选点的依据与取舍。' : '点击上方分析，查看推荐选点、关键指标与 AI 解释。' }}</p>
        <button v-if='record && stage !== "explaining"' class='button secondary' :disabled='disabled' @click='emit("explain", explanationIndex)'>{{ error ? '重试生成解释' : '生成解释' }}</button>
      </div>
    </section>

    <footer class='analysis-footer'>
      <div class='analysis-footer-status'>
        <button v-if='error' type='button' class='text-button analysis-error-link' :title='error' @click='emit("openDetails")'><span role='alert'>本次请求失败 · 查看详情<span class='visually-hidden'>：{{ error }}</span></span></button>
        <button v-else-if='unsaved' type='button' class='text-button save-warning' :disabled='disabled || saving' @click='emit("save")'>{{ saving ? '保存中…' : '尚未保存 · 重试' }}</button>
        <span v-else-if='record' class='save-status'><span class='status-dot'></span>{{ temporary ? '试下结果 · 仅临时保留' : '已保存到本地' }}</span>
        <span v-else class='micro'>仅分析当前局面</span>
        <button v-if='record && !error' type='button' class='text-button' @click='emit("openDetails")'>分析详情</button>
      </div>
    </footer>
    </template>
  </aside>

  <AppDialog v-if='detailsOpen && mode === "position"' title='分析详情' placement='right' @close='emit("closeDetails")'>
    <div class='drawer-heading-row'><span class='micro'>第 {{ moveIndex }} 手后 · {{ toPlay === 'black' ? '黑方' : '白方' }}行棋</span><button type='button' class='button secondary' @click='emit("closeDetails")'>关闭</button></div>
    <p v-if='error' class='notice error' role='alert'>{{ error }}</p>
    <template v-if='record'>
      <section class='drawer-section'>
        <div class='section-row'><h3>完整 AI 解释<span v-if='explanationLabel'> · {{ explanationLabel }}</span></h3><button type='button' class='text-button' :disabled='disabled' @click='emit("explain", explanationIndex)'>{{ record.explanation ? '重新生成解释' : '生成解释' }}</button></div>
        <p v-if='record.explanation' class='explanation'><template v-for='(part, index) in fullParts' :key='index'><button v-if='part.point' type='button' class='coordinate-link' :aria-label='`在棋盘定位 ${part.text}`' @mouseenter='emit("previewPoint", part.point)' @mouseleave='emit("previewPoint", null)' @focus='emit("previewPoint", part.point)' @blur='emit("previewPoint", null)'>{{ part.text }}</button><template v-else>{{ part.text }}</template></template></p>
        <p v-else class='micro'>{{ stage === 'explaining' ? '正在生成解释…' : '尚未生成解释。' }}</p>
        <p v-if='record.aiModel && record.explainedAt' class='micro'>{{ record.aiModel }} · {{ time(record.explainedAt) }}</p>
      </section>
      <section class='drawer-section'>
        <h3>候选主要变化</h3>
        <p class='micro'>点击后关闭详情并在棋盘预览，按 Esc 返回实战局面。</p>
        <button v-for='(candidate, index) in record.analysis.candidates' :key='index' type='button' class='variation-line' :disabled='!candidate.principalVariation.length' @click='previewCandidate(candidate)'><b>{{ 'ABC'[index] }} · {{ coordinate(candidate.point, size) }}</b><span>{{ candidate.principalVariation.length ? candidate.principalVariation.map(point => coordinate(point, size)).join(' → ') : '引擎未提供变化' }}</span></button>
      </section>
      <section class='drawer-section'>
        <h3>指标口径与引擎信息</h3>
        <p class='micro'>胜率与预计领先目数统一为黑方视角；领先为负表示白方领先。σ 是最终目数预测标准差。</p>
        <dl class='metric-list'>
          <div v-for='(candidate, index) in record.analysis.candidates' :key='index'><dt>{{ 'ABC'[index] }} · {{ coordinate(candidate.point, size) }} 的 σ</dt><dd>{{ candidate.scoreStdev == null ? '未提供，可重新分析获取' : `${candidate.scoreStdev.toFixed(1)} 目` }}</dd></div>
          <div><dt>分析引擎</dt><dd>{{ record.analysis.engineLabel }}</dd></div>
          <div><dt>搜索次数</dt><dd>{{ record.analysis.visitBudget }}</dd></div>
          <div><dt>分析时间</dt><dd>{{ time(record.analysis.analyzedAt) }}</dd></div>
        </dl>
      </section>
      <p class='micro'>解释用于辅助理解，不代表死活或胜负保证。</p>
    </template>
    <p v-else class='muted'>当前局面尚无分析结果，可关闭详情后重新分析。</p>
  </AppDialog>
</template>
