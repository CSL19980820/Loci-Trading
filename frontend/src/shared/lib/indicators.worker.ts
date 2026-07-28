/// <reference lib="webworker" />
import { expose } from 'comlink'

import { computeChartPrep, type ChartPrepInput, type ChartPrepResult } from './chartPrep'
import { resampleBars, type KPeriod, type OhlcBar } from './indicators'

const api = {
  computeChartPrep(input: ChartPrepInput): ChartPrepResult {
    return computeChartPrep(input)
  },
  resampleBars(bars: OhlcBar[], period: KPeriod): OhlcBar[] {
    return resampleBars(bars, period)
  },
}

export type IndicatorsWorkerApi = typeof api

expose(api)
