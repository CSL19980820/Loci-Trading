export type AiSessionStatus = 'idle' | 'running' | 'waiting_user' | 'done' | 'cancelled' | 'error' | 'archived'

export interface AiSessionSummary {
  id: string
  title: string
  updated_at?: string
  status: AiSessionStatus
  provider?: string
  model?: string
}

export interface AiToolReceipt {
  call_id: string
  name: string
  status: 'running' | 'done' | 'error'
  preview?: string
  elapsed_ms?: number
  arguments?: Record<string, unknown>
  risk?: string
  summary?: string
}

/** Artifact kinds from ADR-006 大包 C; qianlong_kline aliases kline. */
export type AiArtifactKind =
  | 'kline'
  | 'qianlong_kline'
  | 'table'
  | 'echarts'
  | 'dual_axis'
  | 'equity_curve'
  | 'candidate_verdict'
  | 'source_strip'
  | 'code'
  | string

export type AiArtifactStatus = 'loading' | 'ready' | 'error'

export interface AiChartArtifact {
  id: string
  kind: AiArtifactKind
  title?: string
  status?: AiArtifactStatus
  data: Record<string, unknown>
}

export interface AiAgentProgress {
  id: string
  name?: string
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled'
  progress?: number
  detail?: string
  timeline?: string[]
  /** 子进程内工具回执（嵌套，对齐 Cursor agent thread） */
  tool_receipts?: AiToolReceipt[]
}

export interface AiHitlQuestion {
  id: string
  prompt: string
  options?: string[]
  allow_free_text?: boolean
}

export interface AiHitlAsk {
  prompt?: string
  options?: string[]
  risk?: string
  /** Cursor askQuestions：多题一次提交；缺省时走旧单题 options */
  questions?: AiHitlQuestion[]
}

export interface AiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at?: string
  status?: 'streaming' | 'done' | 'cancelled' | 'error'
  /** Native provider reasoning; empty when supplier has none. */
  thinking?: string
  /** Optional persisted execution phase; never a substitute for provider reasoning. */
  progress?: { phase: 'queued' | 'preparing' | 'thinking' | 'tools' | 'answering' | 'done' | 'error'; label?: string }
  /** Host-provided model/time caption for embedded conversations. */
  meta?: string
  /** User-attached data URLs (vision). */
  images?: string[]
  tool_receipts?: AiToolReceipt[]
  artifacts?: AiChartArtifact[]
  warnings?: string[]
  /** HITL ask payload when run is waiting_user. */
  hitl?: AiHitlAsk
  /** Folded sub-agents from ADR-006 metadata (completed turns). */
  agents?: AiAgentProgress[]
  /** 最近一次 context_compacted.tokens_after（喂模会话段） */
  context_feed_tokens?: number
}

export interface AiSessionDetail extends AiSessionSummary {
  messages: AiMessage[]
  /** 会话占用中的 run（running / waiting_user）；无则 null */
  active_run?: AiRun | null
}

export interface AiRun {
  id: string
  session_id: string
  status: AiSessionStatus
  provider?: string
  model?: string
  cursor?: string
  /** waiting_user 时后端 result.pending_ask，供刷新后还原 ConfirmCard */
  pending_ask?: AiHitlAsk | null
  input_tokens?: number
  output_tokens?: number
}

export interface AiRunEvent {
  id?: string | number
  type: string
  data: Record<string, unknown>
}

export interface AiRunEventsPage {
  events: AiRunEvent[]
  after?: string
}

export interface AiToolsCatalog {
  provider_configured?: boolean
  providers?: AiProviderProfile[]
  tools: Array<{
    name: string
    description?: string
    risk?: string
    tags?: string[]
    schema_tokens?: number
  }>
  /** 安全底座粗估 token，供上下文用量条 */
  system_prompt_tokens?: number
}

export interface AiProviderModelMeta {
  id: string
  name?: string
  context_window?: number | null
  enabled?: boolean
}

export interface AiProviderProfile {
  name: string
  models: string[]
  model_catalog?: AiProviderModelMeta[]
  default_model?: string
  is_active: boolean
  is_default: boolean
}

export interface AiAssistantProfile {
  about_user: string
  response_style: string
  rules: string[]
  memory_enabled: boolean
  auto_memory_enabled: boolean
  auto_memory_min_turns: number
  updated_at?: string
  memory_usage?: { user: number; memory: number }
}

export interface AiMemoryItem {
  id: string
  target: 'user' | 'memory'
  content: string
  source: 'manual' | 'tool' | 'auto' | 'builtin'
  created_at?: string
  updated_at?: string
}

export interface AiSessionBatchResult {
  ok: string[]
  failed: Array<{ id: string; error: string }>
}
