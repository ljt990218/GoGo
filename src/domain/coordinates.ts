import type { Point } from './types'

export const columns = 'ABCDEFGHJKLMNOPQRST'

export function coordinate(point: Point | null, size: number): string {
  return point === null ? '停一手' : `${columns[point.x]}${size - point.y}`
}

export function sgfPoint(value: string, size: number, allowPass = false): Point | null {
  if (allowPass && (value === '' || value === 'tt')) return null
  if (!/^[a-s]{2}$/.test(value)) throw new Error(`非法 SGF 坐标：${value || '空值'}`)
  const point = { x: value.charCodeAt(0) - 97, y: value.charCodeAt(1) - 97 }
  if (point.x >= size || point.y >= size) throw new Error(`坐标 ${value} 超出 ${size} 路棋盘`)
  return point
}

export function setupPoints(value: string, size: number): Point[] {
  const parts = value.split(':')
  if (parts.length > 2) throw new Error(`非法初始摆子坐标：${value}`)
  const start = sgfPoint(parts[0], size)!
  if (parts.length === 1) return [start]
  const end = sgfPoint(parts[1], size)!
  if (start.x > end.x || start.y > end.y) throw new Error(`摆子范围顺序错误：${value}`)
  const points: Point[] = []
  for (let y = start.y; y <= end.y; y++) {
    for (let x = start.x; x <= end.x; x++) points.push({ x, y })
  }
  return points
}
