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
  /** 等待首响应的期限；普通请求仍为20秒。 */
  timeoutMs?: number
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function requestOnce<T>(path: string, options?: ApiRequestInit): Promise<T> {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...init } = options ?? {}
  const headers = new Headers(init?.headers)
  // FormData 必须让浏览器自己设 Content-Type——它要在里面带 multipart
  // 的 boundary，手工设会让后端解析不出文件。
  const isFormData = init?.body instanceof FormData
  if (!headers.has('Content-Type') && init?.body && !isFormData) {
    headers.set('Content-Type', 'application/json')
  }
  // 单次尝试的墙钟上限。没有它时后端挂住就是无限等，再叠上 GET 的 4 次重试，
  // 界面会僵在加载态且没有任何交代。超时按可重试处理（等价于 504），
  // 调用方主动取消则原样上抛、不重试。
  const timer = new AbortController()
  const timeout = window.setTimeout(() => timer.abort(TIMEOUT_REASON), timeoutMs)
  const caller = init?.signal
  if (caller) {
    if (caller.aborted) timer.abort(caller.reason)
    else caller.addEventListener('abort', () => timer.abort(caller.reason), { once: true })
  }
  let response: Response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers,
      credentials: 'same-origin',
      signal: timer.signal,
    })
  } catch (caught: unknown) {
    if (timer.signal.reason === TIMEOUT_REASON) {
      const error = new Error(`请求超时（${timeoutMs / 1000} 秒未响应）`) as Error & {
        retryable?: boolean
      }
      error.retryable = true
      throw error
    }
    throw caught
  } finally {
    window.clearTimeout(timeout)
  }
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('loci:session-expired'))
    const body: unknown = await response.json().catch(() => null)
    const rawDetail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? (body as { detail: unknown }).detail
        : null
    const detail = formatApiDetail(rawDetail, response.status)
    const error = new Error(detail) as Error & {
      status?: number
      retryable?: boolean
      reason?: string
    }
    error.status = response.status
    error.retryable = RETRYABLE_STATUS.has(response.status)
    // 503 同时表示「缺依赖」和「库繁忙」，只有前者带这个头；调用方据此分流引导。
    error.reason = response.headers.get('x-loci-reason') ?? ''
    throw error
  }
  return response.json() as Promise<T>
}

/** 读接口遇 5xx/繁忙时自动退避重试；写接口不重试，避免重复记账。 */
async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
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
} = {}): Promise<Candidate[]> {
  const params = new URLSearchParams()
  if (options.code) params.set('code', options.code)
  if (options.strategy) params.set('strategy', options.strategy)
  if (options.decision) params.set('decision', options.decision)
  if (options.start) params.set('start', options.start)
  if (options.end) params.set('end', options.end)
  if (options.limit) params.set('limit', String(options.limit))
  if (options.include_backfill) params.set('include_backfill', 'true')
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
