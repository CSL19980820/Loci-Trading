/** 选股后台任务：全局单例轮询，不阻塞页面。 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getScreenRunStatus, startScreenRun } from '@/shared/api/quant'
import { strategyLabel } from '@/shared/lib/format'
import type { ScreenResult, ScreenRunStatus } from '@/shared/types/quant'

export type ScreenStartOutcome = 'started' | 'busy' | 'error'

export const useScreenRunStore = defineStore('screenRun', () => {
  const snap = ref<ScreenRunStatus | null>(null)
  const lastError = ref('')
  let timer: number | undefined
  let pollGeneration = 0

  const running = computed(() => snap.value?.status === 'running')
  const busyStrategy = computed(() =>
    running.value ? String(snap.value?.strategy || '') : '',
  )
  const percent = computed(() => Math.round(Number(snap.value?.percent || 0)))
  const result = computed(() => (snap.value?.result as ScreenResult | null) ?? null)

  function stopPoll(): void {
    if (timer) {
      window.clearTimeout(timer)
      timer = undefined
    }
  }

  function schedulePoll(): void {
    stopPoll()
    const gen = pollGeneration
    timer = window.setTimeout(() => {
      void tick(gen)
    }, 900)
  }

  async function tick(gen: number): Promise<void> {
    if (gen !== pollGeneration) return
    try {
      const next = await getScreenRunStatus()
      if (gen !== pollGeneration) return
      snap.value = next
      if (next.status === 'running') {
        schedulePoll()
        return
      }
      stopPoll()
    } catch {
      if (gen !== pollGeneration) return
      schedulePoll()
    }
  }

  function ensurePoll(): void {
    if (!running.value) return
    if (timer) return
    pollGeneration += 1
    void tick(pollGeneration)
  }

  async function hydrate(): Promise<void> {
    try {
      snap.value = await getScreenRunStatus()
      if (running.value) ensurePoll()
    } catch {
      /* 启动时接口未就绪可忽略 */
    }
  }

  function isBusyFor(strategy: string): boolean {
    if (!running.value) return false
    const busy = busyStrategy.value
    if (!busy) return true
    return busy === strategy
  }

  /** 任一选股在跑时，引擎侧都不允许再开新任务（后端全局单槽）。 */
  function canStartEngine(): boolean {
    return !running.value
  }

  async function start(payload: {
    strategy: string
    date?: string
    start?: string
    end?: string
    record_candidates?: boolean
    top_n?: number
  }): Promise<ScreenStartOutcome> {
    lastError.value = ''
    if (running.value) {
      lastError.value = busyStrategy.value
        ? `选股进行中：${strategyLabel(busyStrategy.value)}，请等待结束后再跑`
        : '已有选股任务在跑，请等待结束'
      return 'busy'
    }

    try {
      const next = await startScreenRun({
        record_candidates: true,
        ...payload,
      })
      snap.value = next

      // 后端已在跑时返回当前快照，不新开任务
      if (
        next.status === 'running' &&
        next.strategy &&
        payload.strategy &&
        next.strategy !== payload.strategy
      ) {
        lastError.value = `选股进行中：${next.strategy}，请等待结束`
        ensurePoll()
        return 'busy'
      }

      if (next.status === 'running') {
        ensurePoll()
        return 'started'
      }

      if (next.status === 'error') {
        lastError.value = next.error || next.message || '选股失败'
        return 'error'
      }

      return 'started'
    } catch (caught: unknown) {
      lastError.value = caught instanceof Error ? caught.message : '启动选股失败'
      return 'error'
    }
  }

  // 完成后轻提示（不抢前台；用户可在工作台看结果）
  watch(
    () => snap.value?.status,
    (status, prev) => {
      if (prev !== 'running') return
      if (status === 'done') {
        const result = snap.value?.result as ScreenResult | null
        const written =
          result?.recorded?.written_total ??
          result?.recorded?.written ??
          result?.range?.written_total
        const strategy = strategyLabel(snap.value?.strategy || '')
        const days = result?.range?.trading_days
        ElMessage.success(
          written != null
            ? days && days > 1
              ? `区间选股完成 · ${days} 日 · 入库合计 ${written} 条 · ${strategy}`
              : `选股完成并入库 ${written} 条 · ${strategy}`
            : `选股完成 · ${strategy}`,
        )
      } else if (status === 'error') {
        ElMessage.error(snap.value?.error || snap.value?.message || '选股失败')
      }
    },
  )

  return {
    snap,
    running,
    busyStrategy,
    percent,
    result,
    lastError,
    hydrate,
    ensurePoll,
    stopPoll,
    start,
    canStartEngine,
    isBusyFor,
  }
})
