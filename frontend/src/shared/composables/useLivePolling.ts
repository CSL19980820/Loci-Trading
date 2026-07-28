import { onMounted, onUnmounted, ref, type Ref } from 'vue'

import { getMarketSession } from '@/shared/api/quant'
import { isAshareLiveWindow, type MarketSession } from '@/shared/lib/marketSession'

/**
 * 受交易日 / 15:00 闸门约束的轮询。
 * - 非交易日、开盘前、收盘后：不自动 tick（仍可手动 refresh 一次）
 * - 收盘后若库已是当日最新：live_allowed=false
 */
export function useLivePolling(opts: {
  intervalMs: number
  tick: () => void | Promise<void>
  /** 为 false 时不启动（例如详情页） */
  enabled?: Ref<boolean> | (() => boolean)
}) {
  const session = ref<MarketSession | null>(null)
  const liveAllowed = ref(isAshareLiveWindow())
  let timer: number | undefined
  let sessionTimer: number | undefined

  function enabled(): boolean {
    if (opts.enabled == null) return true
    if (typeof opts.enabled === 'function') return opts.enabled()
    return opts.enabled.value
  }

  async function refreshSession(): Promise<void> {
    try {
      session.value = await getMarketSession()
      liveAllowed.value = Boolean(session.value.live_allowed)
    } catch {
      // API 失败时退回本地钟点粗判
      liveAllowed.value = isAshareLiveWindow()
    }
  }

  async function runTick(): Promise<void> {
    if (!enabled()) return
    if (document.hidden) return
    if (!liveAllowed.value) return
    await opts.tick()
  }

  function stop(): void {
    if (timer) {
      window.clearInterval(timer)
      timer = undefined
    }
    if (sessionTimer) {
      window.clearInterval(sessionTimer)
      sessionTimer = undefined
    }
  }

  function start(): void {
    stop()
    void refreshSession().then(() => {
      void runTick()
    })
    timer = window.setInterval(() => {
      void runTick()
    }, opts.intervalMs)
    sessionTimer = window.setInterval(() => {
      void refreshSession()
    }, 60_000)
  }

  onMounted(() => {
    start()
  })

  onUnmounted(() => {
    stop()
  })

  return { session, liveAllowed, refreshSession, start, stop, runTick }
}
