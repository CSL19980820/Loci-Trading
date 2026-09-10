/**
 * 股票池（universe）的请求契约与统计回执。选股、回测、试跑、装包四条入口都
 * 传同一份 `UniverseSpec`，所以它不属于其中任何一条，单独一处收口。
 */

import type { BoardBucket } from './enums'

/** 选股股票池：未传时后端默认剔 ST、无北交所 */
export interface UniverseSpec {
  preset?: string | null
  boards?: BoardBucket[] | null
  exclude_st?: boolean | null
  exclude_delisting?: boolean | null
  exclude_suspended?: boolean | null
  min_list_days?: number | null
  codes_include?: string[] | null
  codes_exclude?: string[] | null
  industries_include?: string[] | null
  industries_exclude?: string[] | null
}

export interface UniverseFunnel {
  instruments_total: number
  after_type: number
  after_board: number
  after_st: number
  after_status: number
  after_list_days: number
  after_industry: number
  panel_columns: number
  signals_true: number
  watch_signals_true?: number
}

export interface UniversePreset {
  id: string
  label: string
  boards: BoardBucket[]
  exclude_st: boolean
  exclude_delisting: boolean
  exclude_suspended: boolean
  min_list_days: number | null
}

export interface UniverseStats {
  total: number
  by_board: Record<string, number>
  st_count: number
  selectable_default: number
  bse_blocked: boolean
  as_of: string
}
