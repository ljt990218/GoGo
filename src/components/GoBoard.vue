<script setup lang='ts'>
import { computed, onUnmounted, ref, watch } from 'vue'
import Board from '@sabaki/go-board'
import type { SignMap } from '@sabaki/go-board'
import { columns, coordinate } from '../domain/coordinates'
import { formatScoreLead, formatWinRate } from '../domain/evaluation'
import type { Candidate, Player, Point } from '../domain/types'

const props = defineProps<{
  size: number
  board: number[][]
  lastPoint: Point | null
  candidates: Candidate[]
  toPlay: Player
  selectedIndex: number
  highlightedPoint: Point | null
  variation: Candidate | null
}>()
const emit = defineEmits<{
  selectCandidate: [index: number]
  exitPreview: []
  play: [point: Point]
}>()

const padding = 34
const step = computed(() => 560 / (props.size - 1))
const at = (index: number) => padding + index * step.value
const radius = computed(() => Math.min(step.value * 0.46, 23))
const indices = computed(() => Array.from({ length: props.size }, (_, index) => index))
const stars = computed(() => {
  const edge = props.size === 9 ? 2 : 3
  const middle = (props.size - 1) / 2
  const positions = props.size === 19 ? [edge, middle, props.size - 1 - edge] : [edge, props.size - 1 - edge]
  const points = positions.flatMap(y => positions.map(x => ({ x, y })))
  if (props.size !== 19) points.push({ x: middle, y: middle })
  return points
})
const previewStep = ref(0)
let previewTimer: ReturnType<typeof setInterval> | null = null
function stopTimer() {
  if (previewTimer !== null) clearInterval(previewTimer)
  previewTimer = null
}
const preview = computed(() => {
  let board = new Board(props.board.map(row => [...row]) as SignMap)
  const labels = new Map<string, { x: number, y: number, step: number }>()
  const line = props.variation?.principalVariation ?? []
  let played = 0
  for (let index = 0; index < Math.min(previewStep.value, line.length); index++) {
    const point = line[index]
    const sign = (props.toPlay === 'black') === (index % 2 === 0) ? 1 : -1
    if (point) {
      const vertex: [number, number] = [point.x, point.y]
      const legality = board.analyzeMove(sign, vertex)
      if (legality.overwrite || legality.suicide) break
      board = board.makeMove(sign, vertex, { preventOverwrite: true, preventSuicide: true })
      // 提走的棋子同时移除编号，回到相同交叉点时显示最新步数。
      for (const [key, label] of labels) {
        if (board.get([label.x, label.y]) === 0) labels.delete(key)
      }
      labels.set(`${point.x},${point.y}`, { ...point, step: index + 1 })
    }
    played = index + 1
  }
  return { board: board.signMap, labels: [...labels.values()], played }
})
watch([() => props.variation, () => props.board, () => props.toPlay], () => {
  stopTimer()
  previewStep.value = 0
  const length = props.variation?.principalVariation.length ?? 0
  if (!length) return
  previewStep.value = 1
  if (length === 1) return
  previewTimer = setInterval(() => {
    if (preview.value.played < previewStep.value) {
      stopTimer()
      return
    }
    previewStep.value++
    if (previewStep.value >= length) stopTimer()
  }, 250)
}, { immediate: true, flush: 'sync' })
onUnmounted(stopTimer)
const previewing = computed(() => !!props.variation?.principalVariation.length)
const displayedBoard = computed(() => previewing.value ? preview.value.board : props.board)
const stones = computed(() => displayedBoard.value.flatMap((row, y) => row.flatMap((sign, x) => sign ? [{ x, y, sign }] : [])))
</script>

<template>
  <div class='board-surface'>
    <svg viewBox='0 0 628 628' class='go-board' role='group' :aria-label='`${size} 路棋盘，共 ${stones.length} 颗棋子。点击空位开始试下，在分析区查看黑方视角指标。`'>
      <defs>
        <radialGradient id='black-stone' cx='32%' cy='25%' r='75%'>
          <stop offset='0' stop-color='#50514d' />
          <stop offset='0.65' stop-color='#222522' />
          <stop offset='1' stop-color='#111613' />
        </radialGradient>
        <radialGradient id='white-stone' cx='30%' cy='22%' r='80%'>
          <stop offset='0' stop-color='#ffffff' />
          <stop offset='0.72' stop-color='#f7f6ef' />
          <stop offset='1' stop-color='#dcdcd3' />
        </radialGradient>
      </defs>
      <g class='board-grid'>
        <template v-for='index in indices' :key='index'>
          <line :x1='at(index)' :y1='padding' :x2='at(index)' :y2='594' />
          <line :x1='padding' :y1='at(index)' :x2='594' :y2='at(index)' />
        </template>
        <rect x='34' y='34' width='560' height='560' fill='none' stroke-width='1.6' />
      </g>
      <g class='board-coordinate'>
        <template v-for='index in indices' :key='index'>
          <text :x='at(index)' y='16'>{{ columns[index] }}</text>
          <text :x='at(index)' y='615'>{{ columns[index] }}</text>
          <text x='15' :y='at(index) + 4'>{{ size - index }}</text>
          <text x='613' :y='at(index) + 4'>{{ size - index }}</text>
        </template>
      </g>
      <circle v-for='point in stars' :key='`${point.x}-${point.y}`' :cx='at(point.x)' :cy='at(point.y)' r='3.1' fill='#756449' />
      <g v-for='stone in stones' :key='`${stone.x}-${stone.y}`'>
        <circle :cx='at(stone.x) + 0.8' :cy='at(stone.y) + 1.6' :r='radius' fill='#5b4d33' opacity='.23' />
        <circle :cx='at(stone.x)' :cy='at(stone.y)' :r='radius' :fill='stone.sign === 1 ? "url(#black-stone)" : "url(#white-stone)"' :stroke='stone.sign === 1 ? "#151b16" : "#c8c8bd"' stroke-width='.6'>
          <title>{{ stone.sign === 1 ? '黑' : '白' }} {{ coordinate(stone, size) }}</title>
        </circle>
        <circle v-if='!previewing && lastPoint?.x === stone.x && lastPoint?.y === stone.y' :cx='at(stone.x)' :cy='at(stone.y)' :r='radius * .28' fill='none' :stroke='stone.sign === 1 ? "#eceee3" : "#455847"' stroke-width='1.8' />
      </g>
      <template v-for='(candidate, index) in candidates' :key='index'>
        <g v-if='candidate.point && !previewing' class='board-candidate' role='button' tabindex='0' :aria-label='`选择候选 ${"ABC"[index]} ${coordinate(candidate.point, size)}，黑方胜率 ${formatWinRate(candidate.blackWinRate)}，黑方领先 ${formatScoreLead(candidate.blackScoreLead)} 目`' :aria-pressed='selectedIndex === index' @click='emit("selectCandidate", index)' @keydown.enter.prevent='emit("selectCandidate", index)' @keydown.space.prevent='emit("selectCandidate", index)'>
          <circle v-if='selectedIndex === index' :cx='at(candidate.point.x)' :cy='at(candidate.point.y)' :r='radius + 3' fill='none' stroke='#a34324' stroke-width='1.8' />
          <circle :cx='at(candidate.point.x)' :cy='at(candidate.point.y)' :r='radius' :fill='toPlay === "black" ? "#111613" : "#fffefa"' :fill-opacity='[1, .75, .5][index]' :stroke='toPlay === "black" ? "#111613" : "#929887"' :stroke-opacity='[1, .75, .5][index]' :stroke-width='index === 0 ? 1.8 : 1' />
          <text :x='at(candidate.point.x)' :y='at(candidate.point.y)' dominant-baseline='central' text-anchor='middle' font-weight='700' :fill='toPlay === "black" ? "#ffffff" : "#26382b"' :font-size='radius * 1.05' class='candidate-metrics'>{{ 'ABC'[index] }}</text>
          <title>候选 {{ 'ABC'[index] }}：{{ coordinate(candidate.point, size) }}，黑方胜率 {{ formatWinRate(candidate.blackWinRate) }}，黑方领先 {{ formatScoreLead(candidate.blackScoreLead) }} 目</title>
        </g>
      </template>
      <g v-if='previewing' class='variation-stones'>
        <text v-for='label in preview.labels' :key='`${label.x}-${label.y}`' :x='at(label.x)' :y='at(label.y)' dominant-baseline='central' text-anchor='middle' :font-size='radius * .9' font-weight='700' :fill='displayedBoard[label.y][label.x] === 1 ? "#ffffff" : "#315d49"'>{{ label.step }}</text>
      </g>
      <g v-if='!previewing' class='trial-intersections'>
        <template v-for='y in indices' :key='y'>
          <rect v-for='x in indices' :key='x' :x='at(x) - step / 2' :y='at(y) - step / 2' :width='step' :height='step' fill='transparent' role='button' :tabindex='board[y][x] === 0 ? 0 : -1' :aria-label='`试下 ${coordinate({ x, y }, size)}`' @click='emit("play", { x, y })' @keydown.enter.prevent='emit("play", { x, y })' @keydown.space.prevent='emit("play", { x, y })' />
        </template>
      </g>
      <g v-if='highlightedPoint' class='coordinate-highlight' pointer-events='none'>
        <circle :cx='at(highlightedPoint.x)' :cy='at(highlightedPoint.y)' :r='radius + 2' fill='none' stroke='#fffefa' stroke-width='4' />
        <circle :cx='at(highlightedPoint.x)' :cy='at(highlightedPoint.y)' :r='radius + 3' fill='none' stroke='#a34324' stroke-width='2' />
        <title>{{ coordinate(highlightedPoint, size) }}</title>
      </g>
    </svg>
    <div v-if='previewing && variation' class='variation-preview-status' role='status' aria-live='off'>
      <span>{{ 'ABC'[candidates.indexOf(variation)] }} 变化 · 第 {{ preview.played }} / {{ variation.principalVariation.length }} 手<span v-if='preview.played && variation.principalVariation[preview.played - 1] === null'> · 停一手</span><span v-if='preview.played < previewStep'> · 变化无法继续</span></span>
      <button type='button' class='text-button' @click='emit("exitPreview")'>退出预览</button>
    </div>
  </div>
</template>
