/** 量化 API 共用请求层：503 → CapabilityUnavailableError。 */
import { apiRequest } from '@/shared/api/palace'

/** 依赖缺失导致的功能不可用。与普通请求失败区分开，便于界面给出不同引导。 */
export class CapabilityUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CapabilityUnavailableError'
  }
}

export async function quantRequest<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await apiRequest<T>(path, init)
  } catch (caught: unknown) {
    const error = caught as Error & { status?: number; reason?: string }
    // 后端用 503 同时表示「缺依赖」和「SQLite 短暂繁忙」。只有前者带
    // X-Loci-Reason: capability-missing；把繁忙也当成缺依赖，会让用户在
    // 锁竞争时被引导去装包——装了也没用。
    if (error.status === 503 && error.reason === 'capability-missing') {
      throw new CapabilityUnavailableError(error.message)
    }
    throw caught
  }
}

/** 取消原因规范成 `name === 'AbortError'` 的 Error，与 fetch abort 对齐。 */
export function toAbortError(reason?: unknown): Error {
  if (reason instanceof Error) return reason
  const error = new Error(typeof reason === 'string' && reason ? reason : '请求已取消')
  error.name = 'AbortError'
  return error
}

/**
 * 可取消的 sleep。裸 `setTimeout` 的 Promise 在组件卸载后照样 resolve，
 * 靠它驱动的轮询循环就永远停不下来；这里把 abort 接进来并清掉 timer。
 */
export function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  const { promise, resolve, reject } = Promise.withResolvers<void>()
  if (signal?.aborted) {
    reject(toAbortError(signal.reason))
    return promise
  }
  const onAbort = (): void => {
    clearTimeout(timer)
    reject(toAbortError(signal?.reason))
  }
  const timer = setTimeout(() => {
    signal?.removeEventListener('abort', onAbort)
    resolve()
  }, ms)
  signal?.addEventListener('abort', onAbort, { once: true })
  return promise
}

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
