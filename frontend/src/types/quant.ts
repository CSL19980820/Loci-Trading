/** 量化能力（行情 / 策略 / 回测 / 技能 / 任务 / 供应商）的类型。
 *
 * 与账本类型分开放：这些能力依赖后端的可选重量级依赖，接口可能整体返回
 * 503。前端要能只凭 Capabilities 就决定隐藏哪些入口，而不是逐个试错。
 */

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
  adjust: string
  rows: number
  bars: Bar[]
}

/** 入场时点：策略自己声明，不是回测参数。 */
export type EntryTiming = 'open' | 'next_open'

export interface StrategyInfo {
  slug: string
  name: string
  description: string
  entry_timing: EntryTiming
  required_fields: string[]
  min_bars: number
  params: Record<string, number | string | boolean>
}

export interface Pick {
  code: string
  open: number | null
  close: number | null
  /** 中间因子。用来回答"为什么它被选中"，没有它就无法归因 */
  factors: Record<string, number | boolean | null>
}

export interface ScreenResult {
  strategy: string
  trade_date: string
  entry_timing: EntryTiming
  universe_size: number
  elapsed_seconds: number
  params: Record<string, unknown>
  picks: Pick[]
}

export interface BacktestMetrics {
  trades: number
  win_rate?: number
  wins?: number
  losses?: number
  avg_gross_return?: number
  avg_net_return?: number
  median_net_return?: number
  best?: number
  worst?: number
  expectancy?: number
  profit_factor?: number | null
  avg_win?: number | null
  avg_loss?: number | null
  avg_mfe?: number
  avg_mae?: number
  avg_hold_days?: number
  exit_reasons?: Record<string, number>
  avg_alpha?: number
  alpha_win_rate?: number
  /** 样本不足 30 笔时后端会带上这句。别把 7 笔交易的均值当结论。 */
  caution?: string
}

export interface BacktestTrade {
  code: string
  signal_date: string
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  hold_days: number
  gross_return_pct: number
  net_return_pct: number
  mae_pct: number
  mfe_pct: number
  exit_reason: string
  benchmark_return_pct: number | null
  alpha_pct: number | null
}

export interface BacktestResult {
  strategy: string
  config: Record<string, unknown>
  metrics: BacktestMetrics
  skipped: Record<string, number>
  trades?: BacktestTrade[]
}

export interface Skill {
  slug: string
  name: string
  version: string
  description: string
  install_path: string
  source_filename: string
  content_sha256: string
  allowed_tools: string[]
  default_cron: string
  metadata: Record<string, unknown>
  enabled: boolean
  installed_at: string
  updated_at: string
  /** 仅详情接口返回，列表接口会省略（正文可能很长） */
  instructions?: string
}

export type JobKind = 'sync' | 'screen' | 'backtest' | 'skill'
export type RunStatus = 'running' | 'success' | 'failed' | 'skipped'

export interface Job {
  id: string
  name: string
  kind: JobKind
  cron: string
  config: Record<string, unknown>
  enabled: boolean
  last_run_at: string
  last_status: string
  created_at: string
  updated_at: string
}

export interface JobRun {
  id: string
  job_id: string
  job_name: string
  kind: string
  trigger: string
  status: RunStatus
  started_at: string
  finished_at: string
  duration_ms: number
  result: Record<string, unknown>
  error_text: string
}

export interface ScheduleStatus {
  running: boolean
  reason?: string
  jobs: { id: string; name: string; next_run_at: string | null }[]
}

export interface LlmProvider {
  id: string
  name: string
  protocol: 'openai_compatible' | 'anthropic'
  base_url: string
  /** 只有末四位。明文与密文都不会经过网络回传。 */
  key_last4: string
  has_key: boolean
  default_model: string
  models: string[]
  models_synced_at: string
  proxy_url: string
  is_active: boolean
  validated_at: string
  note: string
}
