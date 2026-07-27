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

// ---- 复盘 ------------------------------------------------------------
// 与回测问的是两个不同问题：回测问"这套战法有没有 alpha"，
// 复盘问"我自己做得怎么样"。

export interface EquityPoint {
  trade_date: string
  holding_value: number
  cash: number
  total_equity: number
  floating_pnl: number
  realized_pnl_cum: number
  drawdown_pct: number
  benchmarks: Record<string, number>
}

export interface EquityCurve {
  points: EquityPoint[]
  metrics: Record<string, number | string | null>
  /** anchored = 有资产快照校准；estimated = 绝对值仅供参考，形状仍可用 */
  confidence: 'anchored' | 'estimated' | 'none'
  note: string
}

export interface RoundTrip {
  code: string
  name: string
  opened_on: string
  closed_on: string | null
  is_open: boolean
  peak_shares: number
  avg_cost: number
  buy_amount: number
  sell_amount: number
  realized_pnl: number
  return_pct: number | null
  hold_days: number | null
  mae_pct: number | null
  mfe_pct: number | null
  event_ids: string[]
}

export interface RoundTripSummary {
  total: number
  closed: number
  open: number
  realized_pnl?: number
  win_rate?: number
  avg_return_pct?: number
  profit_factor?: number | null
  avg_mae_pct?: number
  avg_mfe_pct?: number
  winner_avg_mae_pct?: number
  loser_avg_mae_pct?: number
  profit_give_back_pct?: number
  avg_hold_days?: number
  hint?: string
  caution?: string
  by_code: Record<string, { name: string; count: number; realized_pnl: number }>
  by_month: Record<string, { count: number; realized_pnl: number }>
}

export interface CandidateOutcome {
  candidate_id: string
  code: string
  name: string
  base_date: string
  decision: string
  selected: boolean
  score: number | null
  base_close: number | null
  returns: Record<string, number | null>
  alpha: Record<string, number | null>
  max_favorable_pct: number | null
  note: string
}

export interface CandidateSummary {
  total: number
  evaluated: number
  by_decision: Record<string, Record<string, unknown>>
  selected: Record<string, unknown>
  rejected: Record<string, unknown>
  /** 当初否决、事后大涨的票——改进选股规则最直接的线索 */
  missed_winners: {
    code: string
    name: string
    base_date: string
    decision: string
    return_t20: number | null
    max_favorable_pct: number | null
  }[]
  score_buckets?: { range: string; count: number; avg_t20: number | null; win_rate: number | null }[]
}

export interface PlanOutcome {
  plan_id: string
  code: string
  title: string
  occurred_on: string
  stop_price: number | null
  target_price: number | null
  stop_hit_on: string | null
  target_hit_on: string | null
  status_final: string
  note?: string
}

// ---- 分析任务（异步）-------------------------------------------------
// 横向对比与退出扫描是分钟级的，同步返回会被网关超时掐断，
// 所以走后台任务 + 轮询。

export interface AnalysisStarted {
  job_id: string
  kind: 'compare' | 'optimize'
  status: string
  poll: string
}

// ---- MCP server -----------------------------------------------------

export interface McpServer {
  id: string
  name: string
  url: string
  token_last4: string
  has_token: boolean
  proxy_url: string
  tools: { name: string; description: string }[]
  tools_synced_at: string
  is_active: boolean
  note: string
}

// ---- 策略定时选股配置 ------------------------------------------------

export interface StrategyJobConfig {
  cron: string
  enabled: boolean
  auto_review: boolean
  trading_days: number
  top_n: number
  hold_days: number
  stop_loss_pct: number | null
}

export interface StrategyJob extends Job {
  slug: string
  bound: boolean
}

// ---- 胜率趋势 -------------------------------------------------------

export interface WinRateSummary {
  strategy_tag: string
  total: number
  wins: number
  win_rate: number | null
  avg_return: number | null
  last_reviewed: string
}

export interface WinRateTrendPoint {
  period: string
  strategy_tag: string
  total: number
  wins: number
  win_rate: number | null
}

// ---- 选股历史 -------------------------------------------------------

export interface ScreenCandidate {
  id: string
  date: string
  pool_id: string
  code: string
  name: string
  score: number | null
  decision: string
  timing: string
  reason: string
  rule_version: string
  evidence: Record<string, unknown>
  source: string
  created_at: string
}

export interface ScreenHistory {
  strategy: string
  total: number
  dates: string[]
  by_date: Record<string, ScreenCandidate[]>
}

export interface ScreenTodayResult {
  strategy: string
  trade_date: string
  entry_timing: string
  universe_size: number
  elapsed_seconds: number
  picks: Pick[]
  synced: boolean
  sync_note: string
}

export interface CompareRow {
  label: string
  strategy: string
  hold_days: number
  trades: number
  win_rate: number
  avg_net_return: number
  avg_mfe: number | null
  avg_mae: number | null
  avg_alpha: number | null
  /** MFE 均值 − 净收益均值：持有期内的浮盈最终没拿住多少 */
  give_back: number
  caution?: string
}

export interface CompareResult {
  rows: CompareRow[]
  failures: { label: string; error: string }[]
  range: { start: string | null; end: string | null }
  worst_give_back: CompareRow | null
  hint: string
}

export interface OptimizeRow {
  hold_days: number
  take_profit_pct: number | null
  stop_loss_pct: number | null
  trades: number
  win_rate: number
  avg_net_return: number
  avg_alpha: number | null
  exit_reasons: Record<string, number>
  caution?: string
}

export interface OptimizeResult {
  strategy: string
  rows: OptimizeRow[]
  best: OptimizeRow | null
  baseline: OptimizeRow | null
  improvement: number | null
  /** 参数扫描天生会生产漂亮数字，这句提示必须显示出来 */
  warning: string
  note?: string
}
