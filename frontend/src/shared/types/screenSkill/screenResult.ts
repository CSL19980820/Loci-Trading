/**
 * 一次选股跑完的结果：命中/观察名单、股票池漏斗、数据快照、入库回执，以及区间
 * 批跑的逐日汇总。试跑、正式选股、区间回补三条路径回的是同一个 `ScreenResult`，
 * 所以它不能挂在任一条入口的类型文件下。
 */

import type { EntryTiming, ScreenSkillAdjust } from './enums'
import type { UniverseFunnel, UniverseSpec } from './universe'

export interface Pick {
  code: string
  name?: string
  board_bucket?: string
  board_label?: string
  is_st?: boolean
  open: number | null
  close: number | null
  pct_chg?: number | null
  intent?: 'observe' | string
  factors: Record<string, number | boolean | null>
}

export interface ScreenRecorded {
  pool_id?: string
  written?: number
  formal_written?: number
  watch_written?: number
  failed?: { code: string; error: string }[]
  trade_date?: string
  written_total?: number
  days?: number
}

export interface MarketTimeSeriesSnapshot {
  rows: number
  last_date: string
  fetched_at: string
  content_digest?: string
}

export interface MarketInstrumentSnapshot {
  rows: number
  updated_at: string
  content_digest: string
}

export interface MarketDataSnapshot {
  fields: string[]
  adjust: ScreenSkillAdjust
  start?: string
  end?: string
  schema_version?: number
  rows?: number
  last_date?: string
  fetched_at?: string
  quotes?: MarketTimeSeriesSnapshot
  adjust_factors?: MarketTimeSeriesSnapshot
  instruments?: MarketInstrumentSnapshot
  market_revision?: string
}

export interface ScreenRangeDay {
  trade_date: string
  picks: number
  watch_picks?: number
  universe_size: number
  elapsed_seconds: number
  recorded?: ScreenRecorded | null
}

export interface ScreenRangeSummary {
  start: string
  end: string
  trading_days: number
  days: ScreenRangeDay[]
  written_total: number
}

export interface ScreenResult {
  strategy: string
  strategy_revision: string
  trade_date: string
  entry_timing: EntryTiming
  universe_size: number
  elapsed_seconds: number
  params: Record<string, unknown>
  effective_params: Record<string, unknown>
  picks: Pick[]
  watch_picks: Pick[]
  picks_total?: number
  picks_truncated?: boolean
  watch_picks_total?: number
  watch_picks_truncated?: boolean
  universe?: UniverseSpec
  universe_funnel?: UniverseFunnel
  health?: Record<string, unknown>
  data_snapshot?: MarketDataSnapshot
  recorded?: ScreenRecorded
  range?: ScreenRangeSummary
}
