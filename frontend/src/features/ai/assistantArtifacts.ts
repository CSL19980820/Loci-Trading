import type { AiArtifactKind, AiChartArtifact } from '@/shared/types/ai_assistant'
import type { OhlcBar } from '@/shared/lib/indicators'

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

export interface ArtifactTableColumn {
  prop: string
  label: string
  width?: number | string
}

export interface ArtifactTablePayload {
  columns: ArtifactTableColumn[]
  rows: Record<string, unknown>[]
  paginate: boolean
  pageSize: number
}

export interface ArtifactSourceItem {
  label: string
  detail?: string
  code?: string
  date?: string
  hash?: string
}

export interface ArtifactEquityPayload {
  dates: string[]
  values: Array<number | null>
}

/** Known rich-render kinds (ADR-006 大包 C). Unknown kinds fall back to JSON. */
export const KNOWN_ARTIFACT_KINDS = new Set<string>([
  'kline',
  'qianlong_kline',
  'table',
  'echarts',
  'dual_axis',
  'equity_curve',
  'candidate_verdict',
  'source_strip',
  'code',
])

export const ASSISTANT_KLINE_MA = [5, 10, 20] as const
export const ASSISTANT_KLINE_MIN_VISIBLE = 20

export function normalizeArtifactKind(kind: unknown): AiArtifactKind {
  const value = typeof kind === 'string' ? kind.trim() : ''
  return value || 'code'
}

export function isKlineKind(kind: AiArtifactKind): boolean {
  return kind === 'kline' || kind === 'qianlong_kline'
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

/** Parse tool OHLC into shared OhlcBar[]; insufficient bars stay as-is for the card to warn. */
export function parseKlineBars(data: Record<string, unknown>): OhlcBar[] {
  const rows = arrayValue(data.bars ?? data.kline ?? data.candles)
  return rows.map((row, index) => {
    if (Array.isArray(row)) {
      const dated = typeof row[0] === 'string' && /\d{4}-\d{2}-\d{2}/.test(row[0])
      // dated: [date, open, high, low, close, volume?]；否则 [open, close, high, low, volume?]
      const open = numeric(dated ? row[1] : row[0])
      const high = numeric(dated ? row[2] : row[2])
      const low = numeric(dated ? row[3] : row[3])
      const close = numeric(dated ? row[4] : row[1])
      const volume = numeric(dated ? row[5] : row[4])
      return {
        trade_date: dated ? String(row[0]) : `T${String(index + 1).padStart(3, '0')}`,
        open: open ?? null,
        high: high ?? null,
        low: low ?? null,
        close: close ?? null,
        volume: volume ?? null,
      }
    }
    const values = objectValue(row)
    return {
      trade_date: stringValue(values.trade_date ?? values.date ?? values.day) ?? `T${index + 1}`,
      open: numberValue(values.open) ?? null,
      high: numberValue(values.high) ?? null,
      low: numberValue(values.low) ?? null,
      close: numberValue(values.close) ?? null,
      volume: numberValue(values.volume ?? values.vol) ?? null,
      amount: numberValue(values.amount) ?? null,
    }
  }).filter((bar) => [bar.open, bar.high, bar.low, bar.close].every((v) => v != null && Number.isFinite(v)))
}

export function parseTablePayload(data: Record<string, unknown>): ArtifactTablePayload {
  const rawColumns = arrayValue(data.columns)
  const rows = arrayValue(data.rows ?? data.items).map((row) => objectValue(row))
  let columns: ArtifactTableColumn[] = rawColumns.map((col, index) => {
    if (typeof col === 'string') return { prop: col, label: col }
    const values = objectValue(col)
    const prop = stringValue(values.prop ?? values.key ?? values.field) ?? `col_${index}`
    return {
      prop,
      label: stringValue(values.label ?? values.title) ?? prop,
      width: (values.width as number | string | undefined),
    }
  })
  if (!columns.length && rows[0]) {
    columns = Object.keys(rows[0]).map((key) => ({ prop: key, label: key }))
  }
  const pageSize = Math.max(5, Math.min(100, numberValue(data.pageSize ?? data.page_size) ?? 20))
  const paginate = data.paginate === true || rows.length > 50
  return { columns, rows, paginate, pageSize }
}

const ECHARTS_SERIES_WHITELIST = new Set([
  'line', 'bar', 'pie', 'scatter', 'candlestick', 'heatmap', 'radar', 'funnel', 'gauge',
])

/** Accept only JSON-serializable option with whitelisted series types. */
export function parseEchartsOption(data: Record<string, unknown>): Record<string, unknown> | null {
  const option = objectValue(data.option ?? data)
  if (!Object.keys(option).length) return null
  try {
    JSON.stringify(option)
  } catch {
    return null
  }
  const series = Array.isArray(option.series) ? option.series : option.series && typeof option.series === 'object' ? [option.series] : []
  if (!series.length) return null
  for (const item of series) {
    const type = stringValue(objectValue(item).type)
    if (type && !ECHARTS_SERIES_WHITELIST.has(type)) return null
  }
  return option
}

export function parseEquityPayload(data: Record<string, unknown>): ArtifactEquityPayload {
  const points = arrayValue(data.points ?? data.series)
  if (points.length) {
    const dates: string[] = []
    const values: Array<number | null> = []
    for (const point of points) {
      if (Array.isArray(point)) {
        const date = String(point[0] ?? '')
        const value = numeric(point[1])
        if (date) { dates.push(date); values.push(value ?? null) }
        continue
      }
      const row = objectValue(point)
      const date = stringValue(row.date ?? row.trade_date ?? row.day)
      const value = numberValue(row.value ?? row.equity ?? row.nav)
      if (date) { dates.push(date); values.push(value ?? null) }
    }
    return { dates, values }
  }
  const dates: string[] = []
  const values: Array<number | null> = []
  const rawValues = arrayValue(data.values)
  for (const [index, date] of arrayValue(data.dates).entries()) {
    if (date == null || date === '') continue
    dates.push(String(date))
    values.push(numeric(rawValues[index]) ?? null)
  }
  return { dates, values }
}

export function parseSources(data: Record<string, unknown>): ArtifactSourceItem[] {
  const rows = arrayValue(data.sources ?? data.items ?? data.evidence)
  return rows.map((row, index) => {
    if (typeof row === 'string') return { label: row }
    const values = objectValue(row)
    return {
      label: stringValue(values.label ?? values.title ?? values.name) ?? `来源 ${index + 1}`,
      detail: stringValue(values.detail ?? values.summary ?? values.url),
      code: stringValue(values.code),
      date: stringValue(values.date ?? values.trade_date),
      hash: stringValue(values.hash ?? values.sha256),
    }
  })
}

export function parseCodePayload(data: Record<string, unknown>): { language: string; text: string } {
  const text = stringValue(data.text ?? data.code ?? data.content)
    ?? (Object.keys(data).length ? JSON.stringify(data, null, 2) : '')
  return {
    language: stringValue(data.language ?? data.lang) ?? 'json',
    text,
  }
}

export function artifactShellTitle(artifact: AiChartArtifact): string {
  if (artifact.title?.trim()) return artifact.title.trim()
  if (isKlineKind(artifact.kind)) return artifact.kind === 'qianlong_kline' ? '潜龙 K 线' : 'K 线'
  if (artifact.kind === 'candidate_verdict') return '候选精选'
  if (artifact.kind === 'table') return '数据表'
  if (artifact.kind === 'echarts' || artifact.kind === 'dual_axis') return '统计图'
  if (artifact.kind === 'equity_curve') return '净值曲线'
  if (artifact.kind === 'source_strip') return '来源'
  if (artifact.kind === 'code') return '代码'
  return String(artifact.kind || '产物')
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

function numeric(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : typeof value === 'string' && value.trim() && Number.isFinite(Number(value))
      ? Number(value)
      : undefined
}
