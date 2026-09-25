import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest } from './palace'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe('JSON request deadlines and cancellation', () => {
  it('times out a slow body after successful headers, without retrying a write', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(async (_url: unknown, init: RequestInit) => ({
      ok: true,
      json: () => new Promise((_resolve, reject) => init.signal!.addEventListener('abort', () => reject(init.signal!.reason), { once: true })),
    }))
    vi.stubGlobal('fetch', fetcher)
    const request = apiRequest('/probe', { method: 'POST', timeoutMs: 25 })
    const assertion = expect(request).rejects.toMatchObject({ name: 'TimeoutError' })
    await vi.advanceTimersByTimeAsync(26)
    await assertion
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('removes the caller abort listener after the body has completed', async () => {
    const caller = new AbortController()
    const add = vi.spyOn(caller.signal, 'addEventListener')
    const remove = vi.spyOn(caller.signal, 'removeEventListener')
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"ok":true}')))
    await expect(apiRequest('/probe', { signal: caller.signal })).resolves.toEqual({ ok: true })
    expect(remove).toHaveBeenCalledWith('abort', add.mock.calls[0]![1])
  })

  it('cancels retry backoff immediately and does not issue a second request', async () => {
    vi.useFakeTimers()
    const caller = new AbortController()
    const fetcher = vi.fn(async () => new Response('{"detail":"busy"}', { status: 503 }))
    vi.stubGlobal('fetch', fetcher)
    const request = apiRequest('/probe', { signal: caller.signal })
    const assertion = expect(request).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(1)
    caller.abort()
    await assertion
    await vi.advanceTimersByTimeAsync(1_000)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('retries a transient read within the deadline and never retries writes', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 503 })).mockResolvedValueOnce(new Response('{"ok":true}'))
    vi.stubGlobal('fetch', fetcher)
    const request = apiRequest('/probe', { timeoutMs: 1_000 })
    await vi.advanceTimersByTimeAsync(201)
    await expect(request).resolves.toEqual({ ok: true })
    expect(fetcher).toHaveBeenCalledTimes(2)
    fetcher.mockReset().mockResolvedValue(new Response('{}', { status: 503 }))
    await expect(apiRequest('/probe', { method: 'POST' })).rejects.toMatchObject({ status: 503 })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
