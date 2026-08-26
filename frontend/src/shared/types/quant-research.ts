export type ResearchQuality = 'full' | 'partial' | 'missing' | 'error'
export type ResearchBudget = 'lite' | 'standard' | 'deep'
export type ResearchSourceState = 'registered' | 'probed' | 'selected' | 'failed' | 'not_probed'

export interface ResearchDimensionSpec {
  key: string
  name: string
  group: string
  summary: string
  expected_fields: string[]
  candidate_sources: string[]
  availability: 'local' | 'partial' | 'pending'
  historical_safe: boolean
  dependencies: string[]
}

export interface ResearchSource {
  id: string
  name_cn: string
  base_url: string
  markets: string[]
  dims: string[]
  tier: string
  access: string
  health: string
  notes: string
}

export interface ResearchBudgetSpec {
  id: ResearchBudget
  label: string
  max_bars: number
  external_fetch: boolean
}

export interface ResearchCatalog {
  version: string
  dimensions: ResearchDimensionSpec[]
  sources: ResearchSource[]
  market_adapters: Record<string, unknown>[]
  quality_values: ResearchQuality[]
  budgets: ResearchBudgetSpec[]
  guardrails: {
    production_signal: boolean
    static_scores_are_not_facts: boolean
    missing_data_stays_missing: boolean
    market_health_gate: boolean
  }
}

export interface ResearchEvidence {
  source_id: string
  source_url: string
  title: string
  observed_at: string
  as_of: string
  payload_sha256: string
  quote: string
}

export interface ResearchDimensionResult {
  key: string
  name: string
  quality: ResearchQuality
  source: string
  retrieved_at: string
  as_of: string
  data_gaps: string[]
  values: Record<string, unknown>
  evidence: ResearchEvidence[]
  error: string
}

export interface ResearchReviewIssue {
  severity: 'critical' | 'warning' | 'info'
  code: string
  message: string
  dimension: string
  evidence: string[]
  suggested_fix: string
  rule_version: string
}

export interface ResearchQualitySnapshot {
  overall: ResearchQuality
  blocked: boolean
  completeness_ratio: number
  market_revision: string
  generated_at: string
  findings: ResearchReviewIssue[]
  market_health: Record<string, unknown>
}

export interface ResearchSourceAttempt {
  source_id: string
  state: ResearchSourceState
  checked_at: string
  rtt_ms: number | null
  row_sources: string[]
  fields: string[]
  error: string
  /** 仅在后端有真实 receipt/attempt 时才可标为已观测。 */
  observed?: boolean
  attempts_not_observed?: boolean
  fallback_used?: boolean
  unresolved?: boolean
}

export interface ResearchProfile {
  code: string
  subject: Record<string, unknown>
  budget: ResearchBudget
  generated_at: string
  market_snapshot: Record<string, unknown>
  dimensions: ResearchDimensionResult[]
  quality: ResearchQualitySnapshot
  requested_as_of: string
  source_attempts: ResearchSourceAttempt[]
  artifact_id: string
  artifact_status: 'transient' | 'archived' | 'stale'
  contract: {
    quality_values: ResearchQuality[]
    evidence_required: boolean
    production_signal: boolean
  }
}

export interface ResearchRunStage {
  status: 'completed'
  output_sha256: string
  depends_on: string[]
}

export interface ResearchRun {
  id: string
  contract_version: string
  status: 'running' | 'completed' | 'stale' | 'error'
  code: string
  budget: ResearchBudget
  requested_as_of: string
  created_at: string
  updated_at: string
  input_sha256: string
  market_revision: string
  as_of: string
  stages: Record<string, ResearchRunStage>
  source_attempts?: ResearchSourceAttempt[]
  error: string
  reused?: boolean
  stale?: boolean
}

export interface ResearchRunResult {
  run: ResearchRun
  profile: ResearchProfile
}

export type ResearchBacktestRunStatus = 'running' | 'awaiting_human_review' | 'completed' | 'stale' | 'failed' | 'rejected'
export type ResearchWorkflowStageStatus = 'pending' | 'waiting' | 'running' | 'completed' | 'failed' | 'blocked'
export type ResearchHypothesisStatus = 'exploring' | 'testing' | 'validated' | 'rejected' | 'monitoring'

export interface ResearchArtifactManifestEntry {
  path: string
  sha256: string
  created_at: string
  size_bytes: number | null
  artifact_type: string
  metadata: Record<string, unknown>
}

export interface ResearchBacktestRun {
  contract_version: string
  run_id: string
  strategy_slug: string
  strategy_revision: string
  version: string
  hypothesis_id: string | null
  hypothesis_revision: number | null
  requested_as_of: string
  actual_as_of: string
  market_revision: string
  universe: Record<string, unknown>
  universe_funnel: Record<string, unknown>
  params: Record<string, unknown>
  backtest_config: Record<string, unknown>
  data_snapshot: Record<string, unknown>
  source_evidence: Record<string, unknown>[]
  metrics: Record<string, unknown>
  validation: Record<string, unknown>
  risk_xray: Record<string, unknown>
  conclusion: unknown
  artifact_manifest: ResearchArtifactManifestEntry[]
  status: ResearchBacktestRunStatus
  created_at: string
  updated_at: string
  input_sha256: string
  /** 后端对当前 artifact manifest 计算的规范摘要，人工签署必须原样回传。 */
  artifact_manifest_sha256: string
  /** 保留后端兼容字段；新代码优先使用 artifact_manifest_sha256。 */
  manifest_sha256: string
  error: string
}

export interface ResearchBacktestPublicationPayload {
  manifest_sha256: string
  reviewer: string
  reason: string
}

export interface ResearchWorkflowStage {
  status: ResearchWorkflowStageStatus
  attempts: number
  error: string
  failure_code: string
  blocked_by: string[]
  artifact_sha256: string
}

export interface ResearchWorkflowEvent {
  action: string
  occurred_at: string
  stage: string
  detail: string
  attempt: number
}

export interface ResearchWorkflow {
  contract_version: string
  workflow_id: string
  run_id: string
  max_retries: number
  status: 'waiting' | 'running' | 'awaiting_human_review' | 'completed' | 'failed'
  stages: Record<string, ResearchWorkflowStage>
  events: ResearchWorkflowEvent[]
}

export interface ResearchBacktestPublicationResult {
  run_card: ResearchBacktestRun
  workflow: ResearchWorkflow
  reused: boolean
}

/** 人工否决与人工签署使用相同的服务端 manifest 绑定请求。 */
export type ResearchBacktestRejectionPayload = ResearchBacktestPublicationPayload
export type ResearchBacktestRejectionResult = ResearchBacktestPublicationResult

/** 历史股票池在某一时点可见的成员快照。 */
export interface ResearchMembershipSnapshot {
  universe_id: string
  as_of: string
  available_at: string
  members: string[]
  source_id: string
  source_url: string
  snapshot_revision: string
  fetched_at: string
  payload_sha256: string
  parser_revision: string
  pit_membership: boolean
  survivorship_bias: boolean
  degraded: boolean
  missing_reason: string
}

export interface ResearchMembershipSnapshotPayload {
  universe_id: string
  as_of: string
  available_at: string
  members: string[]
  source_id: string
  source_url: string
  snapshot_revision: string
  fetched_at: string
  payload_sha256: string
  parser_revision: string
  pit_membership?: boolean
  survivorship_bias?: boolean
  degraded?: boolean
  missing_reason?: string
}

export interface ResearchMembershipSnapshotList {
  items: ResearchMembershipSnapshot[]
  total: number
  /** 指定 universe_id 与 as_of 时，后端选择的最近历史快照或明确降级结果。 */
  resolved?: ResearchMembershipSnapshot
}

export interface ResearchMembershipSnapshotImportPayload {
  snapshots: ResearchMembershipSnapshotPayload[]
}

/** 一条带可见日期的财务、事件或其他外部事实。 */
export interface ResearchPointInTimeFact {
  observation_id: string
  entity_id: string
  observed_on: string
  available_at: string
  values: Record<string, unknown>
  source_id: string
  source_url: string
  published_at: string
  revision: string
  fetched_at: string
  payload_sha256: string
  parser_revision: string
  restated: boolean
  fact_type: 'financial' | 'event' | 'other'
}

export interface ResearchPointInTimeFactPayload {
  observation_id: string
  entity_id: string
  observed_on: string
  available_at: string
  values?: Record<string, unknown>
  source_id: string
  source_url: string
  published_at?: string
  revision: string
  fetched_at: string
  payload_sha256: string
  parser_revision: string
  restated?: boolean
  fact_type?: 'financial' | 'event' | 'other'
}

export interface ResearchPointInTimeFactList {
  items: ResearchPointInTimeFact[]
  total: number
  /** 指定 entity_id 与 as_of 时，后端按可见日期选择的事实。 */
  selected?: ResearchPointInTimeFact | null
}

export interface ResearchPointInTimeFactImportPayload {
  facts: ResearchPointInTimeFactPayload[]
}

export interface ResearchEvidenceLink {
  run_id: string
  artifact_sha256: string
  summary: string
  observed_metrics: Record<string, number>
  as_of: string
}

export interface ResearchHypothesisMetric {
  name: string
  operator: '>=' | '>' | '<=' | '<' | '=='
  threshold: number
}

export interface ResearchHypothesis {
  contract_version: string
  hypothesis_id: string
  title: string
  thesis: string
  strategy_revision: string
  metrics: ResearchHypothesisMetric[]
  failure_conditions: string[]
  status: ResearchHypothesisStatus
  run_ids: string[]
  evidence_links: ResearchEvidenceLink[]
  audit_log: Array<{
    action: string
    actor: string
    occurred_at: string
    reason: string
    from_status: string
    to_status: string
    evidence_run_ids: string[]
  }>
  revision: number
  created_at: string
  updated_at: string
}

export interface CreateResearchBacktestRunPayload {
  strategy: string
  start: string
  end: string
  params?: Record<string, unknown>
  /** 后端允许的显式股票池限定；严格 PIT 仍以 historical_universe_id 为准。 */
  universe?: Record<string, unknown>
  split?: {
    train_start: string
    train_end: string
    oos_start: string
    oos_end: string
  }
  backtest_config?: {
    hold_days?: number
    stop_loss_pct?: number | null
    take_profit_pct?: number | null
    commission_bps?: number
    stamp_duty_bps?: number
    slippage_bps?: number
    allow_limit_up_entry?: boolean
    benchmark?: string | null
  }
  hypothesis_id?: string
  hypothesis_revision?: number
  initial_capital?: number
  max_positions?: number
  lot_size?: number
  seed?: number
  random_repeats?: number
  bootstrap_iterations?: number
  monte_carlo_iterations?: number
  historical_universe_id?: string
  strict_pit?: boolean
}

export interface ResearchReplayComparison {
  contract_version: string
  run_id: string
  source_manifest_sha256: string
  input_sha256: string
  matches_card_metrics: boolean
  execution_matches: {
    main: boolean
    control: boolean
    train: boolean
    oos: boolean
  }
  matches_all_recomputed_execution: boolean
}

export interface ResearchReplayResult {
  run_card: ResearchBacktestRun
  workflow: ResearchWorkflow
  comparison: ResearchReplayComparison
  receipt: ResearchArtifactManifestEntry
}

export interface Pth252FactorSplit {
  train_start: string
  train_end: string
  oos_start: string
  oos_end: string
}

export interface CreatePth252FactorJobPayload {
  factor_id: 'pth252'
  start: string
  end: string
  split: Pth252FactorSplit
  top_quantile: 0.9
  rebalance_every: 20
  backtest_config: {
    hold_days: 20
    stop_loss_pct: null
    take_profit_pct: null
    commission_bps: 3
    stamp_duty_bps: 10
    slippage_bps: 5
    allow_limit_up_entry: false
    benchmark: '000300'
  }
  initial_capital: 200000
  max_positions: 20
  strict_pit: true
  historical_universe_id: string
}

export interface ResearchBacktestJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  request: Record<string, unknown>
  run_id: string
  error: string
  created_at: string
  updated_at: string
}

export interface CreateResearchHypothesisPayload {
  hypothesis_id: string
  title: string
  thesis: string
  strategy_revision: string
  metrics: ResearchHypothesisMetric[]
  failure_conditions: string[]
  actor: string
}

export interface ResearchHypothesisReviewPayload {
  decision: Extract<ResearchHypothesisStatus, 'validated' | 'rejected'>
  actor: string
  reason: string
  evidence: ResearchEvidenceLink[]
  expected_revision: number
}

export interface ResearchHypothesisTransitionPayload {
  target: Exclude<ResearchHypothesisStatus, 'exploring'>
  actor: string
  reason: string
  evidence: ResearchEvidenceLink[]
  expected_revision: number
}
