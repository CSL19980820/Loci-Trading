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
  /** YYYY-MM-DD；过期后自动跳过 */
  expires_at?: string
  /** 有 Key、未过期且未停用时为 true */
  is_usable?: boolean
  /** 不可用原因：未配置 Key / 已过期 / 已停用 */
  skip_reason?: string
  /** 当前可调用清单（AI/兼容）；内置会按 lane 启停过滤 */
  tools: McpToolRow[]
  /** 内置 loci-market：完整能力目录（全量 lane 工具 + 上桌 AkShare），仅 UI */
  tools_catalog?: McpToolRow[]
  tools_synced_at: string
  is_active: boolean
  note: string
  /** 进程内置，不写 mcp.json，不可删停 */
  builtin?: boolean
  /** 常驻内置（悟道） */
  resident?: boolean
  hist_daily_primary?: boolean
  quota?: {
    daily_total: number
    daily_structured: number
    daily_skill: number
    per_minute: number
  }
  source?: string
}

export interface McpQuotaSnapshot {
  trade_date: string
  limits: {
    daily_total: number
    structured: number
    skill: number
    per_minute: number
  }
  used: { structured: number; skill: number; total: number }
  remaining: { structured: number; skill: number; total: number }
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

/**
 * 专属战法配置：`screen_*` 是盘后 AI 选股档位，`watch_*` 是盘中信号监测档位。
 * `*_schedule_mode='off'` 表示删除对应任务。SKILL.md 不带时间，全在这里。
 */
export interface SkillStrategyConfig {
  provider?: string
  model?: string
  thinking?: string
  push_wecom?: boolean
  push_watch?: boolean
  watch_use_ai?: boolean
  screen_schedule_mode?: 'off' | 'once' | 'interval' | null
  screen_run_hour?: number
  screen_run_minute?: number
  screen_interval_minutes?: number
  screen_window_start_hour?: number
  screen_window_start_minute?: number
  screen_window_end_hour?: number
  screen_window_end_minute?: number
  watch_schedule_mode?: 'off' | 'once' | 'interval' | null
  watch_run_hour?: number
  watch_run_minute?: number
  watch_interval_minutes?: number
  watch_window_start_hour?: number
  watch_window_start_minute?: number
  watch_window_end_hour?: number
  watch_window_end_minute?: number
  context?: string[]
  context_strategy?: string
  screen_bound?: boolean
  watch_bound?: boolean
  screen_next_runs?: string[]
  watch_next_runs?: string[]
  /** 悟道 MCP 未装配时为 false，盘中监测与预览一并失效 */
  watch_available?: boolean
  watch_unavailable_reason?: string
}

// ---- 战法监测预览 ---------------------------------------------------

/** 龙空龙市场闸门：dragon=进攻窗口，empty=空仓，observe=观察 */
export interface MarketGateSnapshot {
  state?: 'dragon' | 'observe' | 'empty' | string
  mode?: string
  label?: string
  reason?: string
  entry_allowed?: boolean
  data_status?: 'ok' | 'degraded' | string
  score?: number
  trade_date?: string
  quality_warnings?: string[]
  metrics?: Record<string, number | null>
}

/** 龙头地图角色：leader/secondary/follower/weakened/failed */
export interface LeaderMapEntry {
  code: string
  name?: string
  role?: string
  role_label?: string
  role_basis?: string
  theme_name?: string
  ladder_level?: number | null
  gain_20_pct?: number
  drawdown_pct?: number
  close?: number
}

export interface SkillWatchSignal {
  type: string
  code?: string
  reason?: string
  theme?: string
  score?: number
  validation?: string
}

export interface SkillWatchPick {
  code: string
  name?: string
  score?: number
  close?: number
  thesis?: string
  validation?: string
  validation_label?: string
}

/** 每段流水线的启停；关掉的段不会跑，也不消耗配额 */
export interface WatchStages {
  market_gate?: boolean
  auction_confirm?: boolean
  role_history?: boolean
  paper_candidates?: boolean
}

/** 战法监测调参：段启停 + 各档阈值。越界值由后端钳到边界 */
export interface WatchTuning {
  stages: WatchStages
  gate: Record<string, number>
  roles: Record<string, number>
  scan: Record<string, number>
  auction: Record<string, number>
}

/** 字段清单由后端描述，前端照着渲染，避免加了阈值界面漏掉 */
export interface WatchTuningSchema {
  presets?: WatchTuningPreset[]
  stages: Array<{ key: string; label: string; hint: string; default: boolean }>
  sections: Array<{
    name: 'gate' | 'roles' | 'scan' | 'auction' | string
    label: string
    fields: Array<{
      key: string
      label: string
      step: number
      min: number | null
      max: number | null
      default: number
    }>
  }>
}

export interface WatchTuningPreset {
  id: 'aggressive' | 'balanced' | 'defensive' | string
  label: string
  summary: string
}

/** 留痕频率推导的调参建议；只读，不会自动改参 */
export interface WatchTuningSuggestion {
  direction: string
  message: string
}

export interface WatchTuningResponse {
  slug: string
  tuning: WatchTuning
  defaults: WatchTuning
  schema?: WatchTuningSchema
  presets?: WatchTuningPreset[]
}

export interface AuctionStanceRow {
  code: string
  name?: string
  stance?: 'confirmed' | 'downgraded' | 'abandoned' | 'pending' | string
  gap_pct?: number | null
  reason?: string
}

export interface LeaderRoleTransition {
  code: string
  name?: string
  theme_name?: string
  from_role: string
  to_role: string
  from_at?: string
  to_at?: string
  basis?: string
}

/** 从留痕事实推导，不入库：存活天数、转移矩阵、走弱预警提前量 */
export interface LeaderRoleSummary {
  observations?: number
  codes?: number
  trade_days?: number
  role_days?: Record<string, number>
  transition_matrix?: Record<string, number>
  leader_survival?: Array<{
    code: string
    name?: string
    theme_name?: string
    leader_days?: number
    current_role?: string
    still_leader?: boolean
  }>
  warning_lead?: {
    samples?: number
    avg_days?: number | null
    min_days?: number | null
    max_days?: number | null
  }
}

export interface LeaderRoleHistoryResponse {
  slug: string
  history: Array<Record<string, unknown>>
  transitions: LeaderRoleTransition[]
  summary?: LeaderRoleSummary
  suggestions?: WatchTuningSuggestion[]
}

export interface SkillWatchTheme {
  theme_code?: string
  theme_name?: string
  strength?: number | null
  main_net_amount?: number | null
  boom_reason?: string
}

/** `POST /api/skills/{slug}/watch-preview` 的返回；不落库、不推送、不调 LLM */
export interface SkillWatchPreview {
  slug?: string
  engine?: string
  available?: boolean
  skipped?: boolean
  reason?: string
  unavailable_reason?: string
  summary?: string
  trade_date?: string
  validation?: string
  validation_label?: string
  market_gate?: MarketGateSnapshot
  themes?: SkillWatchTheme[]
  leaders?: LeaderMapEntry[]
  weakened?: LeaderMapEntry[]
  entries?: LeaderMapEntry[]
  ranked?: LeaderMapEntry[]
  leader_map?: { leaders?: LeaderMapEntry[]; weakened?: LeaderMapEntry[] }
  signals?: SkillWatchSignal[]
  picks?: SkillWatchPick[]
  pool_size?: number
  tuning?: WatchTuning
  role_transitions?: LeaderRoleTransition[]
  roles_recorded?: number
  suggestions?: WatchTuningSuggestion[]
  auction?: {
    active?: boolean
    reason?: string
    stances?: AuctionStanceRow[]
    abandoned?: string[]
    downgraded?: string[]
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
