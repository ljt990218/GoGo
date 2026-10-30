import Board from '@sabaki/go-board'
import { parseTokens, tokenize } from '@sabaki/sgf'
import type { SgfNode, Token } from '@sabaki/sgf'
import { coordinate, setupPoints, sgfPoint } from './coordinates'
import type { Player, Point, Rules } from './types'

export const maxSgfBytes = 2 * 1024 * 1024
const rootOnly = ['AB', 'AW', 'AE', 'PL', 'SZ', 'RU', 'KM', 'HA', 'GM', 'FF', 'CA']
const ruleMap = new Map<string, Rules>([['chinese', 'chinese'], ['japanese', 'japanese']])

export interface Move {
  player: Player
  point: Point | null
}

export interface ParsedGame {
  boardSize: number
  rules: Rules | null
  komi: number | null
  originalRules: string | null
  initialPlayer: Player
  handicap: number
  moves: Move[]
  hasVariations: boolean
  checkpoints: Map<number, Board>
}

// Sabaki 负责词法和树解析；这里拒绝其容错解析会接受的残缺语法。
function validateStructure(tokens: Token[]) {
  const stack: { node: boolean, children: boolean, properties: Set<string> }[] = []
  let property: string | null = null
  let values = 0
  let roots = 0
  const finishProperty = () => {
    if (property !== null && values === 0) throw new Error(`SGF 属性 ${property} 缺少值`)
    property = null
    values = 0
  }

  for (const token of tokens) {
    const frame = stack.at(-1)
    const invalid = () => { throw new Error(`SGF 语法错误，第 ${token.row + 1} 行、第 ${token.col + 1} 列`) }
    if (token.type === 'parenthesis' && token.value === '(') {
      finishProperty()
      if (frame) {
        if (!frame.node) invalid()
        frame.children = true
      } else {
        roots++
      }
      stack.push({ node: false, children: false, properties: new Set() })
    } else if (token.type === 'parenthesis' && token.value === ')') {
      finishProperty()
      if (!frame?.node) invalid()
      stack.pop()
    } else if (token.type === 'semicolon') {
      finishProperty()
      if (!frame || frame.children) invalid()
      frame!.node = true
      frame!.properties.clear()
    } else if (token.type === 'prop_ident') {
      finishProperty()
      if (!frame?.node || frame.children || !/^[A-Z]+$/.test(token.value)) invalid()
      if (frame!.properties.has(token.value)) throw new Error(`SGF 属性 ${token.value} 在同一节点重复`)
      frame!.properties.add(token.value)
      property = token.value
    } else if (token.type === 'c_value_type') {
      if (property === null) invalid()
      values++
    } else {
      invalid()
    }
  }
  finishProperty()
  if (stack.length || roots === 0) throw new Error('SGF 语法不完整，缺少游戏树括号')
  if (roots !== 1) throw new Error('一个文件包含多盘棋，请拆分后导入')
}

function single(node: SgfNode, name: string): string | null {
  const values = node.data[name]
  if (!values) return null
  if (values.length !== 1) throw new Error(`属性 ${name} 必须只有一个值`)
  return values[0]
}

export function validKomi(value: number): boolean {
  return Number.isFinite(value) && value >= -50 && value <= 50 && Number.isInteger(value * 2)
}

export async function readSgf(file: File): Promise<string> {
  if (!file.name.toLowerCase().endsWith('.sgf')) throw new Error('请选择 .sgf 棋谱文件')
  if (file.size > maxSgfBytes) throw new Error('棋谱超过 2 MB，请选择更小的文件')
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()).replace(/^\uFEFF/, '')
  } catch {
    throw new Error('无法按 UTF-8 读取棋谱，请另存为 UTF-8 后导入')
  }
}

export function parseGame(text: string): ParsedGame {
  if (new TextEncoder().encode(text).length > maxSgfBytes) throw new Error('棋谱超过 2 MB')
  const tokens = tokenize(text.replace(/^\uFEFF/, ''))
  validateStructure(tokens)
  let roots: SgfNode[]
  try {
    roots = parseTokens(tokens)
  } catch {
    throw new Error('棋谱语法损坏或分支嵌套过深，无法解析')
  }
  const root = roots[0]
  const sizeText = single(root, 'SZ')
  if (!sizeText) throw new Error('棋谱缺少棋盘尺寸 SZ，无法导入')
  if (!['9', '13', '19'].includes(sizeText)) throw new Error('仅支持 9 路、13 路、19 路正方形棋盘')
  const boardSize = Number(sizeText)
  const charset = single(root, 'CA')
  if (charset && !['utf8', 'utf-8'].includes(charset.toLowerCase())) throw new Error('仅支持 UTF-8 编码，请另存后导入')
  const gameType = single(root, 'GM')
  if (gameType !== null && gameType !== '1') throw new Error('仅支持围棋 SGF（GM[1]）')
  const format = single(root, 'FF')
  if (format !== null && !['1', '2', '3', '4'].includes(format)) throw new Error('不支持此 SGF 格式版本')
  const originalRules = single(root, 'RU')
  const rules = originalRules === null ? null : ruleMap.get(originalRules.trim().toLowerCase()) ?? null
  const komiText = single(root, 'KM')
  const komi = komiText === null ? null : Number(komiText)
  if (komiText !== null && (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(komiText) || !validKomi(komi!))) {
    throw new Error('贴目 KM 必须在 -50～50 之间，且为 0.5 的倍数')
  }
  const handicapText = single(root, 'HA')
  if (handicapText !== null && !/^\d+$/.test(handicapText)) throw new Error('让子数 HA 必须是非负整数')
  const handicap = handicapText === null ? 0 : Number(handicapText)
  if (handicap === 1 || handicap > boardSize * boardSize) throw new Error('让子数 HA 必须为 0 或至少 2，且不能超过棋盘容量')
  const player = single(root, 'PL')
  if (player !== null && player !== 'B' && player !== 'W') throw new Error('根节点 PL 必须为 B 或 W')
  const initialPlayer: Player = player === 'W' || (player === null && handicap >= 2) ? 'white' : 'black'
  let toPlay = initialPlayer
  let board = Board.fromDimensions(boardSize)
  const occupied = new Set<string>()
  let blackSetup = 0
  for (const [name, sign] of [['AB', 1], ['AW', -1], ['AE', 0]] as const) {
    for (const value of root.data[name] ?? []) {
      for (const point of setupPoints(value, boardSize)) {
        const key = `${point.x},${point.y}`
        if (occupied.has(key)) throw new Error(`初始摆子 ${coordinate(point, boardSize)} 重复或重叠`)
        occupied.add(key)
        board.set([point.x, point.y], sign)
        if (sign === 1) blackSetup++
      }
    }
  }
  if (handicap >= 2 && blackSetup !== handicap) throw new Error('HA 与 AB 初始黑子数量不一致，不能推测让子位置')
  if (!board.isValid()) throw new Error('初始摆子存在无气棋块，无法导入')
  const checkpoints = new Map<number, Board>([[0, board]])
  const moves: Move[] = []
  let previousBoard: string | null = null
  let hasVariations = false
  let node: SgfNode | undefined = root
  while (node) {
    if (node !== root) {
      const unsupported = rootOnly.find(name => name in node!.data)
      if (unsupported) throw new Error(`第 ${moves.length} 手之后出现中途属性 ${unsupported}，MVP 不支持`)
    }
    if ('KO' in node.data) throw new Error('不支持 KO 强制非法着手属性')
    if ('B' in node.data && 'W' in node.data) throw new Error('同一节点不能同时包含黑白着手')
    const color = 'B' in node.data ? 'B' : 'W' in node.data ? 'W' : null
    if (color) {
      if (['AB', 'AW', 'AE'].some(name => name in node!.data)) throw new Error('同一节点不能混合初始摆子与着手')
      const actual: Player = color === 'B' ? 'black' : 'white'
      if (actual !== toPlay) throw new Error(`第 ${moves.length + 1} 手行棋方错误，应轮到${toPlay === 'black' ? '黑' : '白'}方`)
      const point = sgfPoint(single(node, color)!, boardSize, true)
      const before = JSON.stringify(board.signMap)
      if (point) {
        const vertex: [number, number] = [point.x, point.y]
        const sign = actual === 'black' ? 1 : -1
        const legality = board.analyzeMove(sign, vertex)
        const label = `第 ${moves.length + 1} 手 ${coordinate(point, boardSize)}`
        if (legality.overwrite) throw new Error(`${label}：交叉点已有棋子`)
        if (legality.suicide) throw new Error(`${label}：不允许自杀落子`)
        const next = board.makeMove(sign, vertex, { preventOverwrite: true, preventSuicide: true })
        if (JSON.stringify(next.signMap) === previousBoard) throw new Error(`${label}：不允许立即回提劫`)
        board = next
      }
      // 停一手也推进历史，让简单劫限制正确解除；不依赖库的 pass 劫状态。
      previousBoard = before
      moves.push({ player: actual, point })
      if (moves.length % 32 === 0) checkpoints.set(moves.length, board)
      toPlay = actual === 'black' ? 'white' : 'black'
    }
    if (node.children.length > 1) hasVariations = true
    node = node.children[0]
  }
  return { boardSize, rules, komi, originalRules, initialPlayer, handicap, moves, hasVariations, checkpoints }
}

export function positionAt(game: ParsedGame, moveIndex: number) {
  const checkpoint = Math.floor(moveIndex / 32) * 32
  let board = game.checkpoints.get(checkpoint)!
  for (let i = checkpoint; i < moveIndex; i++) {
    const move = game.moves[i]
    if (move.point) board = board.makeMove(move.player === 'black' ? 1 : -1, [move.point.x, move.point.y])
  }
  const lastMove = moveIndex === 0 ? null : game.moves[moveIndex - 1]
  const toPlay: Player = lastMove ? (lastMove.player === 'black' ? 'white' : 'black') : game.initialPlayer
  return { board: board.signMap, toPlay, lastMove }
}

export async function gameIdentity(sgfText: string, rules: Rules, komi: number): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify({ sgfText, rules, komi }))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
}

// 保留初始摆子和完整着手历史，供试下分析使用；不携带原棋谱注释。
export function trialSgf(game: ParsedGame, moveIndex: number, trialMoves: Move[], rules: Rules, komi: number): string {
  const encodePoint = (point: Point | null) => point === null ? '' : String.fromCharCode(97 + point.x, 97 + point.y)
  const initial = game.checkpoints.get(0)!
  let root = `(;GM[1]FF[4]CA[UTF-8]SZ[${game.boardSize}]RU[${rules}]KM[${komi}]PL[${game.initialPlayer === 'black' ? 'B' : 'W'}]`
  if (game.handicap >= 2) root += `HA[${game.handicap}]`
  for (const [property, sign] of [['AB', 1], ['AW', -1]] as const) {
    const points = initial.signMap.flatMap((row, y) => row.flatMap((stone, x) => stone === sign ? [`[${encodePoint({ x, y })}]`] : []))
    if (points.length) root += property + points.join('')
  }
  const moves = [...game.moves.slice(0, moveIndex), ...trialMoves]
  return root + moves.map(move => `;${move.player === 'black' ? 'B' : 'W'}[${encodePoint(move.point)}]`).join('') + ')'
}
