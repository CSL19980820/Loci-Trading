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
    const error = caught as Error & { status?: number }
    if (error.status === 503) {
      throw new CapabilityUnavailableError(error.message)
    }
    throw caught
  }
}

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
