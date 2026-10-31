export type Rules = 'chinese' | 'japanese'
export type Player = 'black' | 'white'

export interface Point {
  x: number
  y: number
}

export interface Candidate {
  point: Point | null
  blackWinRate: number
  blackScoreLead: number
  scoreStdev?: number | null
  principalVariation: (Point | null)[]
}

export interface AnalysisResult {
  moveIndex: number
  toPlay: Player
  candidates: Candidate[]
  engineLabel: string
  visitBudget: number
  analyzedAt: string
}

export interface GameRecord {
  gameId: string
  fileName: string
  sgfText: string
  boardSize: number
  rules: Rules
  komi: number
  totalMoves: number
  lastMoveIndex: number
  createdAt: string
  lastOpenedAt: string
  blackName?: string
  whiteName?: string
}

export interface AnalysisRecord {
  gameId: string
  moveIndex: number
  analysis: AnalysisResult
  candidateIndex?: number
  explanation: string | null
  aiModel: string | null
  explainedAt: string | null
}

export interface PositionRequest {
  sgfText: string
  moveIndex: number
  rules: Rules
  komi: number
}

export interface MoveExplanationResult {
  explanation: string
  aiModel: string
  explainedAt: string
}

export interface MoveReviewRecord {
  gameId: string
  moveIndex: number
  beforeAnalysis: AnalysisResult
  afterAnalysis: AnalysisResult
  explanation: string | null
  aiModel: string | null
  explainedAt: string | null
}

export type PlayerNames = Pick<GameRecord, 'blackName' | 'whiteName'>

export interface ExplanationResult {
  candidateIndex: number
  explanation: string
  aiModel: string
  explainedAt: string
}
