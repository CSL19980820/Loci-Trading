export interface Skill {
  slug: string
  name: string
  version: string
  description: string
  install_path: string
  source_filename: string
  content_sha256: string
  allowed_tools: string[]
  metadata: Record<string, unknown>
  enabled: boolean
  installed_at?: string
  updated_at?: string
  mcp_servers?: string[]
  tool_specs?: Array<Record<string, unknown>>
  agents?: Array<Record<string, unknown>>
  isolation?: string
  policy?: string
  /** 仅详情接口返回，列表接口会省略（正文可能很长） */
  instructions?: string
}

export type JobKind =
  | 'sync'
  | 'screen'
  | 'backtest'
  | 'compare'
  | 'optimize'
  | 'prune'
  | 'skill'
  | 'notify'
  | 'outcome'
  | 'hot_rebuild'
  | 'data_quality'
  | 'intel_fetch'
  | 'intel_brief'
  | 'skill_watch'
  | 'alert_scan'
  | 'strategy_monitor'
  | 'paper_eod'
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

/**
 * 自建定时任务额度（`GET /api/jobs/quota`）。
 *
 * `used` 只数用户自建的；`managed` 是系统托管任务（选股 / 情报 / 候选跟踪等），
 * **不占额度**——不把它报出来，用户看到「上限 5」却在列表里数出 12 条，
 * 只会以为额度算错了。`unlimited`（= limit < 0）是管理员账号。
 */
export interface JobQuota {
  used: number
  limit: number
  unlimited: boolean
  managed: number
}

export interface WecomSettings {
  configured: boolean
  url_masked: string
  screen_template?: WecomScreenTemplate
  preview?: string
}

export type WecomScreenPreset = 'default' | 'compact' | 'with_date' | 'custom'

export interface WecomScreenTemplate {
  preset: WecomScreenPreset
  header: string
  intro: string
  pick: string
  pick_no_pct: string
  skill_pick: string
  skill_pick_no_pct: string
  empty: string
  formal_empty: string
  watch_header: string
  watch_pick: string
  watch_pick_no_pct: string
  more: string
  quant_tag: string
  skills_tag: string
  max_picks: number
}

export interface MarketSyncSettings {
  enabled_intraday: boolean
  interval_minutes: number
  enabled_eod: boolean
  eod_hour: number
  eod_minute: number
  workers: number
  push_wecom_on_fail: boolean
  intraday_job?: Job & { next_run_at?: string | null }
  eod_job?: Job & { next_run_at?: string | null }
}

/** 数据线路：一类数据需求（历史日 K / 实时快照 / …），不是供应商名。 */
export interface DataLane {
  id: string
  label: string
  required: boolean
}

/** 可接入 API（适配器）目录项。 */
export interface LaneProvider {
  id: string
  label: string
  lanes: string[]
  description?: string
  /** 源总开关；关掉等于这家所有工具都不可用 */
  enabled?: boolean
  /** 被单独关掉的工具（lane）；源总开关仍可能是开的 */
  disabled_lanes?: string[]
  /** 数据来源站点，仅供人核对出处，不是我们直接请求的地址 */
  base_url?: string
  /** adapter=行情适配器；mcp=外部情报 MCP（启停走运维 MCP 页） */
  kind?: 'adapter' | 'mcp'
  mcp_name?: string
  expires_at?: string
  has_token?: boolean
}

export type LanePolicyMode = 'auto' | 'manual'

/** 一条数据线路的选择策略。effective_provider_ids 只读，由后端计算。 */
export interface LanePolicy {
  lane: string
  mode: LanePolicyMode
  provider_id?: string | null
  fallback: boolean
  effective_provider_ids: string[]
}

export interface LanePolicyPayload {
  mode: LanePolicyMode
  provider_id?: string | null
  fallback: boolean
}

export interface LanesSummary {
  ok: number
  degraded: number
  down: number
}

export interface LanesCatalog {
  lanes: DataLane[]
  providers: LaneProvider[]
  policies?: LanePolicy[]
  summary?: LanesSummary
}

/** 单次类目探测结果（连通 + 小样本 RTT）。 */
export interface LaneProbeResult {
  adapter_id: string
  lane: string
  ok: boolean
  rtt_ms: number
  rows?: number | null
  error?: string | null
  unsupported?: boolean
  /** API 层可补中文名；缺省时前端用目录 label */
  label?: string
  missing_fields?: string[]
  extra?: Record<string, unknown>
}

export interface LaneProbeResponse {
  results?: LaneProbeResult[]
  rounds?: LaneProbeRound[]
  median_rtt_ms?: number | null
}

/** 新版探测返回每轮；旧版仅有 results，前端同时兼容两种形态。 */
export interface LaneProbeRound {
  provider_id?: string
  adapter_id?: string
  label?: string
  lane?: string
  run: number
  ok: boolean
  rtt_ms?: number | null
  elapsed_ms?: number | null
  rows?: number | null
  error?: string | null
}

/** hist_daily 全量拉取比速的一行。 */
export interface LaneSpeedTestResult {
  adapter_id: string
  code: string
  ok: boolean
  elapsed_ms: number
  rows: number
  bytes_est?: number
  mb_per_s: number
  error?: string | null
  label?: string
  missing_fields?: string[]
  extra?: Record<string, unknown>
}

export interface LaneSpeedTestResponse {
  lane?: string
  code?: string
  results?: LaneSpeedTestResult[]
  rounds?: LaneProbeRound[]
  median_rtt_ms?: number | null
}
