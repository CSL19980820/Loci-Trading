import type {
  Candidate,
  PoolDay,
  ReviewRecord,
  TimelineEvent,
} from '@/shared/types/palace'

import { formatApiDetail } from '@/shared/lib/errors'

const API_ROOT = '/api'
const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504])
/** 账本 SQLite 偶发锁竞争 → 503；多退几步再抛给 UI。 */
const MAX_GET_RETRIES = 4
/** 单次请求的墙钟上限。全市场同步这类长活走 ops Job 轮询，不占用 HTTP 连接。 */
const REQUEST_TIMEOUT_MS = 20_000
const TIMEOUT_REASON = 'loci-request-timeout'

export interface ApiRequestInit extends RequestInit {
  /** 单次请求期限，包含响应体读取；默认20秒。 */
  timeoutMs?: number
  /** 所有尝试及退避的总期限，默认等于 timeoutMs。 */
  totalTimeoutMs?: number
}

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

function timeoutError(ms: number): Error & { retryable: boolean } {
  return Object.assign(new Error(`请求超时（${ms / 1000} 秒内未完成）`), { name: 'TimeoutError', retryable: true })
}

function sleep(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return }
    const onAbort = () => { window.clearTimeout(timer); reject(signal?.reason) }
    const timer = window.setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve() }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

async function requestOnce<T>(path: string, options?: ApiRequestInit): Promise<T> {
  const { timeoutMs = REQUEST_TIMEOUT_MS, totalTimeoutMs: _totalTimeoutMs, ...init } = options ?? {}
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const timer = new AbortController()
  const timeout = window.setTimeout(() => timer.abort(TIMEOUT_REASON), timeoutMs)
  const caller = init.signal
  const onAbort = () => timer.abort(caller?.reason)
  if (caller?.aborted) onAbort()
  else caller?.addEventListener('abort', onAbort, { once: true })
  try {
    const response = await fetch(`${API_ROOT}${path}`, {
      ...init, headers, credentials: 'same-origin', signal: timer.signal,
    })
    if (!response.ok) {
      if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('loci:session-expired'))
      const body: unknown = await response.json().catch((error: unknown) => {
        // A cancelled body is not an empty error response.
        if (timer.signal.aborted) throw error
        return null
      })
      const rawDetail = typeof body === 'object' && body !== null && 'detail' in body ? body.detail : null
      throw Object.assign(new Error(formatApiDetail(rawDetail, response.status)), {
        status: response.status, retryable: RETRYABLE_STATUS.has(response.status),
        reason: response.headers.get('x-loci-reason') ?? '',
      })
    }
    // Keep cancellation alive until the body is consumed, not just until headers arrive.
    const body = await response.json() as T
    timer.signal.throwIfAborted()
    return body
  } catch (caught: unknown) {
    if (timer.signal.reason === TIMEOUT_REASON) throw timeoutError(timeoutMs)
    throw caught
  } finally {
    window.clearTimeout(timeout)
    caller?.removeEventListener('abort', onAbort)
  }
}

/** Reads may retry transient failures within one deadline; writes never retry. */
async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const canRetry = method === 'GET' || method === 'HEAD'
  const timeoutMs = init?.timeoutMs ?? REQUEST_TIMEOUT_MS
  const totalTimeoutMs = init?.totalTimeoutMs ?? timeoutMs
  const deadline = Date.now() + totalTimeoutMs
  let attempt = 0
  for (;;) {
    init?.signal?.throwIfAborted()
    const remaining = deadline - Date.now()
    if (remaining <= 0) throw timeoutError(totalTimeoutMs)
    try {
      return await requestOnce<T>(path, { ...init, timeoutMs: Math.min(timeoutMs, remaining) })
    } catch (caught: unknown) {
      if (init?.signal?.aborted) throw caught
      const retryable = Boolean((caught as { retryable?: boolean } | null)?.retryable) || caught instanceof TypeError
      if (!canRetry || !retryable || attempt >= MAX_GET_RETRIES) throw caught
      const backoff = 200 * ++attempt
      if (deadline - Date.now() <= backoff) throw caught
      await sleep(backoff, init?.signal)
    }
  }
}

export function getTodayAlerts(): Promise<TodayAlert[]> {
  return request<TodayAlert[]>('/alerts/today')
}

async function downloadExport(path: string, filename: string): Promise<void> {
  const response = await fetch(`${API_ROOT}${path}`, { credentials: 'same-origin' })
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('loci:session-expired'))
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

export function getTimeline(code: string): Promise<TimelineEvent[]> {
  return request<TimelineEvent[]>(`/timeline/${encodeURIComponent(code)}`)
}

export function getReviews(limit = 100): Promise<ReviewRecord[]> {
  const query = limit === 100 ? '' : `?limit=${limit}`
  return request<ReviewRecord[]>(`/reviews${query}`)
}

export function getPoolDay(date?: string, poolId?: string): Promise<PoolDay> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (poolId) params.set('pool_id', poolId)
  const query = params.toString()
  return request<PoolDay>(`/pools/day${query ? `?${query}` : ''}`)
}

// ---- 候选 / 预案 / 复盘三类写入 ------------------------------------
// 持仓与成交类写入（成交、出入金、资产快照、持仓导入）已随账本下线一并移除。

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

/** 后端 WriteModel 是 extra="forbid"：多一个字段就 422。所以只提交填了的项。 */
function compact<T extends object>(payload: T): Partial<T> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined || value === '') continue
    out[key] = value
  }
  return out as Partial<T>
}

export function getCandidates(
  date?: string,
  options: { include_backfill?: boolean } = {},
): Promise<Candidate[]> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (options.include_backfill) params.set('include_backfill', 'true')
  const query = params.toString()
  return request<Candidate[]>(`/candidates${query ? `?${query}` : ''}`)
}

export function listCandidates(options: {
  code?: string
  strategy?: string
  decision?: string
  start?: string
  end?: string
  limit?: number
  /** 默认排除回填；审计时传 true */
  include_backfill?: boolean
  /** 只要时间轴：不回 evidence / effective_params */
  slim?: boolean
} = {}): Promise<Candidate[]> {
  const params = new URLSearchParams()
  if (options.code) params.set('code', options.code)
  if (options.strategy) params.set('strategy', options.strategy)
  if (options.decision) params.set('decision', options.decision)
  if (options.start) params.set('start', options.start)
  if (options.end) params.set('end', options.end)
  if (options.limit) params.set('limit', String(options.limit))
  if (options.include_backfill) params.set('include_backfill', 'true')
  if (options.slim) params.set('slim', 'true')
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
