import type {
  Analytics,
  Dashboard,
  PoolDay,
  PoolSummary,
  ReviewRecord,
  TimelineEvent,
  TradePayload,
  TradeRecord,
} from '@/types'

const API_ROOT = '/api'
const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504])
const MAX_GET_RETRIES = 2

export interface SessionStatus {
  authenticated: boolean
  username: string
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function requestOnce<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type') && init?.body) {
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