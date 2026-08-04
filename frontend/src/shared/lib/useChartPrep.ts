/**
 * 指标计算 Worker 客户端。失败时回退主线程 computeChartPrep。
 */
import { wrap, type Remote } from 'comlink'
import { ref, shallowRef } from 'vue'

import { computeChartPrep, type ChartPrepInput, type ChartPrepResult } from './chartPrep'
import type { IndicatorsWorkerApi } from './indicators.worker'
import { resampleBars, type KPeriod, type OhlcBar } from './indicators'

let remote: Remote<IndicatorsWorkerApi> | null = null
let bootFailed = false

async function getApi(): Promise<Remote<IndicatorsWorkerApi> | null> {
  if (bootFailed) return null
  if (remote) return remote
  try {
    const WorkerCtor = (await import('./indicators.worker.ts?worker')).default
    const worker = new WorkerCtor()
    remote = wrap<IndicatorsWorkerApi>(worker)
    return remote
  } catch {
    bootFailed = true
    remote = null
    return null
  }
}

export async function prepChartOffthread(input: ChartPrepInput): Promise<ChartPrepResult> {
  const api = await getApi()
  if (!api) return computeChartPrep(input)
  try {
    return await api.computeChartPrep(input)
  } catch {
    return computeChartPrep(input)
  }
}

export async function resampleOffthread(bars: OhlcBar[], period: KPeriod): Promise<OhlcBar[]> {
  const api = await getApi()
  if (!api) return resampleBars(bars, period)
  try {
    return await api.resampleBars(bars, period)
  } catch {
    return resampleBars(bars, period)
  }
}

/** 可选取消的 prep；用于 watch 防竞态。 */
export function useChartPrepState() {
  const prep = shallowRef<ChartPrepResult | null>(null)
  const pending = ref(false)
  let seq = 0

  async function run(input: ChartPrepInput): Promise<ChartPrepResult> {
    const my = ++seq
    pending.value = true
    const result = await prepChartOffthread(input)
    if (my === seq) {
      prep.value = result
      pending.value = false
    }
    return result
  }

  return { prep, pending, run }
}
