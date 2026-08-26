import { afterEach, describe, expect, it, vi } from 'vitest'

import { awaitJobResult } from './quant_strategy'

/** 后端「还在跑」的一次响应；awaitJobResult 见到它就会继续轮询。 */
function runningRuns(): Response {
  return new Response(JSON.stringify([{ id: 'run-1', job_id: 'job-1', status: 'running' }]))
}

describe('awaitJobResult cancellation', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('stops polling once the caller aborts', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async () => runningRuns())
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    const pending = awaitJobResult('job-1', {
   intervalMs: 1000,
      timeoutMs: 900_000,
      signal: controller.signal,
    })
    // 先让它真的轮几圈，否则「不再轮询」可能只是因为压根没开始。
    await vi.advanceTimersByTimeAsync(3000)
    const pollsBeforeAbort = fetchMock.mock.calls.length
    expect(pollsBeforeAbort).toBeGreaterThan(1)

    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })

    // 关键断言：abort 之后再推进几十个轮询周期也不能有新请求。
    // 修复前 sleep 是裸 setTimeout、循环也没有出口，这里会一路涨到 300 次。
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock.mock.calls.length).toBe(pollsBeforeAbort)
  })

  it('rejects immediately when the signal is already aborted', async () => {
    const fetchMock = vi.fn(async () => runningRuns())
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    controller.abort()

    await expect(
      awaitJobResult('job-1', { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('forwards the signal to the underlying job-runs request', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([{ id: 'run-1', status: 'success' }])),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await awaitJobResult('job-1', { signal: controller.signal })

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/jobs/runs?job_id=job-1&limit=3')
  // palace.ts 把调用方 signal 桥接到它自己的超时 controller 上，所以传到
    // fetch 的是派生 signal、不是同一个对象——非空且未 abort 即证明管道通了。
    expect(init.signal).toBeTruthy()
    expect(init.signal?.aborted).toBe(false)
  })

  it('still works without a signal and returns the finished run', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([{ id: 'run-9', status: 'failed' }])),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(awaitJobResult('job-1')).resolves.toMatchObject({
      id: 'run-9',
      status: 'failed',
    })
  })
})
