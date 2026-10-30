export const formatWinRate = (value: number) => `${(value * 100).toFixed(1)}%`

export function formatScoreLead(value: number) {
  const rounded = Number(value.toFixed(1))
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}`
}

export function describeScoreLead(value: number) {
  const rounded = Number(value.toFixed(1))
  if (rounded === 0) return '预计双方目差 0.0 目'
  return `${rounded > 0 ? '黑方' : '白方'}预计领先 ${Math.abs(rounded).toFixed(1)} 目`
}
