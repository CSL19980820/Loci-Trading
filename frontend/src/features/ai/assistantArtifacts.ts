export interface CandidateDecision {
  id: string
  code: string
  name: string
  decision: string
  score?: number
  reason?: string
  occurredOn?: string
  timing?: string
  invalidation?: string
  pctChange?: number
  volumeRatio?: number
  ma5Deviation?: number
  ma20Deviation?: number
}

export function candidateDecisions(data: Record<string, unknown>): CandidateDecision[] {
  const rows = arrayValue(data.candidates ?? data.items)
  return rows.map((row, index) => {
    const values = objectValue(row)
    const evidence = objectValue(values.evidence)
    const close = numberValue(values.close ?? evidence.close)
    const ma5 = numberValue(values.ma5 ?? evidence.ma5)
    const ma20 = numberValue(values.ma20 ?? evidence.ma20)
    const code = stringValue(values.code) ?? ''
    const decision = stringValue(values.decision) ?? '观察'
    const occurredOn = stringValue(values.occurred_on ?? values.date)
    return {
      id: stringValue(values.id) ?? `${code || 'candidate'}-${occurredOn ?? index}-${decision}`,
      code,
      name: stringValue(values.name) ?? '未命名候选',
      decision,
      score: numberValue(values.score),
      reason: stringValue(values.reason),
      occurredOn,
      timing: stringValue(values.timing),
      invalidation: stringValue(values.invalidation ?? evidence.invalidation),
      pctChange: numberValue(values.pct_chg ?? values.pctChange ?? evidence.pct_chg),
      volumeRatio: numberValue(values.volume_ratio ?? values.volumeRatio ?? evidence.volume_ratio),
      ma5Deviation: deviation(close, ma5),
      ma20Deviation: deviation(close, ma20),
    }
  })
}

export function percent(value: number | undefined): string {
  if (value == null) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function decimal(value: number | undefined): string {
  return value == null ? '—' : value.toFixed(2)
}

function deviation(close: number | undefined, movingAverage: number | undefined): number | undefined {
  if (close == null || movingAverage == null || movingAverage === 0) return undefined
  return ((close - movingAverage) / movingAverage) * 100
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function numberValue(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : Number.NaN
  return Number.isFinite(number) ? number : undefined
}
