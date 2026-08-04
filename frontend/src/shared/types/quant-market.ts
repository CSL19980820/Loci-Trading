/** 行情与能力入口的接口。 */
export interface Capabilities {
  market: boolean
  quotes_sync: boolean
  strategies: boolean
  backtest: boolean
  skills: boolean
  scheduler: boolean
  llm: boolean
  /** 缺失的依赖名，用于在界面上直接告诉用户少装了什么 */
  missing: string[]
}

export interface MarketCoverage {
  rows: number
  codes: number
  first_date: string
  last_date: string
  failed_codes: number
  db_path: string
  db_bytes: number
}

export interface Instrument {
  code: string
  name: string
  market: string
  board: string
  instrument_type: 'STOCK' | 'INDEX'
  list_date: string
  delist_date: string
  status: string
}

export interface Bar {
  trade_date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  amount: number | null
  turnover: number | null
}

export interface QuoteSeries {
  code: string
  name?: string
  market?: string
  board?: string
  /** 中文板块：主板 / 创业板 / 科创板 / 北交所 */
  board_label?: string
  /** 所属行业（半导体 / 电力设备等） */
  industry?: string
  adjust: string
  rows: number
  /** 库内总根数（截断展示时可能大于 rows） */
  total_rows?: number
  bars: Bar[]
}

/** 行情台分页列表行：本机最新日线 + 可选实时。 */
export interface BoardRow {
  code: string
  name: string
  market: string
  board: string
  /** 所属行业（半导体 / 电力设备等） */
  industry: string
  instrument_type: string
  status: string
  local_date: string
  local_close: number | null
  local_pct: number | null
  local_change: number | null
  price: number | null
  pct: number | null
  change: number | null
  open: number | null
  high: number | null
  low: number | null
  prev_close: number | null
  volume: number | null
  amount: number | null
  /** 换手率小数（0.05 = 5%） */
  turnover: number | null
  trade_time: string
  ok: boolean
  source: string
}

export interface MarketBoard {
  total: number
  page: number
  page_size: number
  as_of: string
  live_error: string
  items: BoardRow[]
}
