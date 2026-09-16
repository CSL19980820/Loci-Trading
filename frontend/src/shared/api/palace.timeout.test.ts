/**
 * 请求层的墙钟上限。
 *
 * 没有它时后端挂住就是无限等，再叠上 GET 的 4 次重试，界面会僵在加载态且
 * 没有任何交代——这种"坏了也看不出来"的行为必须有测试钉住。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, getSession } from './palace'
import { replayResearchBacktestRun } from './quant_research'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('palace request timeout', () => {
  it('keeps ordinary POST first-response timeout at twenty seconds', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = apiRequest('/small-write', { method: 'POST' }).catch((error: Error) => error)
    await vi.advanceTimersByTimeAsync(19_999)
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect((await pending as Error).message).toContain('20 秒')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('only replay waits up to 300 seconds and does not forward timeoutMs to fetch', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const pending = replayResearchBacktestRun('run-1').catch((error: Error) => error)
    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty('timeoutMs')
    await vi.advanceTimersByTimeAsync(299_999)
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect((await pending as Error).message).toContain('300 秒')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('caller can still cancel replay before the long timeout without retry', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const pending = replayResearchBacktestRun('run-1', { signal: controller.signal }).catch((error: Error) => error)
    controller.abort()
    expect((await pending as Error).name).toBe('AbortError')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aborts a hung request instead of waiting forever', async () => {
    vi.useFakeTimers()
    // 永不 resolve 的 fetch，但尊重 signal —— 模拟后端挂死
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const pending = getSession().catch((err: Error) => err)
    // 推过超时 + 4 次重试的全部退避（200/400/600/800ms）
    await vi.advanceTimersByTimeAsync(20_000 * 5 + 2_000)
    const result = await pending

    expect(result).toBeInstanceOf(Error)
    expect((result as Error).message).toContain('超时')
    // GET 会重试，但必须有上限：1 次首发 + 4 次重试
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })

  it('does not retry when the caller aborts', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const controller = new AbortController()
    const pending = apiRequest('/auth/session', { signal: controller.signal }).catch(
      (err: Error) => err,
    )
    controller.abort()
    await vi.advanceTimersByTimeAsync(100)
    await pending

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
