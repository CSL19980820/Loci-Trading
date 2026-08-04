import type { Pick, ScreenRecorded, UniverseSpec } from '@/shared/types/screenSkill'

import type { Job } from './quant-ops'

// ---- MCP server -----------------------------------------------------

export interface McpToolRow {
  name: string
  description: string
  input_schema?: Record<string, unknown>
  /** UI 目录分组：lane=内置行情 · akshare=已上桌 AkShare */
  group?: 'lane' | 'akshare' | string
  /** false=线路无源，详情仍展示但标为不可用 */
  available?: boolean
}

export interface McpServer {
  id: string
  name: string
  url: string
  token_last4: string
  has_token: boolean
  /** 当前可调用清单（AI/兼容）；内置会按 lane 启停过滤 */
  tools: McpToolRow[]
  /** 内置 loci-market：完整能力目录（全量 lane 工具 + 上桌 AkShare），仅 UI */
  tools_catalog?: McpToolRow[]
  tools_synced_at: string
  is_active: boolean
  note: string
  /** 进程内置，不写 mcp.json，不可删停 */
  builtin?: boolean
  source?: string
}

// ---- 策略定时选股配置 ------------------------------------------------

export interface StrategyJobSchedule {
  mode: 'off' | 'once' | 'interval'
  run_hour: number
  run_minute: number
  interval_minutes: number
  window_start_hour: number
  window_start_minute: number
  window_end_hour: number
  window_end_minute: number
}

export interface StrategyJobConfig {
  cron?: string
  enabled?: boolean
  auto_review?: boolean
  push_wecom?: boolean
  trading_days?: number
  top_n?: number
  hold_days?: number
  stop_loss_pct?: number | null
  provider?: string
  model?: string
  thinking?: string
  use_ai_pick?: boolean
  universe?: UniverseSpec | null
  schedule_mode?: 'off' | 'once' | 'interval' | null
  run_hour?: number
  run_minute?: number
  interval_minutes?: number
  window_start_hour?: number
  window_start_minute?: number
  window_end_hour?: number
  window_end_minute?: number
}

export interface StrategyJob extends Omit<Job, 'config'> {
  slug: string
  bound: boolean
  next_runs?: string[]
  config?: Record<string, unknown> & {
    universe?: UniverseSpec
    schedule?: StrategyJobSchedule
    record_candidates?: boolean
    top_n?: number
    push_wecom?: boolean
  }
}

export interface SkillJobConfig {
  cron?: string
  enabled?: boolean
  push_wecom?: boolean
  provider?: string
  model?: string
  thinking?: string
  context?: string[]
  context_strategy?: string
  schedule_mode?: 'off' | 'once' | 'interval' | null
  run_hour?: number
  run_minute?: number
  interval_minutes?: number
  window_start_hour?: number
  window_start_minute?: number
  window_end_hour?: number
  window_end_minute?: number
}

export interface SkillJob extends Omit<Job, 'config'> {
  slug: string
  bound: boolean
  next_runs?: string[]
  config?: Record<string, unknown> & {
    skill?: string
    provider?: string
    push_wecom?: boolean
    schedule?: StrategyJobSchedule
    context?: string[]
    context_strategy?: string
  }
}

// ---- 胜率趋势 -------------------------------------------------------

export interface WinRateSummary {
  strategy_tag: string
  total: number
  wins: number
  win_rate: number | null
  avg_return: number | null
  last_reviewed: string
  /** candidates=精选候选 T+N；reviews=手工复盘兜底 */
  source?: 'candidates' | 'reviews' | string
  horizons?: Record<
    string,
    { n: number; avg: number; win_rate: number; best?: number; worst?: number }
  >
  observing?: number
  sample_all?: number
  primary_horizon?: number
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
  recorded?: ScreenRecorded
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
