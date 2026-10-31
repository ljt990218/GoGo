import type { MoveReviewRecord, Player, PositionRequest } from '../domain/types'
import { validateAnalysis } from '../domain/results'
import { analyzePosition } from './api'

export async function analyzeMove(request: PositionRequest, gameId: string, size: number, player: Player, isCurrent = () => true): Promise<MoveReviewRecord | null> {
  const beforeAnalysis = await analyzePosition({ ...request, moveIndex: request.moveIndex - 1 })
  if (!isCurrent()) return null
  validateAnalysis(beforeAnalysis, size, request.moveIndex - 1, player)
  const afterAnalysis = await analyzePosition(request)
  if (!isCurrent()) return null
  validateAnalysis(afterAnalysis, size, request.moveIndex, player === 'black' ? 'white' : 'black')
  if (beforeAnalysis.engineLabel !== afterAnalysis.engineLabel || beforeAnalysis.visitBudget !== afterAnalysis.visitBudget) {
    throw new Error('落子前后的引擎配置发生变化，请重新点评')
  }
  return {
    gameId, moveIndex: request.moveIndex, beforeAnalysis, afterAnalysis,
    explanation: null, aiModel: null, explainedAt: null
  }
}
