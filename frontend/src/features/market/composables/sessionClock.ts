/**
 * A 股交易时段的推导（纯函数，可单测）。
 *
 * 页头只需要一句话：现在处于哪个时段、距下一个节点还有多久（`statusText`）。
 * 只用本地时间 + 后端已有的 `session.is_trading_day` 推导，**不新增任何接口**。
 * 节假日日历前端没有真源：`isTradingDay` 传 null 时退化成「周一至周五算交易日」，
 * 这只是兜底，真值应由 `/market/session` 给。
 */

/** 集合竞价开始 09:15 */
const AUCTION_OPEN_MIN = 9 * 60 + 15
/** 收盘 15:00 */
const CLOSE_MIN = 15 * 60

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

export interface SessionClockState {
  phase: SessionPhase
  /** 当前时段名，如「早盘」；页头徽标直接用它，不再和倒计时重复同一个词 */
  phaseLabel: string
  /** 倒计时本身，如「距午休 42 分」；紧跟徽标后面显示 */
  remainText: string
  /** 整句，如「早盘 · 距午休 42 分」；进 tooltip / 无徽标的场合 */
  statusText: string
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
  if (minute < AUCTION_OPEN_MIN) return 'pre'
  if (minute < OPEN_AUCTION_END) return 'auction-open'
  if (minute < MORNING_START) return 'pre-open'
  if (minute < MORNING_END) return 'morning'
  if (minute < AFTERNOON_START) return 'lunch'
  if (minute < CLOSE_AUCTION_START) return 'afternoon'
  if (minute < CLOSE_MIN) return 'auction-close'
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

export interface SessionClockInput {
  now: Date
  /** 后端 session.is_trading_day；null/undefined 时按周内工作日兜底 */
  isTradingDay?: boolean | null
}

export function computeSessionClock(input: SessionClockInput): SessionClockState {
  const now = input.now
  const minute = minutesOfDay(now)
  const tradingDay =
    input.isTradingDay == null ? !isWeekend(now) : Boolean(input.isTradingDay)

  if (!tradingDay) {
    const remain = `距下次开盘 ${formatGap(minutesUntilNextOpen(now, false))}`
    return {
      phase: 'holiday',
      phaseLabel: PHASE_LABEL.holiday,
      remainText: remain,
      statusText: `${PHASE_LABEL.holiday} · ${remain}`,
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
    const remain = `距集合竞价 ${formatGap(AUCTION_OPEN_MIN - minute)}`
    return {
      ...base,
      remainText: remain,
      statusText: `${PHASE_LABEL.pre} · ${remain}`,
    }
  }

  if (phase === 'closed') {
    const remain = `距下次开盘 ${formatGap(minutesUntilNextOpen(now, true))}`
    return {
      ...base,
      remainText: remain,
      statusText: `${PHASE_LABEL.closed} · ${remain}`,
    }
  }

  const remainByPhase: Record<string, string> = {
    'auction-open': `距开盘 ${formatGap(MORNING_START - minute)}`,
    'pre-open': `距开盘 ${formatGap(MORNING_START - minute)}`,
    morning: `距午休 ${formatGap(MORNING_END - minute)}`,
    lunch: `距午盘 ${formatGap(AFTERNOON_START - minute)}`,
    afternoon: `距收盘 ${formatGap(CLOSE_MIN - minute)}`,
    'auction-close': `距收盘 ${formatGap(CLOSE_MIN - minute)}`,
  }

  const remain = remainByPhase[phase]
  return { ...base, remainText: remain, statusText: `${PHASE_LABEL[phase]} · ${remain}` }
}
