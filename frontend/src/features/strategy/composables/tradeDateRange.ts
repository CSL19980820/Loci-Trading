/** 选股台交易日窗口：快捷泡 + 跨度校验（与后端 screen_dates 对齐） */

export const MAX_INCLUSIVE_DAYS = 31

export type TradeDatePreset = 'today' | 'this_week' | 'last_week' | 'last_30' | 'prev_month'

export type TradeDateRange = [string, string]

export const TRADE_DATE_PRESETS: Array<{ id: TradeDatePreset; label: string }> = [
  { id: 'today', label: '今日' },
  { id: 'this_week', label: '本周' },
  { id: 'last_week', label: '上周' },
  { id: 'last_30', label: '近一月' },
  { id: 'prev_month', label: '上一月' },
]

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function toIsoDate(value: Date): string {
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

export function parseIsoDate(value: string): Date | null {
  const raw = String(value || '').trim().slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null
  const [y, m, d] = raw.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) return null
  return date
}

export function inclusiveDaySpan(start: string, end: string): number {
  const a = parseIsoDate(start)
  const b = parseIsoDate(end)
  if (!a || !b) return 0
  return Math.round((b.getTime() - a.getTime()) / 86_400_000) + 1
}

export function isValidTradeDateRange(range: TradeDateRange | null | undefined): boolean {
  if (!range?.[0] || !range?.[1]) return false
  const span = inclusiveDaySpan(range[0], range[1])
  return span >= 1 && span <= MAX_INCLUSIVE_DAYS
}

export function clampTradeDateRange(range: TradeDateRange): TradeDateRange | null {
  const a = parseIsoDate(range[0])
  const b = parseIsoDate(range[1])
  if (!a || !b) return null
  let start = a <= b ? a : b
  let end = a <= b ? b : a
  const span = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1
  if (span > MAX_INCLUSIVE_DAYS) {
    start = new Date(end)
    start.setDate(end.getDate() - (MAX_INCLUSIVE_DAYS - 1))
  }
  return [toIsoDate(start), toIsoDate(end)]
}

export function presetTradeDateRange(
  kind: TradeDatePreset,
  today: Date = new Date(),
  /** 最近交易日 ISO；休市时「今日」落到此日，避免窗口内无交易日。 */
  lastTradingDay?: string | null,
): TradeDateRange {
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate())

  if (kind === 'today') {
    const session = String(lastTradingDay || '').trim().slice(0, 10)
    if (/^\d{4}-\d{2}-\d{2}$/.test(session)) {
      return [session, session]
    }
    const day = toIsoDate(base)
    return [day, day]
  }

  if (kind === 'this_week') {
    const monday = new Date(base)
    monday.setDate(base.getDate() - ((base.getDay() + 6) % 7))
    return [toIsoDate(monday), toIsoDate(base)]
  }

  if (kind === 'last_week') {
    const monday = new Date(base)
    monday.setDate(base.getDate() - ((base.getDay() + 6) % 7) - 7)
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)
    return [toIsoDate(monday), toIsoDate(sunday)]
  }

  if (kind === 'last_30') {
    const start = new Date(base)
    start.setDate(base.getDate() - (MAX_INCLUSIVE_DAYS - 1))
    return [toIsoDate(start), toIsoDate(base)]
  }

  // prev_month
  const firstThis = new Date(base.getFullYear(), base.getMonth(), 1)
  const lastPrev = new Date(firstThis)
  lastPrev.setDate(0)
  const firstPrev = new Date(lastPrev.getFullYear(), lastPrev.getMonth(), 1)
  return [toIsoDate(firstPrev), toIsoDate(lastPrev)]
}

export function rangeLabel(range: TradeDateRange | null | undefined): string {
  if (!range?.[0]) return '最新交易日'
  if (!range[1] || range[0] === range[1]) return range[0]
  return `${range[0]} → ${range[1]}`
}

/** 技能跑仍吃单日：取区间末日（或空=最新） */
export function skillDateFromRange(range: TradeDateRange | null | undefined): string | undefined {
  if (!range?.[1]) return undefined
  return range[1]
}
