import type {
  Analytics,
  Candidate,
  Dashboard,
  PoolDay,
  PoolSummary,
  ReviewRecord,
  TimelineEvent,
  TradePayload,
  TradeRecord,
} from '@/shared/types/palace'

const API_ROOT = '/api'
const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504])
const MAX_GET_RETRIES = 2

export interface SessionStatus {
  authenticated: boolean
  username: string
}

export type TodayAlertStatus =
  | 'stop_hit'
  | 'target_hit'
  | 'near_stop'
  | 'near_target'
  | 'ok'
  | 'no_quote'

export interface TodayAlert {
  code: string
  name: string
  plan_id: string
  title: string
  stop_price: number | null
  target_price: number | null
  last_close: number | null
  status: TodayAlertStatus
  note: string
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function requestOnce<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  // FormData 必须让浏览器自己设 Content-Type——它要在里面带 multipart
  // 的 boundary，手工设会让后端解析不出文件。
  const isFormData = init?.body instanceof FormData
  if (!headers.has('Content-Type') && init?.body && !isFormData) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `请求失败（${response.status}）`
    const error = new Error(detail) as Error & { status?: number; retryable?: boolean }
    error.status = response.status
    error.retryable = RETRYABLE_STATUS.has(response.status)
    throw error
  }
  return response.json() as Promise<T>
}

/** 读接口遇 5xx/繁忙时自动退避重试；写接口不重试，避免重复记账。 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const canRetry = method === 'GET' || method === 'HEAD'
  let attempt = 0
  for (;;) {
    try {
      return await requestOnce<T>(path, init)
    } catch (caught: unknown) {
      const err = caught as Error & { retryable?: boolean }
      const retryable = Boolean(err.retryable) || (caught instanceof TypeError)
      if (!canRetry || !retryable || attempt >= MAX_GET_RETRIES) throw caught
      attempt += 1
      await sleep(200 * attempt)
    }
  }
}

export function getDashboard(date?: string): Promise<Dashboard> {
  const query = date ? `?date=${encodeURIComponent(date)}` : ''
  return request<Dashboard>(`/dashboard${query}`)
}

export function getTodayAlerts(): Promise<TodayAlert[]> {
  return request<TodayAlert[]>('/alerts/today')
}

async function downloadExport(path: string, filename: string): Promise<void> {
  const response = await fetch(`${API_ROOT}${path}`, { credentials: 'same-origin' })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `导出失败（${response.status}）`
    throw new Error(detail)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function exportTradesCsv(code?: string): Promise<void> {
  const params = new URLSearchParams()
  if (code) params.set('code', code)
  const query = params.toString()
  return downloadExport(`/trades/export.csv${query ? `?${query}` : ''}`, 'trades.csv')
}

export function exportCandidatesCsv(
  options: {
    strategy?: string
    decision?: string
    start?: string
    end?: string
    limit?: number
  } = {},
): Promise<void> {
  const params = new URLSearchParams()
  if (options.strategy) params.set('strategy', options.strategy)
  if (options.decision) params.set('decision', options.decision)
  if (options.start) params.set('start', options.start)
  if (options.end) params.set('end', options.end)
  if (options.limit) params.set('limit', String(options.limit))
  const query = params.toString()
  return downloadExport(`/candidates/export.csv${query ? `?${query}` : ''}`, 'candidates.csv')
}

export interface QianlongImportPreviewHolding {
  code: string
  name: string
  shares: number
  cost: number
  note: string
}

export interface QianlongImportPreview {
  can_import: boolean
  block_reason: string
  date: string
  holdings_count: number
  holdings: QianlongImportPreviewHolding[]
  realized_pnl_baseline: number
  total_assets: number | null
}

export interface QianlongImportResult {
  date: string
  position_events: string[]
  realized_pnl_baseline: number
  total_assets: number | null
}

function qianlongImportFormData(file: File): FormData {
  const form = new FormData()
  form.append('file', file)
  return form
}

export function previewQianlongImport(file: File): Promise<QianlongImportPreview> {
  return request<QianlongImportPreview>('/import/qianlong/preview', {
    method: 'POST',
    body: qianlongImportFormData(file),
  })
}

export function confirmQianlongImport(file: File): Promise<QianlongImportResult> {
  return request<QianlongImportResult>('/import/qianlong/confirm', {
    method: 'POST',
    body: qianlongImportFormData(file),
  })
}

export function getTimeline(code: string): Promise<TimelineEvent[]> {
  return request<TimelineEvent[]>(`/timeline/${encodeURIComponent(code)}`)
}

export function getTrades(code?: string, limit = 200): Promise<TradeRecord[]> {
  const params = new URLSearchParams()
  if (code) params.set('code', code)
  if (limit !== 200) params.set('limit', String(limit))
  const query = params.toString()
  return request<TradeRecord[]>(`/trades${query ? `?${query}` : ''}`)
}

export function getReviews(limit = 100): Promise<ReviewRecord[]> {
  const query = limit === 100 ? '' : `?limit=${limit}`
  return request<ReviewRecord[]>(`/reviews${query}`)
}

export function getPools(): Promise<PoolSummary[]> {
  return request<PoolSummary[]>('/pools')
}

export function getPoolDay(date?: string, poolId?: string): Promise<PoolDay> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (poolId) params.set('pool_id', poolId)
  const query = params.toString()
  return request<PoolDay>(`/pools/day${query ? `?${query}` : ''}`)
}

export function getAnalytics(): Promise<Analytics> {
  return request<Analytics>('/analytics')
}

export function createTrade(payload: TradePayload): Promise<{ id: string }> {
  return request<{ id: string }>('/trades', { method: 'POST', body: JSON.stringify(payload) })
}

// ---- 此前只有后端接口、前端一个按钮都没有的五类写入 -----------------
// 它们是"线上只能看不能记，什么都要回本地 CLI"的直接原因。

export interface CandidatePayload {
  code: string
  decision: string
  reason: string
  name?: string
  occurred_on?: string | null
  pool_id?: string
  score?: number | null
  timing?: string
  rule_version?: string
  evidence?: Record<string, unknown>
  source?: string
}

export interface PlanPayload {
  code: string
  title: string
  scenario: string
  occurred_on?: string | null
  entry_zone?: string
  stop_price?: number | null
  target_price?: number | null
  layers?: number | null
  invalidation?: string
  rule_version?: string
  supersedes_id?: string | null
  note?: string
  source?: string
}

export interface ReviewPayload {
  entity_type: 'plan' | 'candidate' | 'trade'
  entity_id: string
  outcome: string
  reviewed_on?: string | null
  strategy_tag?: string
  return_pct?: number | null
  max_favorable_pct?: number | null
  max_adverse_pct?: number | null
  lesson?: string
  next_rule?: string
  source?: string
}

export interface SnapshotPayload {
  total_assets: number
  occurred_on?: string | null
  cash?: number | null
  note?: string
  source?: string
}

export interface CashflowPayload {
  amount: number
  occurred_on?: string | null
  note?: string
  source?: string
}

/** 后端 WriteModel 是 extra="forbid"：多一个字段就 422。所以只提交填了的项。 */
function compact<T extends object>(payload: T): Partial<T> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined || value === '') continue
    out[key] = value
  }
  return out as Partial<T>
}

export function getCandidates(date?: string): Promise<Candidate[]> {
  const query = date ? `?date=${encodeURIComponent(date)}` : ''
  return request<Candidate[]>(`/candidates${query}`)
}

export function listCandidates(options: {
  strategy?: string
  decision?: string
  start?: string
  end?: string
  limit?: number
} = {}): Promise<Candidate[]> {
  const params = new URLSearchParams()
  if (options.strategy) params.set('strategy', options.strategy)
  if (options.decision) params.set('decision', options.decision)
  if (options.start) params.set('start', options.start)
  if (options.end) params.set('end', options.end)
  if (options.limit) params.set('limit', String(options.limit))
  const query = params.toString()
  return request<Candidate[]>(`/candidates/list${query ? `?${query}` : ''}`)
}

export function createCandidate(payload: CandidatePayload): Promise<{ id: string }> {
  return request<{ id: string }>('/candidates', {
    method: 'POST',
    body: JSON.stringify(compact(payload)),
  })
}

export function deleteCandidate(id: string): Promise<{ removed: boolean }> {
  return request<{ removed: boolean }>(`/candidates/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function batchDeleteCandidates(ids: string[]): Promise<{ removed: number }> {
  return request<{ removed: number }>('/candidates/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
}

export function createPlan(payload: PlanPayload): Promise<{ id: string }> {
  return request<{ id: string }>('/plans', {
    method: 'POST',
    body: JSON.stringify(compact(payload)),
  })
}

export function createReview(payload: ReviewPayload): Promise<{ id: string }> {
  return request<{ id: string }>('/reviews', {
    method: 'POST',
    body: JSON.stringify(compact(payload)),
  })
}

export function createSnapshot(payload: SnapshotPayload): Promise<{ id: string }> {
  return request<{ id: string }>('/snapshots', {
    method: 'POST',
    body: JSON.stringify(compact(payload)),
  })
}

export function createCashflow(payload: CashflowPayload): Promise<{ id: string }> {
  return request<{ id: string }>('/cashflows', {
    method: 'POST',
    body: JSON.stringify(compact(payload)),
  })
}

/** 供 api/quant.ts 复用同一套凭据、重试与错误契约。 */
export { request as apiRequest }

export function getSession(): Promise<SessionStatus> {
  return request<SessionStatus>('/auth/session')
}

export function login(username: string, password: string): Promise<SessionStatus> {
  return request<SessionStatus>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function logout(): Promise<{ authenticated: boolean }> {
  return request<{ authenticated: boolean }>('/auth/logout', { method: 'POST' })
}