import { onActivated, onDeactivated, onMounted, onUnmounted, ref, type Ref } from 'vue'

import { getMarketSession } from '@/shared/api/quant'
import type { MarketSession } from '@/shared/lib/marketSession'

/**
 * 受交易日 / 15:00 闸门约束的轮询。
 * - 非交易日、开盘前、收盘后：不自动 tick（仍可手动 refresh 一次）
 * - 收盘后若库已是当日最新：live_allowed=false
 * - KeepAlive 离页：onDeactivated 停表，onActivated 重启，避免后台请求风暴
 */
export function useLivePolling(opts: {
  intervalMs: number
  tick: () => void | Promise<void>
  /** 为 false 时不启动（例如详情页） */
  enabled?: Ref<boolean> | (() => boolean)
}) {
  const session = ref<MarketSession | null>(null)
  const liveAllowed = ref(false)
  let timer: number | undefined
  let sessionTimer: number | undefined
  let tickRunning = false
  let lifecycleGeneration = 0

  function enabled(): boolean {
    if (opts.enabled == null) return true
    if (typeof opts.enabled === 'function') return opts.enabled()
    return opts.enabled.value
  }

  async function refreshSession(generation = lifecycleGeneration): Promise<void> {
    try {
      const next = await getMarketSession()
      if (generation !== lifecycleGeneration) return
      session.value = next
      liveAllowed.value = Boolean(session.value.live_allowed)
    } catch {
      if (generation !== lifecycleGeneration) return
      // 会话接口是实时请求与后台落库的权威闸门；未知时宁可不拉远程行情。
      liveAllowed.value = false
    }
  }

  async function runTick(options: { ignoreLiveGate?: boolean } = {}): Promise<void> {
    if (!enabled()) return
    if (document.hidden) return
    if (!options.ignoreLiveGate && !liveAllowed.value) return
    if (tickRunning) return
    tickRunning = true
    try {
      await opts.tick()
    } finally {
      tickRunning = false
    }
  }

  /** 首次展示可读取一次缓存行情；仍共享单飞保护，后续自动刷新继续受会话闸门约束。 */
  async function refreshOnce(): Promise<void> {
    await runTick({ ignoreLiveGate: true })
  }

  function stop(): void {
    // 清定时器 + 作废进行中的 session 回调；手动 runTick 仍可用（测单飞 / 显式刷新）
    lifecycleGeneration += 1
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
    if (!enabled()) return
    const generation = lifecycleGeneration
    void refreshSession(generation).then(() => {
      if (generation !== lifecycleGeneration) return
      void runTick()
    })
    timer = window.setInterval(() => {
      void runTick()
    }, opts.intervalMs)
    sessionTimer = window.setInterval(() => {
      void refreshSession(generation)
    }, 60_000)
  }

  onMounted(() => {
    start()
  })

  onActivated(() => {
    start()
  })

  onDeactivated(() => {
    stop()
  })

  onUnmounted(() => {
    stop()
  })

  return { session, liveAllowed, refreshSession, refreshOnce, start, stop, runTick }
}
