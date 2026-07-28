/** 图表指标批量计算（主线程与 Worker 共用）。 */
import {
  kdj,
  macd,
  resampleBars,
  sma,
  type KPeriod,
  type OhlcBar,
} from './indicators'

export type ChartIndicatorKind = 'macd' | 'kdj' | 'none'

export interface ChartPrepInput {
  bars: OhlcBar[]
  period: KPeriod
  maPeriods: number[]
  indicator: ChartIndicatorKind
}

export interface ChartPrepResult {
  dates: string[]
  candle: number[][]
  volumes: Array<{ value: number; up: boolean }>
  maLines: Array<{ period: number; data: Array<number | null> }>
  macd: { dif: Array<number | null>; dea: Array<number | null>; hist: Array<number | null> } | null
  kdj: { k: Array<number | null>; d: Array<number | null>; j: Array<number | null> } | null
  seriesBars: OhlcBar[]
}

export function computeChartPrep(input: ChartPrepInput): ChartPrepResult {
  const seriesBars = resampleBars(input.bars, input.period)
  const dates = seriesBars.map((b) => b.trade_date)
  const candle = seriesBars.map((b) => [
    Number(b.open ?? 0),
    Number(b.close ?? 0),
    Number(b.low ?? 0),
    Number(b.high ?? 0),
  ])
  const volumes = seriesBars.map((b) => {
    const open = Number(b.open ?? 0)
    const close = Number(b.close ?? 0)
    return { value: Number(b.volume ?? 0), up: close >= open }
  })
  const closes = seriesBars.map((b) => (b.close == null ? null : Number(b.close)))
  const highs = seriesBars.map((b) => (b.high == null ? null : Number(b.high)))
  const lows = seriesBars.map((b) => (b.low == null ? null : Number(b.low)))

  const maLines = input.maPeriods.map((period) => ({
    period,
    data: sma(closes, period),
  }))

  let macdOut: ChartPrepResult['macd'] = null
  let kdjOut: ChartPrepResult['kdj'] = null
  if (input.indicator === 'macd') macdOut = macd(closes)
  else if (input.indicator === 'kdj') kdjOut = kdj(highs, lows, closes)

  return { dates, candle, volumes, maLines, macd: macdOut, kdj: kdjOut, seriesBars }
}
