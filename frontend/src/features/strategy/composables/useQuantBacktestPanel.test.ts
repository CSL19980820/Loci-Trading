import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { HorizonBacktestResult, StrategyInfo } from '@/shared/types/quant'

vi.mock('@/shared/api/quant', () => ({
  runBacktest: vi.fn(),
  runHorizonBacktest: vi.fn(),
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  }
})

import { runHorizonBacktest } from '@/shared/api/quant'
import { useQuantBacktestPanel, type QuantBacktestPanel } from './useQuantBacktestPanel'

const horizonMock = vi.mocked(runHorizonBacktest)

const STRATEGIES: StrategyInfo[] = [{ slug: 's1', name: '战法一' } as StrategyInfo]

const RESULT = {
  horizons: { t1: { n: 3 }, t3: { n: 5 } },
} as unknown as HorizonBacktestResult

/** 挂一个空壳组件跑 composable：它注册了 onUnmounted，必须在组件上下文里。 */
function mountPanel(pinia = createPinia()) {
  let panel!: QuantBacktestPanel
  const Harness = defineComponent({
    setup() {
      panel = useQuantBacktestPanel({ strategies: ref(STRATEGIES) })
      return () => null
    },
  })
  const wrapper = mount(Harness, { global: { plugins: [pinia] } })
  return { panel, wrapper, pinia }
}

/** 永不 settle 的回测请求 + 拿到它的 resolve/reject，用来模拟「慢响应」。 */
function hangingRun() {
  const box: {
    resolve?: (value: HorizonBacktestResult) => void
    reject?: (reason: Error) => void
  } = {}
  horizonMock.mockImplementation(
    () =>
      new Promise<HorizonBacktestResult>((resolve, reject) => {
        box.resolve = resolve
        box.reject = reject
      }),
  )
  return box
}

describe('useQuantBacktestPanel · 停止回测', () => {
  beforeEach(() => {
    horizonMock.mockReset()
    window.localStorage.clear()
  })

  it('把 AbortSignal 交给回测请求，停止时真的 abort', async () => {
    let seen: AbortSignal | undefined
    horizonMock.mockImplementation((_payload, options) => {
      seen = options?.signal
      return new Promise<HorizonBacktestResult>(() => undefined)
    })
    const { panel } = mountPanel()

    void panel.run()
    await flushPromises()
    expect(seen).toBeTruthy()
    expect(seen?.aborted).toBe(false)

    panel.stop()
    expect(seen?.aborted).toBe(true)
    expect(panel.busy.value).toBe(false)
  })

  it('停止后迟到的成功响应不再回写结果', async () => {
    const box = hangingRun()
    const { panel } = mountPanel()

    void panel.run()
    await flushPromises()
    panel.stop()

    box.resolve?.(RESULT)
    await flushPromises()

    expect(panel.horizonResult.value).toBeNull()
    expect(panel.activeHasResult.value).toBe(false)
    expect(panel.busy.value).toBe(false)
  })

  it('停止后迟到的失败也不再糊一条报错上来', async () => {
    const box = hangingRun()
    const { panel } = mountPanel()

    void panel.run()
    await flushPromises()
    panel.stop()

    box.reject?.(new Error('连接已中止'))
    await flushPromises()

    expect(panel.errorText.value).toBe('')
    expect(panel.busy.value).toBe(false)
  })

  it('正常跑完仍然回写结果', async () => {
    horizonMock.mockResolvedValue(RESULT)
    const { panel } = mountPanel()

    await panel.run()
    await flushPromises()

    expect(panel.horizonResult.value).toEqual(RESULT)
    expect(panel.busy.value).toBe(false)
  })

  it('切 Tab 卸载再装载：结果还在', async () => {
    horizonMock.mockResolvedValue(RESULT)
    const pinia = createPinia()
    const first = mountPanel(pinia)

    await first.panel.run()
    await flushPromises()
    first.wrapper.unmount()

    const second = mountPanel(pinia)
    expect(second.panel.horizonResult.value).toEqual(RESULT)
  })

  it('卸载即作废在途请求，不会回写已经没人看的面板', async () => {
    const box = hangingRun()
    const { panel, wrapper } = mountPanel()

    void panel.run()
    await flushPromises()
    wrapper.unmount()

    box.resolve?.(RESULT)
    await flushPromises()

    expect(panel.horizonResult.value).toBeNull()
  })

  it('开跑前就把预计耗时说出来，不藏在空态里', () => {
    const { panel } = mountPanel()
    expect(panel.expectedHint.value).toContain('几十秒')
  })
})
