/**
 * A 股交易日刻度尺的时段推导（纯函数，可单测）。
 *
 * 只用本地时间 + 后端已有的 `session.is_trading_day` 推导，**不新增任何接口**。
 * 节假日日历前端没有真源：`isTradingDay` 传 null 时退化成「周一至周五算交易日」，
 * 这只是兜底，真值应由 `/market/session` 给。
 */

/** 轨道左端：集合竞价开始 09:15 */
export const RULER_START_MIN = 9 * 60 + 15
/** 轨道右端：收盘 15:00 */
export const RULER_END_MIN = 15 * 60
const RULER_SPAN_MIN = RULER_END_MIN - RULER_START_MIN

const OPEN_AUCTION_END = 9 * 60 + 25
const MORNING_START = 9 * 60 + 30
const MORNING_END = 11 * 60 + 30
const AFTERNOON_START = 13 * 60
const CLOSE_AUCTION_START = 14 * 60 + 57

export type SessionPhase =
  | 'pre'
  | 'auction-open'
  | 'pre-open'
  | 'morning'
  | 'lunch'
  | 'afternoon'
  | 'auction-close'
  | 'closed'
  | 'holiday'

/** 轨道分段。`break` 段画成断口（不画轨），不是灰条。 */
export interface RulerSegment {
  id: string
  label: string
  startMin: number
  endMin: number
  kind: 'auction' | 'trade' | 'break'
}

export const RULER_SEGMENTS: readonly RulerSegment[] = [
  {
    id: 'auction-open',
    label: '集合竞价',
    startMin: RULER_START_MIN,
    endMin: OPEN_AUCTION_END,
    kind: 'auction',
  },
  { id: 'pre-open', label: '待开盘', startMin: OPEN_AUCTION_END, endMin: MORNING_START, kind: 'break' },
  { id: 'morning', label: '早盘', startMin: MORNING_START, endMin: MORNING_END, kind: 'trade' },
  { id: 'lunch', label: '午休', startMin: MORNING_END, endMin: AFTERNOON_START, kind: 'break' },
  {
    id: 'afternoon',
    label: '午盘',
    startMin: AFTERNOON_START,
    endMin: CLOSE_AUCTION_START,
    kind: 'trade',
  },
  {
    id: 'auction-close',
    label: '收盘竞价',
    startMin: CLOSE_AUCTION_START,
    endMin: RULER_END_MIN,
    kind: 'auction',
  },
]

export const RULER_TICKS: readonly { min: number; label: string }[] = [
  { min: MORNING_START, label: '09:30' },
  { min: MORNING_END, label: '11:30' },
  { min: AFTERNOON_START, label: '13:00' },
  { min: RULER_END_MIN, label: '15:00' },
]

export interface SessionRulerState {
  phase: SessionPhase
  /** 当前时段名，如「早盘」 */
  phaseLabel: string
  /** 右端整句，如「早盘 · 距午休 42 分」 */
  statusText: string
  /** 刻针位置（0–100）；不在 09:15–15:00 之内时为 null（不画针） */
  markerPct: number | null
  /** 已走完的比例（0–1），用于实心填充 */
  progress: number
  /** 整轨降级为 --rule：非交易日 / 已收盘 */
  dimmed: boolean
  isTradingDay: boolean
  /** 当日分钟数（含小数秒），便于调试与测试 */
  minutes: number
}

/** 当日分钟数（含秒的小数部分）。 */
export function minutesOfDay(now: Date): number {
  return now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60
}

export function isWeekend(now: Date): boolean {
  const day = now.getDay()
  return day === 0 || day === 6
}

/** 分钟锚点 → 轨道百分比（0–100，超界夹紧）。 */
export function pctOfMinute(minute: number): number {
  const ratio = (minute - RULER_START_MIN) / RULER_SPAN_MIN
  return Math.min(100, Math.max(0, ratio * 100))
}

/** 时长口语化：`42 分` / `2 小时 10 分` / `3 天 4 小时`。 */
export function formatGap(minutes: number): string {
  const total = Math.max(0, Math.round(minutes))
  if (total < 1) return '不到 1 分'
  if (total < 60) return `${total} 分`
  if (total < 60 * 24) {
    const hours = Math.floor(total / 60)
    const rest = total % 60
    return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`
  }
  const days = Math.floor(total / (60 * 24))
  // 取整用 floor：round 会把「1 天 23.5 小时」印成「1 天 24 小时」这种废话
  const hours = Math.floor((total % (60 * 24)) / 60)
  return hours ? `${days} 天 ${hours} 小时` : `${days} 天`
}

/**
 * 距下一次开盘（09:30）的分钟数。
 * 今天还没开盘就取今天，否则往后找最近的工作日——节假日日历前端没有，认了。
 */
export function minutesUntilNextOpen(now: Date, isTradingDayToday: boolean): number {
  const minute = minutesOfDay(now)
  if (isTradingDayToday && minute < MORNING_START) return MORNING_START - minute
  const cursor = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  for (let step = 1; step <= 10; step += 1) {
    const next = new Date(cursor)
    next.setDate(cursor.getDate() + step)
    if (isWeekend(next)) continue
  next.setHours(9, 30, 0, 0)
    return (next.getTime() - now.getTime()) / 60000
  }
  return 0
}

function resolvePhase(minute: number): SessionPhase {
  if (minute < RULER_START_MIN) return 'pre'
  if (minute < OPEN_AUCTION_END) return 'auction-open'
  if (minute < MORNING_START) return 'pre-open'
  if (minute < MORNING_END) return 'morning'
  if (minute < AFTERNOON_START) return 'lunch'
  if (minute < CLOSE_AUCTION_START) return 'afternoon'
  if (minute < RULER_END_MIN) return 'auction-close'
  return 'closed'
}

const PHASE_LABEL: Record<SessionPhase, string> = {
  pre: '开盘前',
  'auction-open': '集合竞价',
  'pre-open': '待开盘',
  morning: '早盘',
  lunch: '午休',
  afternoon: '午盘',
  'auction-close': '收盘竞价',
  closed: '已收盘',
  holiday: '休市',
}

export interface SessionRulerInput {
  now: Date
  /** 后端 session.is_trading_day；null/undefined 时按周内工作日兜底 */
  isTradingDay?: boolean | null
}

export function computeSessionRuler(input: SessionRulerInput): SessionRulerState {
  const now = input.now
  const minute = minutesOfDay(now)
  const tradingDay =
    input.isTradingDay == null ? !isWeekend(now) : Boolean(input.isTradingDay)

  if (!tradingDay) {
    return {
      phase: 'holiday',
      phaseLabel: PHASE_LABEL.holiday,
      statusText: `休市 · 距下次开盘 ${formatGap(minutesUntilNextOpen(now, false))}`,
      markerPct: null,
      progress: 0,
      dimmed: true,
      isTradingDay: false,
      minutes: minute,
    }
  }

  const phase = resolvePhase(minute)
  const base = {
    phase,
    phaseLabel: PHASE_LABEL[phase],
    isTradingDay: true,
    minutes: minute,
  }

  if (phase === 'pre') {
    return {
      ...base,
      statusText: `开盘前 · 距集合竞价 ${formatGap(RULER_START_MIN - minute)}`,
      markerPct: null,
      progress: 0,
      dimmed: false,
    }
  }

  if (phase === 'closed') {
    return {
      ...base,
      statusText: `已收盘 · 距下次开盘 ${formatGap(minutesUntilNextOpen(now, true))}`,
      markerPct: null,
      progress: 1,
      dimmed: true,
    }
  }

  const remainText: Record<string, string> = {
    'auction-open': `距开盘 ${formatGap(MORNING_START - minute)}`,
    'pre-open': `距开盘 ${formatGap(MORNING_START - minute)}`,
    morning: `距午休 ${formatGap(MORNING_END - minute)}`,
    lunch: `距午盘 ${formatGap(AFTERNOON_START - minute)}`,
    afternoon: `距收盘 ${formatGap(RULER_END_MIN - minute)}`,
    'auction-close': `距收盘 ${formatGap(RULER_END_MIN - minute)}`,
  }

  return {
    ...base,
    statusText: `${PHASE_LABEL[phase]} · ${remainText[phase]}`,
    markerPct: pctOfMinute(minute),
    progress: (minute - RULER_START_MIN) / RULER_SPAN_MIN,
    dimmed: false,
  }
}

/** 单段的填充比例（0–1）：刻针走过多少算多少。 */
export function segmentFill(segment: RulerSegment, minute: number | null): number {
  if (minute == null) return 0
  if (minute <= segment.startMin) return 0
  if (minute >= segment.endMin) return 1
  return (minute - segment.startMin) / (segment.endMin - segment.startMin)
}
