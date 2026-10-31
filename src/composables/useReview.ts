import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import type { AnalysisRecord, GameRecord, PositionRequest, Rules } from '../domain/types'
import { gameIdentity, parseGame, positionAt, readSgf, validKomi } from '../domain/sgf'
import type { ParsedGame } from '../domain/sgf'
import { validateAnalysis } from '../domain/results'
import * as storage from '../services/storage'
import { analyzePosition, explainPosition, readSettings } from '../services/api'

interface ImportDraft {
  fileName: string
  sgfText: string
  parsed: ParsedGame
}

const recordKey = (gameId: string, moveIndex: number) => `${gameId}:${moveIndex}`
const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试'

export function useReview() {
  const games = shallowRef<GameRecord[]>([])
  const counts = ref<Record<string, number>>({})
  const currentId = ref<string | null>(null)
  const parsed = shallowRef<ParsedGame | null>(null)
  const moveIndex = ref(0)
  const records = shallowRef<Record<string, AnalysisRecord>>({})
  const errors = ref<Record<string, string>>({})
  const unsaved = ref(new Set<string>())
  const dirtyGames = shallowRef(new Map<string, GameRecord>())
  const savedKeys = new Set<string>()
  const parsedGames = new Map<string, ParsedGame>()
  const loadedGames = new Set<string>()
  const source = ref<Record<string, 'local' | 'fresh'>>({})
  const busy = ref<{ gameId: string, moveIndex: number, stage: 'analyzing' | 'explaining' } | null>(null)
  const batch = ref<{ gameId: string, fileName: string, index: number, end: number, stopping: boolean } | null>(null)
  const batchMessage = ref('')
  const batchStopMove = ref<number | null>(null)
  const batchSettingsLoading = ref(false)
  const batchSettingsError = ref('')
  const importing = ref(false)
  const initializing = ref(true)
  const loadingGame = ref(false)
  const storageError = ref('')
  const importError = ref('')
  const draft = shallowRef<ImportDraft | null>(null)
  const deleteTarget = shallowRef<GameRecord | null>(null)
  const deletingId = ref<string | null>(null)
  let openVersion = 0
  let gameWrites: Promise<void> = Promise.resolve()
  let disposed = false

  const currentGame = computed(() => games.value.find(game => game.gameId === currentId.value) ?? null)
  const key = computed(() => currentId.value ? recordKey(currentId.value, moveIndex.value) : '')
  const currentRecord = computed(() => records.value[key.value] ?? null)
  const position = computed(() => parsed.value ? positionAt(parsed.value, moveIndex.value) : null)
  const currentBusy = computed(() => busy.value?.gameId === currentId.value && busy.value.moveIndex === moveIndex.value ? busy.value.stage : null)
  const currentError = computed(() => errors.value[key.value] ?? '')
  const sortedGames = computed(() => [...games.value].sort((a, b) => b.lastOpenedAt.localeCompare(a.lastOpenedAt)))

  function replaceGame(game: GameRecord) {
    games.value = games.value.some(item => item.gameId === game.gameId)
      ? games.value.map(item => item.gameId === game.gameId ? game : item)
      : [...games.value, game]
  }

  function persistGame(game: GameRecord) {
    dirtyGames.value = new Map(dirtyGames.value).set(game.gameId, game)
    gameWrites = gameWrites.then(async () => {
      try {
        await storage.saveGame(game)
        if (dirtyGames.value.get(game.gameId) === game) {
          const next = new Map(dirtyGames.value)
          next.delete(game.gameId)
          dirtyGames.value = next
          if (!next.size && storageError.value.endsWith('浏览位置尚未保存')) storageError.value = ''
        }
      } catch (error) {
        storageError.value = `${messageOf(error)}；浏览位置尚未保存`
      }
    })
    return gameWrites
  }

  async function initialize() {
    if (busy.value || batch.value || importing.value) return
    initializing.value = true
    storageError.value = ''
    try {
      const [savedGames, savedCounts] = await Promise.all([storage.listGames(), storage.analysisCounts()])
      games.value = savedGames.map(game => dirtyGames.value.get(game.gameId) ?? game)
      counts.value = savedCounts
      if (!currentId.value && sortedGames.value[0]) await openGame(sortedGames.value[0])
    } catch (error) {
      storageError.value = messageOf(error)
    } finally {
      initializing.value = false
    }
  }

  async function openGame(game: GameRecord) {
    if (deletingId.value === game.gameId) return
    const version = ++openVersion
    loadingGame.value = true
    try {
      let nextParsed = parsedGames.get(game.gameId)
      if (!nextParsed) {
        nextParsed = parseGame(game.sgfText)
        parsedGames.set(game.gameId, nextParsed)
      }
      // 同步切换显示来源，迟到的其他局面请求只更新各自的内存缓存。
      currentId.value = game.gameId
      parsed.value = nextParsed
      moveIndex.value = Math.max(0, Math.min(game.lastMoveIndex, nextParsed.moves.length))
      if (!loadedGames.has(game.gameId)) {
        const saved = await storage.listAnalyses(game.gameId)
        if (disposed) return
        const nextRecords = { ...records.value }
        for (const record of saved) {
          const target = recordKey(game.gameId, record.moveIndex)
          if (record.moveIndex < 0 || record.moveIndex > nextParsed.moves.length) continue
          validateAnalysis(record.analysis, game.boardSize, record.moveIndex, positionAt(nextParsed, record.moveIndex).toPlay)
          savedKeys.add(target)
          if (!nextRecords[target]) {
            nextRecords[target] = record
            source.value[target] = 'local'
          }
        }
        records.value = nextRecords
        loadedGames.add(game.gameId)
      }
      if (version !== openVersion || disposed) return
      const updated = { ...game, lastMoveIndex: moveIndex.value, lastOpenedAt: new Date().toISOString() }
      replaceGame(updated)
      await persistGame(updated)
    } catch (error) {
      if (version === openVersion) storageError.value = `打开棋谱失败：${messageOf(error)}`
    } finally {
      if (version === openVersion) loadingGame.value = false
    }
  }

  function navigate(index: number) {
    if (!currentGame.value || !parsed.value || loadingGame.value || !Number.isInteger(index)) return
    const next = Math.max(0, Math.min(index, parsed.value.moves.length))
    if (next === moveIndex.value) return
    moveIndex.value = next
    const updated = { ...currentGame.value, lastMoveIndex: next }
    replaceGame(updated)
    void persistGame(updated)
  }

  async function importFile(file: File) {
    if (importing.value || draft.value) return
    importing.value = true
    importError.value = ''
    try {
      const sgfText = await readSgf(file)
      const parsed = parseGame(sgfText)
      const pending = { fileName: file.name, sgfText, parsed }
      if (parsed.rules === null || parsed.komi === null) draft.value = pending
      else await commitImport(pending, parsed.rules, parsed.komi)
    } catch (error) {
      importError.value = messageOf(error)
    } finally {
      importing.value = false
    }
  }

  async function commitImport(pending: ImportDraft, rules: Rules, komi: number) {
    if (!['chinese', 'japanese'].includes(rules) || !validKomi(komi)) throw new Error('请明确选择规则与有效贴目')
    const gameId = await gameIdentity(pending.sgfText, rules, komi)
    const existing = games.value.find(game => game.gameId === gameId) ?? await storage.getGame(gameId)
    if (existing) {
      replaceGame(existing)
      draft.value = null
      await openGame(existing)
      return
    }
    const now = new Date().toISOString()
    const game: GameRecord = {
      gameId, fileName: pending.fileName, sgfText: pending.sgfText,
      boardSize: pending.parsed.boardSize, rules, komi,
      totalMoves: pending.parsed.moves.length, lastMoveIndex: 0,
      createdAt: now, lastOpenedAt: now
    }
    // 导入必须完成事务后才替换当前棋谱。
    await storage.saveGame(game)
    replaceGame(game)
    parsedGames.set(gameId, pending.parsed)
    loadedGames.add(gameId)
    counts.value[gameId] = 0
    draft.value = null
    await openGame(game)
  }

  async function confirmImport(rules: Rules, komi: number) {
    if (!draft.value || importing.value) return
    importing.value = true
    importError.value = ''
    try { await commitImport(draft.value, rules, komi) } catch (error) { importError.value = messageOf(error) }
    finally { importing.value = false }
  }

  async function persistRecord(record: AnalysisRecord, explanationOnly = false) {
    const target = recordKey(record.gameId, record.moveIndex)
    unsaved.value.add(target)
    try {
      if (explanationOnly) await storage.saveExplanation(record)
      else await storage.saveAnalysis(record)
      if (!savedKeys.has(target)) {
        savedKeys.add(target)
        counts.value[record.gameId] = (counts.value[record.gameId] ?? 0) + 1
      }
      if (records.value[target] === record) unsaved.value.delete(target)
      return true
    } catch {
      return false
    }
  }

  async function runAnalysis(explanationOnly = false, candidateIndex = 0) {
    const game = currentGame.value
    const snapshot = position.value
    if (!game || !snapshot || busy.value || batch.value || loadingGame.value || saving.value || deletingId.value === game.gameId) return
    await analyzeAt(game, moveIndex.value, snapshot.toPlay, explanationOnly, candidateIndex)
  }

  async function analyzeAt(game: GameRecord, index: number, toPlay: 'black' | 'white', explanationOnly = false, candidateIndex = 0) {
    const target = recordKey(game.gameId, index)
    let record = records.value[target]
    if (explanationOnly && !record) return
    if (explanationOnly && !record.analysis.candidates[candidateIndex]) return
    const request: PositionRequest = { sgfText: game.sgfText, moveIndex: index, rules: game.rules, komi: game.komi }
    busy.value = { gameId: game.gameId, moveIndex: index, stage: explanationOnly ? 'explaining' : 'analyzing' }
    delete errors.value[target]
    try {
      let analysisSaved = !unsaved.value.has(target)
      if (!explanationOnly) {
        const analysis = await analyzePosition(request)
        validateAnalysis(analysis, game.boardSize, index, toPlay)
        record = { gameId: game.gameId, moveIndex: index, analysis, candidateIndex: 0, explanation: null, aiModel: null, explainedAt: null }
        records.value = { ...records.value, [target]: record }
        source.value[target] = 'fresh'
        analysisSaved = await persistRecord(record)
      }
      busy.value = { gameId: game.gameId, moveIndex: index, stage: 'explaining' }
      const explanation = await explainPosition(request, record.analysis, candidateIndex)
      if (explanation.candidateIndex !== candidateIndex ||
          typeof explanation.explanation !== 'string' || !explanation.explanation.trim() ||
          typeof explanation.aiModel !== 'string' || !explanation.aiModel.trim() ||
          typeof explanation.explainedAt !== 'string' || !Number.isFinite(Date.parse(explanation.explainedAt))) {
        throw new Error('AI 返回了空解释或无效结果，请重新生成解释')
      }
      const complete: AnalysisRecord = { ...record, ...explanation }
      records.value = { ...records.value, [target]: complete }
      const saved = await persistRecord(complete, analysisSaved)
      if (!saved) throw new Error('结果尚未保存，请重试保存后再继续分析')
      return true
    } catch (error) {
      const stage = busy.value?.stage
      const prefix = stage === 'analyzing' && record ? '本次刷新失败，保留原有结果。' : stage === 'explaining' ? '解释生成失败，已保留分析结果。' : ''
      errors.value[target] = `${prefix}${messageOf(error)}`
      return false
    } finally {
      busy.value = null
    }
  }

  function stopBatch() {
    if (batch.value) batch.value.stopping = true
  }

  async function loadBatchSettings() {
    if (batchSettingsLoading.value) return
    batchSettingsLoading.value = true
    batchSettingsError.value = ''
    batchStopMove.value = null
    try {
      const settings = await readSettings()
      batchStopMove.value = settings.stopMove
    } catch (error) {
      batchSettingsError.value = messageOf(error)
    } finally {
      batchSettingsLoading.value = false
    }
  }

  async function runBatch() {
    const game = currentGame.value
    const gameParsed = parsed.value
    if (!game || !gameParsed || !game.totalMoves || !batchStopMove.value || batchSettingsLoading.value || busy.value || batch.value || loadingGame.value || saving.value || deletingId.value || importing.value) return
    batch.value = { gameId: game.gameId, fileName: game.fileName, index: 0, end: 0, stopping: false }
    batchMessage.value = ''
    try {
      const settings = await readSettings()
      batchStopMove.value = settings.stopMove
      const end = Math.min(settings.stopMove, game.totalMoves)
      batch.value.end = end
      for (let index = 1, completed = 0; index <= end; index++) {
        if (batch.value.stopping || disposed) break
        batch.value.index = index
        const success = await analyzeAt(game, index, positionAt(gameParsed, index).toPlay)
        if (!success) {
          batchMessage.value = `「${game.fileName}」第 ${index} 手分析或保存失败，自动分析已停止。${errors.value[recordKey(game.gameId, index)] ?? ''}`
          return
        }
        completed++
        batchMessage.value = completed === end
          ? `「${game.fileName}」已完成第 1～${end} 手分析并保存。`
          : `「${game.fileName}」自动分析已停止，已完成 ${completed} / ${end} 手。`
      }
      if (!batchMessage.value) batchMessage.value = '自动分析已停止，尚未分析任何局面。'
    } catch (error) {
      batchMessage.value = `自动分析已停止：${messageOf(error)}`
    } finally {
      batch.value = null
    }
  }

  const saving = ref(false)
  async function retrySave() {
    if (saving.value || busy.value || batch.value) return
    saving.value = true
    try {
      for (const game of dirtyGames.value.values()) await persistGame(game)
      for (const target of [...unsaved.value]) {
        const record = records.value[target]
        if (record && deletingId.value !== record.gameId) await persistRecord(record)
      }
      if (!dirtyGames.value.size) storageError.value = ''
    } finally {
      saving.value = false
    }
  }

  async function confirmDelete() {
    const game = deleteTarget.value
    if (!game || deletingId.value || busy.value?.gameId === game.gameId || batch.value?.gameId === game.gameId || saving.value) return
    deletingId.value = game.gameId
    try {
      await gameWrites
      await storage.deleteGame(game.gameId)
      if (currentId.value === game.gameId) {
        openVersion++
        currentId.value = null
        parsed.value = null
        loadingGame.value = false
      }
      games.value = games.value.filter(item => item.gameId !== game.gameId)
      const nextRecords = { ...records.value }
      for (const target of Object.keys(nextRecords)) {
        if (nextRecords[target].gameId !== game.gameId) continue
        delete nextRecords[target]
        delete errors.value[target]
        delete source.value[target]
        savedKeys.delete(target)
        unsaved.value.delete(target)
      }
      records.value = nextRecords
      parsedGames.delete(game.gameId)
      loadedGames.delete(game.gameId)
      const dirty = new Map(dirtyGames.value)
      dirty.delete(game.gameId)
      dirtyGames.value = dirty
      delete counts.value[game.gameId]
      deleteTarget.value = null
    } catch (error) {
      storageError.value = `删除失败：${messageOf(error)}`
    } finally {
      deletingId.value = null
    }
  }

  function onKeydown(event: KeyboardEvent) {
    if (window.location.hash !== '#analysis') return
    const element = event.target as HTMLElement | null
    if (draft.value || deleteTarget.value || element?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]') || event.altKey || event.metaKey || event.ctrlKey) return
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault()
      navigate(moveIndex.value + (event.key === 'ArrowRight' ? 1 : -1))
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      navigate(event.key === 'Home' ? 0 : currentGame.value?.totalMoves ?? 0)
    }
  }

  onMounted(() => {
    void initialize()
    void loadBatchSettings()
    window.addEventListener('keydown', onKeydown)
  })
  onUnmounted(() => {
    disposed = true
    stopBatch()
    window.removeEventListener('keydown', onKeydown)
  })

  return {
    games: sortedGames, counts, currentGame, parsed, moveIndex, position, currentRecord, currentBusy,
    batch, batchMessage, batchStopMove, batchSettingsLoading, batchSettingsError, loadBatchSettings, runBatch, stopBatch, currentError, busy, initializing, loadingGame, importing, importError, draft, storageError,
    deleteTarget, deletingId, saving, unsaved, dirtyGames, source, key,
    initialize, openGame, navigate, importFile, confirmImport, runAnalysis, retrySave, confirmDelete
  }
}
