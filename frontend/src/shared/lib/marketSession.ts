/** 交易时段 / 补数状态（与后端 /market/session 对齐）。 */
export type LiveReason =
  | 'live_window'
  | 'non_trading_day'
  | 'before_open'
  | 'after_close'
  | 'after_close_db_current'
  | 'after_close_db_stale'
  | 'off'
  | string

export interface MarketSession {
  today: string
  now: string
  is_trading_day: boolean
  last_trading_day: string | null
  expected_last_date: string | null
  coverage_first_date: string | null
  coverage_last_date: string | null
  coverage_rows: number
  db_is_current: boolean
  lag_trading_days: number
  needs_backfill: boolean
  backfill_kind: 'empty' | 'catchup' | 'none' | string
  /** 将补区间起点（含）；空库为 null */
  backfill_from: string | null
  /** 将补区间终点 / 目标覆盖日（含） */
  backfill_to: string | null
  live_allowed: boolean
  live_reason: LiveReason
  in_live_clock: boolean
}

/** 本地粗判（API 未就绪时的兜底）：工作日 09:15–15:00。 */
export function isAshareLiveWindow(now = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const mins = now.getHours() * 60 + now.getMinutes()
  return mins >= 9 * 60 + 15 && mins < 15 * 60
}
