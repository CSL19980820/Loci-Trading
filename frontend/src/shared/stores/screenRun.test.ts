import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import type { ScreenRunSlot, ScreenRunStatus } from '@/shared/types/quant'

vi.mock('@/shared/api/quant', () => ({
  getScreenRunStatus: vi.fn(),
  startScreenRun: vi.fn(),
  cancelScreenRun: vi.fn(),
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  }
})

import { cancelScreenRun, getScreenRunStatus, startScreenRun } from '@/shared/api/quant'
import { useScreenRunStore } from '@/shared/stores/screenRun'

const QIANLONG = 'qianlong-close'
const SANYUAN = 'sanyuan-tail'

function slot(patch: Partial<ScreenRunSlot> = {}): ScreenRunSlot {
  return {
    status: 'running',
    phase: 'scan',
    percent: 42,
    message: '扫描候选',
    strategy: QIANLONG,
    trade_date: '2026-08-27',
    log: [],
    result: null,
    error: '',
    ...patch,
  }
}

/**
 * `GET /api/screen/run` 的聚合响应：顶层是「当前这一个」，`runs` 才是真相。
 * 只传一个槽时和老单槽响应长得一样——那正是滚动升级期要兼容的形状。
 */
function aggregate(...slots: ScreenRunSlot[]): ScreenRunStatus {
  const runs: Record<string, ScreenRunSlot> = {}
  for (const item of slots) runs[item.strategy] = item
  const primary = slots.find((item) => item.status === 'running') ?? slots[0] ?? slot({ status: 'idle' })
  return {
    ...primary,
    runs,
    running_strategies: slots.filter((item) => item.status === 'running').map((item) => item.strategy),
    max_concurrent_runs: 3,
  }
}

const statusMock = vi.mocked(getScreenRunStatus)
const startMock = vi.mocked(startScreenRun)
const cancelMock = vi.mocked(cancelScreenRun)

describe('screenRun store · 战法级多槽', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    statusMock.mockReset()
    startMock.mockReset()
    cancelMock.mockReset()
    // 默认「后端受理了」：只有专门测降级的用例才覆盖成 reject。
    cancelMock.mockResolvedValue({
      cancelled: true,
      status: 'running',
      strategy: QIANLONG,
      percent: 0,
      cancelled_strategies: [QIANLONG],
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('运行中每 900ms 续一次轮询', async () => {
    statusMock.mockResolvedValue(aggregate(slot()))
    const store = useScreenRunStore()

    await store.hydrate()
    expect(statusMock).toHaveBeenCalledTimes(2) // hydrate 一次 + ensurePoll 立刻补一次

    await vi.advanceTimersByTimeAsync(900)
    expect(statusMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1800)
    expect(statusMock).toHaveBeenCalledTimes(5)
  })

  it('放弃后轮询真的停了：再推时间不会有新请求', async () => {
    statusMock.mockResolvedValue(aggregate(slot()))
    const store = useScreenRunStore()
    await store.hydrate()
    await vi.advanceTimersByTimeAsync(900)
    const callsBeforeAbandon = statusMock.mock.calls.length
    expect(callsBeforeAbandon).toBeGreaterThan(0)

    await store.abandon(QIANLONG)

    await vi.advanceTimersByTimeAsync(900 * 20)
    expect(statusMock).toHaveBeenCalledTimes(callsBeforeAbandon)
  })

  it('放弃后释放这个战法的开跑资格与本地进度', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ percent: 61 })))
    const store = useScreenRunStore()
    await store.hydrate()
    expect(store.isRunning(QIANLONG)).toBe(true)
    expect(store.canStart(QIANLONG)).toBe(false)

    await store.abandon(QIANLONG)

    expect(store.isRunning(QIANLONG)).toBe(false)
    expect(store.canStart(QIANLONG)).toBe(true)
    expect(store.running).toBe(false)
    expect(store.runFor(QIANLONG)).toBeNull()
    expect(store.percentFor(QIANLONG)).toBe(0)
    expect(store.abandonedFor(QIANLONG)).toMatchObject({ strategy: QIANLONG, percent: 61 })
    // 点名取消：不能把别的战法一起停掉
    expect(cancelMock).toHaveBeenCalledWith(QIANLONG)
  })

  it('放弃是前端侧的：hydrate 不把仍在后台跑的那次悄悄捡回来', async () => {
    statusMock.mockResolvedValue(aggregate(slot()))
    const store = useScreenRunStore()
    await store.hydrate()
    await store.abandon(QIANLONG)
    const calls = statusMock.mock.calls.length

    await store.hydrate()

    expect(store.running).toBe(false)
    expect(store.runFor(QIANLONG)).toBeNull()
    await vi.advanceTimersByTimeAsync(900 * 5)
    expect(statusMock).toHaveBeenCalledTimes(calls + 1) // 只有 hydrate 自己那一次
  })

  it('后端受理停止后，残影说「正在停止」而不是「已取消」', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ percent: 17, message: '拉取日线' })))
    cancelMock.mockResolvedValue({
      cancelled: true,
      status: 'running',
      strategy: QIANLONG,
      percent: 17,
      cancelled_strategies: [QIANLONG],
    })
    const store = useScreenRunStore()
    await store.hydrate()

    await store.abandon(QIANLONG)

    expect(cancelMock).toHaveBeenCalledTimes(1)
    expect(store.abandonedFor(QIANLONG)?.stopping).toBe(true)
    expect(store.abandonedFor(QIANLONG)?.percent).toBe(17)
    // 检查点还没到，任务真的还在跑；写「已取消」就是谎话。
    expect(store.abandonedFor(QIANLONG)?.message).toContain('停止')
    expect(store.abandonedFor(QIANLONG)?.message).not.toContain('已取消')

    store.dismissAbandoned(QIANLONG)
    expect(store.abandonedFor(QIANLONG)).toBeNull()
  })

  it('取消请求打不通时不把界面卡在原地，且照实说后台还在跑', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ percent: 17, message: '拉取日线' })))
    cancelMock.mockRejectedValue(new Error('connect ECONNREFUSED'))
    const store = useScreenRunStore()
    await store.hydrate()

    await store.abandon(QIANLONG)

    // 用户点了停止，界面就必须停——不能因为请求失败继续转圈。
    expect(store.running).toBe(false)
    expect(store.runFor(QIANLONG)).toBeNull()
    expect(store.abandonedFor(QIANLONG)?.stopping).toBe(false)
    expect(store.abandonedFor(QIANLONG)?.message).toContain('后台')
    expect(store.abandonedFor(QIANLONG)?.message).not.toContain('已取消')
  })

  it('同一战法重复点击被挡住，并说清是谁在跑、跑了多久、到哪一步', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ percent: 42, message: '扫描候选' })))
    const store = useScreenRunStore()
    await store.hydrate()

    expect(store.detailFor(QIANLONG)).toContain('42%')
    expect(store.detailFor(QIANLONG)).toContain('扫描候选')
    expect(store.elapsedTextFor(QIANLONG)).toMatch(/已跟踪/)

    const outcome = await store.start({ strategy: QIANLONG })
    expect(outcome).toBe('busy')
    expect(startMock).not.toHaveBeenCalled() // 本地就拦掉，不浪费一次 202
    expect(store.lastError).toContain('42%')
    expect(store.lastError).toContain('这个战法正在选股')
  })

  it('别的战法在跑不再阻塞：换个战法直接开得起来', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ percent: 42 })))
    const store = useScreenRunStore()
    await store.hydrate()
    expect(store.isRunning(QIANLONG)).toBe(true)

    // 这就是「引擎单槽」被拆掉的那一刻：三源不该被潜龙挡住
    expect(store.canStart(SANYUAN)).toBe(true)
    startMock.mockResolvedValue(slot({ strategy: SANYUAN, percent: 2 }) as ScreenRunStatus)
    // start 之后会立刻重同步一次：服务端此刻两条都在跑（占槽是同步发生的）
    statusMock.mockResolvedValue(
      aggregate(slot({ percent: 42 }), slot({ strategy: SANYUAN, percent: 2 })),
    )

    const outcome = await store.start({ strategy: SANYUAN })

    expect(outcome).toBe('started')
    expect(startMock).toHaveBeenCalledTimes(1)
    expect(store.lastError).toBe('')
    expect(store.isRunning(SANYUAN)).toBe(true)
    expect(store.isRunning(QIANLONG)).toBe(true)
    expect(store.runningStrategies).toEqual([QIANLONG, SANYUAN])
  })

  it('两个战法并行时进度互不干扰', async () => {
    statusMock.mockResolvedValue(
      aggregate(
        slot({ percent: 42, message: '潜龙扫描候选' }),
        slot({ strategy: SANYUAN, percent: 88, message: '三源写入候选池' }),
      ),
    )
    const store = useScreenRunStore()
    await store.hydrate()

    expect(store.percentFor(QIANLONG)).toBe(42)
    expect(store.percentFor(SANYUAN)).toBe(88)
    expect(store.detailFor(QIANLONG)).toContain('潜龙扫描候选')
    expect(store.detailFor(SANYUAN)).toContain('三源写入候选池')
    // 全局视图（状态轨用）看得见两条
    expect(store.runningStrategies).toHaveLength(2)
    expect(store.runningLabels).toContain('潜龙出海')
    expect(store.runningLabels).toContain('三源尾盘共振')
  })

  it('停一个不影响另一个：轮询继续，另一条进度还在', async () => {
    statusMock.mockResolvedValue(
      aggregate(slot({ percent: 42 }), slot({ strategy: SANYUAN, percent: 88 })),
    )
    const store = useScreenRunStore()
    await store.hydrate()
    const callsBefore = statusMock.mock.calls.length

    await store.abandon(QIANLONG)

    expect(cancelMock).toHaveBeenCalledWith(QIANLONG)
    expect(store.runFor(QIANLONG)).toBeNull()
    expect(store.isRunning(SANYUAN)).toBe(true)
    expect(store.running).toBe(true)

    // 轮询没被停掉——单槽时代这里是无条件停轮询，三源的进度会就此冻住
    await vi.advanceTimersByTimeAsync(900 * 2)
    expect(statusMock.mock.calls.length).toBeGreaterThan(callsBefore)
    // 被放弃的那个即使还在后端跑，也不会被轮询捡回来
    expect(store.runFor(QIANLONG)).toBeNull()
    expect(store.isRunning(SANYUAN)).toBe(true)
  })

  it('并发到顶：说「先停一个或等一个跑完」，不说「引擎忙」', async () => {
    statusMock.mockResolvedValue(
      aggregate(
        slot({ percent: 10 }),
        slot({ strategy: SANYUAN, percent: 20 }),
        slot({ strategy: 'yangshi-tail', percent: 30 }),
      ),
    )
    const store = useScreenRunStore()
    await store.hydrate()

    expect(store.maxConcurrentRuns).toBe(3)
    expect(store.atCapacity).toBe(true)
    expect(store.canStart('lugw-sanwai')).toBe(false)

    const outcome = await store.start({ strategy: 'lugw-sanwai' })
    expect(outcome).toBe('busy')
    expect(startMock).not.toHaveBeenCalled()
    expect(store.lastError).toContain('同时最多 3 个')
    expect(store.lastError).toContain('先停一个或等一个跑完')
    expect(store.lastError).not.toContain('单槽')
  })

  it('后端回 tenant_limit 时也按「排队」处理，并接上占位战法的进度', async () => {
    statusMock.mockResolvedValue(aggregate(slot({ status: 'idle', percent: 0 })))
    const store = useScreenRunStore()
    await store.hydrate()

    startMock.mockResolvedValue({
      ...slot({ strategy: SANYUAN, percent: 55 }),
      busy_reason: 'tenant_limit',
      running_strategies: [SANYUAN],
      max_concurrent_runs: 1,
    } as ScreenRunStatus)

  // start 之后立刻会补一次轮询：聚合快照是服务端真相，mock 必须自洽
    statusMock.mockResolvedValue(aggregate(slot({ strategy: SANYUAN, percent: 55 })))

    const outcome = await store.start({ strategy: QIANLONG })

    expect(outcome).toBe('busy')
    expect(store.lastError).toContain('同时最多 1 个')
    // 占位的那个战法进度要接上，用户才知道在等谁
    expect(store.isRunning(SANYUAN)).toBe(true)
    expect(store.percentFor(SANYUAN)).toBe(55)
  })

  it('放弃后重开同一战法：后端回 same_strategy 就接回旧进度，不谎报「已跑 0 秒」', async () => {
    statusMock.mockResolvedValue(aggregate(slot()))
    const store = useScreenRunStore()
    await store.hydrate()
    await store.abandon(QIANLONG)

    startMock.mockResolvedValue({
      ...slot({ percent: 88 }),
      busy_reason: 'same_strategy',
    } as ScreenRunStatus)
    // 同上：轮询回来的那份也得是 88，否则断言测的是 mock 而不是 store
    statusMock.mockResolvedValue(aggregate(slot({ percent: 88 })))
    const outcome = await store.start({ strategy: QIANLONG })

    expect(outcome).toBe('busy')
    expect(store.isRunning(QIANLONG)).toBe(true)
    expect(store.percentFor(QIANLONG)).toBe(88)
    expect(store.abandonedFor(QIANLONG)).toBeNull()
    expect(store.elapsedTextFor(QIANLONG)).toMatch(/已跟踪/)
  })

  it('后端给了 started_at 就说「已跑」，不再降级成「已跟踪」', async () => {
    const started = Date.now() / 1000 - 130
    statusMock.mockResolvedValue(aggregate(slot({ started_at: started })))
    const store = useScreenRunStore()
    await store.hydrate()

    expect(store.elapsedTextFor(QIANLONG)).toMatch(/^已跑 /)
    expect(store.elapsedTextFor(QIANLONG)).toContain('2 分')
  })

  it('老后端没有 runs 字段时按单槽响应折成字典', async () => {
    // 滚动升级期：前端已经多槽，后端还是老的
    statusMock.mockResolvedValue(slot({ percent: 33 }) as ScreenRunStatus)
    const store = useScreenRunStore()
    await store.hydrate()

    expect(store.isRunning(QIANLONG)).toBe(true)
    expect(store.percentFor(QIANLONG)).toBe(33)
    expect(store.runningStrategies).toEqual([QIANLONG])
  })
})
