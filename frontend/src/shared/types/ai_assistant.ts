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
  status: 'running' | 'done' | 'error' | 'awaiting_confirmation'
  preview?: string
  elapsed_ms?: number
  arguments?: Record<string, unknown>
  risk?: string
  summary?: string
}

export interface AiChartArtifact {
  id: string
  kind: 'qianlong_kline' | 'candidate_verdict'
  title?: string
  data: Record<string, unknown>
}

export interface AiAgentProgress {
  id: string
  name?: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress?: number
  detail?: string
  timeline?: string[]
}

export interface AiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at?: string
  status?: 'streaming' | 'done' | 'cancelled' | 'error'
  thinking?: string
  tool_receipts?: AiToolReceipt[]
  artifacts?: AiChartArtifact[]
  warnings?: string[]
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
  tools: Array<{ name: string; description?: string; risk?: string; tags?: string[] }>
}

export interface AiProviderProfile {
  name: string
  models: string[]
  default_model?: string
  is_active: boolean
  is_default: boolean
}
