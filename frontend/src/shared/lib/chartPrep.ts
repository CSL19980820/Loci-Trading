/** 图表指标批量计算（主线程与 Worker 共用）。 */
import {
  kdj,
  macd,
  resampleBars,
  sma,
  type KPeriod,
  type OhlcBar,
} from './indicators'

export type ChartIndicatorKind = 'macd' | 'kdj'

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
  /** 量能均线（默认 MA5 / MA60） */
  volumeMas: Array<{ period: number; data: Array<number | null> }>
  maLines: Array<{ period: number; data: Array<number | null> }>
  macd: { dif: Array<number | null>; dea: Array<number | null>; hist: Array<number | null> } | null
  kdj: { k: Array<number | null>; d: Array<number | null>; j: Array<number | null> } | null
  seriesBars: OhlcBar[]
}

const VOL_MA_PERIODS = [5, 60] as const

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
  const volValues = volumes.map((v) => v.value)
  const volumeMas = VOL_MA_PERIODS.map((period) => ({
    period,
    data: sma(volValues, period),
  }))

  const closes = seriesBars.map((b) => (b.close == null ? null : Number(b.close)))
  const highs = seriesBars.map((b) => (b.high == null ? null : Number(b.high)))
  const lows = seriesBars.map((b) => (b.low == null ? null : Number(b.low)))

  const maLines = input.maPeriods.map((period) => ({
    period,
    data: sma(closes, period),
  }))

  // 副图常驻：按当前种类计算其一（切换时重算）
  const macdOut = input.indicator === 'macd' ? macd(closes) : null
  const kdjOut = input.indicator === 'kdj' ? kdj(highs, lows, closes) : null

  return {
    dates,
    candle,
    volumes,
    volumeMas,
    maLines,
    macd: macdOut,
    kdj: kdjOut,
    seriesBars,
  }
}
