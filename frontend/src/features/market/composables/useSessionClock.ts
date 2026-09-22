/**
 * 交易时段时钟：30s 一跳，产出「早盘 · 距午休 42 分」这类状态文案。
 *
 * 注册/移除无条件对称；KeepAlive 离页也停表，回页立刻补一次当前时刻。
 * 盘面页头把它渲染在「盘面 · 状态徽标」右侧——精确时间只有这一处，
 * 不再单独占一条刻度尺。纯推导在 `./sessionClock.ts`（可单测）。
 */
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'

import { computeSessionClock } from './sessionClock'

/** 30s 一跳足够：最小粒度是「分」。 */
const TICK_MS = 30_000

export function useSessionClock(isTradingDay: () => boolean | null | undefined) {
  const now = ref(new Date())
  let timer: ReturnType<typeof setInterval> | null = null

  function start(): void {
    stop()
    now.value = new Date()
    timer = setInterval(() => {
      now.value = new Date()
    }, TICK_MS)
  }

  function stop(): void {
    if (timer) clearInterval(timer)
    timer = null
  }

  onMounted(start)
  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)

  const state = computed(() =>
    computeSessionClock({ now: now.value, isTradingDay: isTradingDay() ?? null }),
  )

  return {
    state,
    /** 时段名：`早盘` / `休市` */
    phaseLabel: computed(() => state.value.phaseLabel),
    /** 倒计时：`距午休 42 分` / `距下次开盘 1 天 21 小时` */
    remainText: computed(() => state.value.remainText),
    /** 整句：`早盘 · 距午休 42 分`（tooltip 用） */
    statusText: computed(() => state.value.statusText),
  }
}
