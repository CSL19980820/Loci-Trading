export interface Candidate {
  id: string
  date: string
  pool_id: string
  code: string
  name: string
  score: number | null
  decision: string
  timing: string
  reason: string
  /** 展示用战法名：内置战法会被后端归一成中文名 */
  rule_version: string
  /** 精确的战法 slug（与 `screen:{slug}` 定时任务同一个键） */
  strategy_slug?: string
  /** `slim` 列表不返回 */
  evidence: Record<string, string>
  source: string
  created_at: string
}

export interface Plan {
  id: string
  date: string
  code: string
  title: string
  status: string
  scenario: string
  entry_zone: string
  stop_price: number | null
  target_price: number | null
  layers: number | null
  invalidation: string
  rule_version: string
  source: string
  supersedes_id: string
  note: string
  created_at: string
}

export interface SummaryCard {
  id: string
  code: string
  name: string
  score: number | null
  decision: string
  timing: string
  reason: string
}

export interface CandidateDaySummary {
  headline: string
  note: string
  text: string
  total: number
  selected_count: number
  filtered_count: number
  all_selected: boolean
  picks: SummaryCard[]
  drops: SummaryCard[]
}

export interface TimelineEvent {
  id: string
  date: string
  created_at: string
  type: 'candidate' | 'plan' | 'review'
  label: string
  detail: Record<string, unknown>
}

export interface ReviewRecord {
  id: string
  date: string
  entity_type: 'plan' | 'candidate' | 'trade' | string
  entity_id: string
  strategy_tag: string
  outcome: string
  return_pct: number | null
  max_favorable_pct: number | null
  max_adverse_pct: number | null
  lesson: string
  next_rule: string
  source: string
  created_at: string
}

export interface PoolDay {
  date: string
  pool_id: string
  total: number
  selected_count: number
  filtered_count: number
  selected: Candidate[]
  filtered: Candidate[]
  all: Candidate[]
  summary: CandidateDaySummary
}
