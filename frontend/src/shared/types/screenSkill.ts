/** Screen Skill / 选股 / 回测 相关类型，供 quant.ts re-export。 */

export type BoardBucket = 'main' | 'chi_next' | 'star' | 'bse'
export type EntryTiming = 'open' | 'close' | 'next_open' | 'next_dip'
export type ScreenSkillRuntime = 'formula' | 'python'
export type ScreenSkillDialect = 'loci' | 'tdx' | 'ths' | 'python'
export type ScreenSkillAdjust = 'qfq' | 'hfq' | 'none'
export type ScreenSkillSourceKind = 'formula' | 'python' | 'builtin'
export type ScreenSkillParamType = 'int' | 'float' | 'bool'

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

export interface StrategyInfo {
  slug: string
  name: string
  description: string
  entry_instructions?: string
  entry_timing: EntryTiming
  required_fields: string[]
  min_bars: number
  params: Record<string, number | string | boolean>
  default_universe?: UniverseSpec | null
  source_kind?: ScreenSkillSourceKind
  editable?: boolean
  strategy_revision?: string
  version?: string
  version_history?: StrategyVersion[]
  backtest_metrics?: StrategyBacktestMetrics | null
  backtest_config?: Record<string, unknown> | null
}

/** 可编辑战法的已保存版本快照。 */
export interface StrategyVersion {
  version: string
  id?: string
  status?: string
  created_at?: string
  is_active?: boolean
  backtest_metrics?: StrategyBacktestMetrics | null
  backtest_config?: Record<string, unknown> | null
}

/** 回滚接口只返回恢复后的运行时标识，不返回完整战法详情。 */
export interface StrategyVersionRollbackResult {
  slug: string
  version: string
  file: string
  registered: boolean
}

/** 版本快照来自持久化记录，未执行过回测的字段允许为 null。 */
export interface StrategyBacktestMetrics {
  trades?: number | null
  win_rate?: number | null
  avg_net_return?: number | null
  profit_factor?: number | null
}

export interface ScreenSkillParamDef {
  type: ScreenSkillParamType
  default: number | boolean
  min?: number
  max?: number
  label?: string
}

export interface ScreenSkillLogic {
  id: string
  title: string
  expression: string
  explanation: string
  citations: string[]
}

export interface ScreenSkillReference {
  id: string
  title: string
  kind: string
  url?: string | null
  path?: string | null
  section?: string | null
  quote?: string | null
}

export interface ScreenSkillDataSpec {
  fields: string[]
  adjust: ScreenSkillAdjust
  universe?: UniverseSpec | null
}

export interface ScreenSkillManifest {
  schema_version: number
  entry_timing: EntryTiming
  min_bars: number
  params: Record<string, ScreenSkillParamDef>
  output: {
    signal: string
  }
  factors: string[]
  logic?: ScreenSkillLogic[] | null
  references?: ScreenSkillReference[] | null
  data?: ScreenSkillDataSpec | null
}

export interface ScreenSkillDiagnostic {
  code: string
  severity: 'error' | 'warning' | 'info' | string
  message: string
  line?: number
  column?: number
}

export interface ScreenSkillDerivedInfo {
  required_fields: string[]
  min_bars_required: number
  signal: string
  factors: string[]
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  data?: ScreenSkillDataSpec
}

export interface ScreenSkillCatalogRuntime {
  id: ScreenSkillRuntime
  label: string
  summary: string
  dialects: ScreenSkillDialect[]
}

export interface ScreenSkillCatalogDialect {
  id: ScreenSkillDialect
  runtime: ScreenSkillRuntime
  label: string
  summary: string
}

export interface ScreenSkillCatalogField {
  name: string
  label: string
  summary: string
  source: string
}

export interface ScreenSkillCatalogFunction {
  name: string
  category: string
  signature: string
  summary: string
  description: string
  insert_text: string
  examples: string[]
  dialects: ScreenSkillDialect[]
  source: string
}

export interface ScreenSkillCatalogSnippet {
  id: string
  title: string
  runtime: ScreenSkillRuntime
  dialect: ScreenSkillDialect
  summary: string
  code: string
  required_fields: string[]
  params: Record<string, ScreenSkillParamDef>
  factors: string[]
}

export interface ScreenSkillCatalog {
  runtimes: ScreenSkillCatalogRuntime[]
  dialects: ScreenSkillCatalogDialect[]
  fields: ScreenSkillCatalogField[]
  functions: ScreenSkillCatalogFunction[]
  snippets: ScreenSkillCatalogSnippet[]
}

export interface ScreenSkillExplanationStep {
  id: string
  title: string
  kind: 'signal' | 'factor' | 'intermediate'
  expression: string
  plain_text: string
  line: number | null
  fields: string[]
  functions: string[]
}

export interface ScreenSkillPreviewExplanation {
  mode: 'compiler' | 'manifest'
  summary: string
  steps: ScreenSkillExplanationStep[]
  data_requirements: {
    fields: string[]
    min_bars: number
    adjust: ScreenSkillAdjust
    universe: UniverseSpec | null
  }
  timing: {
    entry_timing: EntryTiming
    plain_text: string
  }
}

export interface ScreenSkillDetail {
  slug: string
  name: string
  description: string
  version?: string
  enabled?: boolean
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  formula?: string
  code?: string
  entrypoint?: string
  manifest: ScreenSkillManifest
  logic?: ScreenSkillLogic[]
  references?: ScreenSkillReference[]
  data?: ScreenSkillDataSpec
  ui?: Record<string, unknown> | null
  package_revision: string
  strategy_revision: string
  updated_at?: string
}

export interface ScreenSkillPreviewRun {
  trade_date?: string
  codes?: string[]
  universe?: UniverseSpec
}

export interface ScreenSkillPreviewResponse {
  ok: boolean
  diagnostics: ScreenSkillDiagnostic[]
  derived?: ScreenSkillDerivedInfo | null
  run_result?: ScreenResult | null
  package_revision?: string
  strategy_revision?: string
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  code?: string
  logic?: ScreenSkillLogic[]
  references?: ScreenSkillReference[]
  data?: ScreenSkillDataSpec
  explanation?: ScreenSkillPreviewExplanation | null
}

export interface ScreenSkillUpsertPayload {
  slug: string
  name: string
  description: string
  version?: string
  enabled?: boolean
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  formula?: string
  code?: string
  entrypoint?: string
  manifest: ScreenSkillManifest
  ui?: Record<string, unknown> | null
}

export interface ScreenSkillGenerateRequest {
  source_type: 'description' | 'tdx' | 'ths' | 'python'
  source: string
  slug?: string
  name?: string
  description?: string
  entry_timing?: EntryTiming
  runtime?: ScreenSkillRuntime
  dialect?: ScreenSkillDialect
  entrypoint?: string
  references?: ScreenSkillReference[]
  provider?: string
  model?: string
  thinking?: string
}

export interface ScreenSkillGenerateResponse {
  ok: boolean
  diagnostics: ScreenSkillDiagnostic[]
  draft?: Partial<ScreenSkillUpsertPayload> | null
  derived?: ScreenSkillDerivedInfo | null
  strategy_revision?: string
}

export interface Pick {
  code: string
  name?: string
  board_bucket?: string
  board_label?: string
  is_st?: boolean
  open: number | null
  close: number | null
  factors: Record<string, number | boolean | null>
}

export interface ScreenRecorded {
  pool_id?: string
  written?: number
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
  picks_total?: number
  picks_truncated?: boolean
  universe?: UniverseSpec
  universe_funnel?: UniverseFunnel
  health?: Record<string, unknown>
  data_snapshot?: MarketDataSnapshot
  recorded?: ScreenRecorded
  range?: ScreenRangeSummary
}

export interface ScreenRunStatus {
  status: 'idle' | 'running' | 'done' | 'error' | string
  phase: string
  percent: number
  message: string
  strategy: string
  trade_date: string
  log: string[]
  result: ScreenResult | null
  error: string
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
  data_end_trades?: number
  avg_alpha?: number
  alpha_win_rate?: number
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
  mode?: 'trade' | 'horizon' | string
  config: Record<string, unknown>
  metrics: BacktestMetrics
  skipped: Record<string, number>
  trades?: BacktestTrade[]
}

/** 极端案例标注（样本最佳/最差那一笔） */
export interface HorizonEventRef {
  code: string
  name?: string
  signal_date: string
  entry_date: string
  mark_date: string
  return_pct: number
  base_close?: number
  mark_high?: number
}

export interface HorizonStats {
  n: number
  win_rate: number
  avg: number
  best: number
  worst: number
  best_event?: HorizonEventRef | null
  worst_event?: HorizonEventRef | null
}

export interface HorizonBacktestResult {
  strategy: string
  mode: 'horizon' | string
  entry_timing: EntryTiming | string
  config: Record<string, unknown>
  horizons: {
    t1?: HorizonStats | null
    t3?: HorizonStats | null
    [key: string]: HorizonStats | null | undefined
  }
  skipped: Record<string, number>
  events?: Array<Record<string, unknown>>
}
