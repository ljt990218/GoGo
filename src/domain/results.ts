import type { AnalysisResult, MoveExplanationResult, Player, Point } from './types'

export function validateExplanation(value: MoveExplanationResult) {
  if (!value || typeof value.explanation !== 'string' || !value.explanation.trim() ||
      typeof value.aiModel !== 'string' || !value.aiModel.trim() ||
      typeof value.explainedAt !== 'string' || !Number.isFinite(Date.parse(value.explainedAt))) {
    throw new Error('AI 返回了空解释或无效结果，请重新生成解释')
  }
}

export function validateAnalysis(value: AnalysisResult, size: number, moveIndex: number, toPlay: Player) {
  const fail = () => { throw new Error('分析结果无法对应当前局面，请重试') }
  const pointValid = (point: Point | null) => point === null || (
    point && Number.isInteger(point.x) && Number.isInteger(point.y) &&
    point.x >= 0 && point.x < size && point.y >= 0 && point.y < size
  )
  if (!value || value.moveIndex !== moveIndex || value.toPlay !== toPlay) fail()
  if (!Array.isArray(value.candidates) || value.candidates.length < 1 || value.candidates.length > 3) fail()
  if (typeof value.engineLabel !== 'string' || !value.engineLabel.trim() ||
      !Number.isInteger(value.visitBudget) || value.visitBudget < 1 ||
      typeof value.analyzedAt !== 'string' || !Number.isFinite(Date.parse(value.analyzedAt))) fail()
  const seen = new Set<string>()
  for (const candidate of value.candidates) {
    if (!candidate || !pointValid(candidate.point) ||
        !Number.isFinite(candidate.blackWinRate) || candidate.blackWinRate < 0 || candidate.blackWinRate > 1 ||
        !Number.isFinite(candidate.blackScoreLead) || !Array.isArray(candidate.principalVariation) ||
        !candidate.principalVariation.every(pointValid)) fail()
    if (candidate.scoreStdev !== undefined && candidate.scoreStdev !== null &&
        (!Number.isFinite(candidate.scoreStdev) || candidate.scoreStdev < 0)) fail()
    const key = candidate.point === null ? 'pass' : `${candidate.point.x},${candidate.point.y}`
    if (seen.has(key)) fail()
    seen.add(key)
  }
}
