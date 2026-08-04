/** 日线重采样与常见技术指标（MA / MACD / KDJ / RSI / BOLL 等）。 */

export interface OhlcBar {
  trade_date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  amount?: number | null
  turnover?: number | null
}

export type KPeriod = 'day' | 'week' | 'month'

function num(value: number | null | undefined): number | null {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? null
    : Number(value)
}

function weekKey(date: string): string {
  const d = new Date(`${date}T00:00:00`)
  const day = (d.getDay() + 6) % 7 // Mon=0
  d.setDate(d.getDate() - day)
  return d.toISOString().slice(0, 10)
}

function monthKey(date: string): string {
  return date.slice(0, 7)
}

/** 由日线合成周/月 K：开=首、高=max、低=min、收=末，量额换手率求和。 */
export function resampleBars(bars: OhlcBar[], period: KPeriod): OhlcBar[] {
  if (period === 'day' || bars.length === 0) return bars
  const keyOf = period === 'week' ? weekKey : monthKey
  const groups = new Map<string, OhlcBar[]>()
  for (const bar of bars) {
    const key = keyOf(bar.trade_date)
    const bucket = groups.get(key)
    if (bucket) bucket.push(bar)
    else groups.set(key, [bar])
  }
  const out: OhlcBar[] = []
  for (const bucket of groups.values()) {
    const first = bucket[0]
    const last = bucket[bucket.length - 1]
    let high = -Infinity
    let low = Infinity
    let volume = 0
    let amount = 0
    let hasVol = false
    let hasAmt = false
    let turnover = 0
    let hasTurnover = false
    for (const bar of bucket) {
      const h = num(bar.high)
      const l = num(bar.low)
      if (h !== null) high = Math.max(high, h)
      if (l !== null) low = Math.min(low, l)
      const v = num(bar.volume)
      if (v !== null) {
        volume += v
        hasVol = true
      }
      const a = num(bar.amount)
      if (a !== null) {
        amount += a
        hasAmt = true
      }
      const t = num(bar.turnover)
      if (t !== null) {
        turnover += t
        hasTurnover = true
      }
    }
    out.push({
      trade_date: last.trade_date,
      open: num(first.open),
      high: high === -Infinity ? null : high,
      low: low === Infinity ? null : low,
      close: num(last.close),
      volume: hasVol ? volume : null,
      amount: hasAmt ? amount : null,
      turnover: hasTurnover ? turnover : null,
    })
  }
  return out
}

export function sma(values: Array<number | null>, period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null)
  let sum = 0
  let count = 0
  const queue: Array<number | null> = []
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    queue.push(v)
    if (v !== null) {
      sum += v
      count += 1
    }
    if (queue.length > period) {
      const old = queue.shift()
      if (old !== null && old !== undefined) {
        sum -= old
        count -= 1
      }
    }
    out[i] = queue.length === period && count === period ? sum / period : null
  }
  return out
}

export function ema(values: Array<number | null>, period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null)
  const k = 2 / (period + 1)
  let prev: number | null = null
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (v === null) {
      out[i] = null
      continue
    }
    prev = prev === null ? v : v * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

export interface MacdSeries {
  dif: Array<number | null>
  dea: Array<number | null>
  hist: Array<number | null>
}

export function macd(
  closes: Array<number | null>,
  fast = 12,
  slow = 26,
  signal = 9,
): MacdSeries {
  const emaFast = ema(closes, fast)
  const emaSlow = ema(closes, slow)
  const dif = closes.map((_, i) => {
    const a = emaFast[i]
    const b = emaSlow[i]
    return a === null || b === null ? null : a - b
  })
  const dea = ema(dif, signal)
  const hist = dif.map((d, i) => {
    const e = dea[i]
    return d === null || e === null ? null : (d - e) * 2
  })
  return { dif, dea, hist }
}

export interface KdjSeries {
  k: Array<number | null>
  d: Array<number | null>
  j: Array<number | null>
}

export function kdj(
  highs: Array<number | null>,
  lows: Array<number | null>,
  closes: Array<number | null>,
  n = 9,
  m1 = 3,
  m2 = 3,
): KdjSeries {
  const rsv: Array<number | null> = Array(closes.length).fill(null)
  for (let i = 0; i < closes.length; i += 1) {
    if (i + 1 < n) continue
    const start = i - n + 1
    let hh = -Infinity
    let ll = Infinity
    let ok = true
    for (let j = start; j <= i; j += 1) {
      const h = highs[j]
      const l = lows[j]
      if (h === null || l === null) {
        ok = false
        break
      }
      hh = Math.max(hh, h)
      ll = Math.min(ll, l)
    }
    const c = closes[i]
    if (!ok || c === null || hh === ll) {
      rsv[i] = ok && c !== null && hh === ll ? 50 : null
      continue
    }
    rsv[i] = ((c - ll) / (hh - ll)) * 100
  }

  const k: Array<number | null> = Array(closes.length).fill(null)
  const d: Array<number | null> = Array(closes.length).fill(null)
  const j: Array<number | null> = Array(closes.length).fill(null)
  let prevK: number | null = null
  let prevD: number | null = null
  for (let i = 0; i < closes.length; i += 1) {
    const r = rsv[i]
    if (r === null) continue
    const curK: number = prevK === null ? r : (prevK * (m1 - 1) + r) / m1
    const curD: number = prevD === null ? curK : (prevD * (m2 - 1) + curK) / m2
    k[i] = curK
    d[i] = curD
    j[i] = 3 * curK - 2 * curD
    prevK = curK
    prevD = curD
  }
  return { k, d, j }
}

function rollingMeanDeviation(values: Array<number | null>, period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i += 1) {
    const window = values.slice(i - period + 1, i + 1)
    if (window.some((value) => value === null)) continue
    const mean = window.reduce<number>((sum, value) => sum + (value as number), 0) / period
    out[i] = window.reduce<number>((sum, value) => sum + Math.abs((value as number) - mean), 0) / period
  }
  return out
}

function rollingStd(values: Array<number | null>, period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i += 1) {
    const window = values.slice(i - period + 1, i + 1)
    if (window.some((value) => value === null)) continue
    const mean = window.reduce<number>((sum, value) => sum + (value as number), 0) / period
    const squared = window.reduce<number>((sum, value) => sum + ((value as number) - mean) ** 2, 0)
    out[i] = period > 1 ? Math.sqrt(squared / (period - 1)) : null
  }
  return out
}

export function rsi(values: Array<number | null>, period = 14): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null)
  let previous: number | null = null
  let averageGain: number | null = null
  let averageLoss: number | null = null
  let validCloses = 0
  for (let i = 0; i < values.length; i += 1) {
    const current = values[i]
    if (current === null) continue
    validCloses += 1
    if (previous === null) {
      previous = current
      continue
    }
    const delta = current - previous
    const gain = Math.max(delta, 0)
    const loss = Math.max(-delta, 0)
    averageGain = averageGain === null ? gain : ((period - 1) * averageGain + gain) / period
    averageLoss = averageLoss === null ? loss : ((period - 1) * averageLoss + loss) / period
    previous = current
    if (validCloses < period + 1) continue
    const total = averageGain + averageLoss
    out[i] = total === 0 ? 50 : (averageGain / total) * 100
  }
  return out
}

export function trueRange(
  highs: Array<number | null>,
  lows: Array<number | null>,
  closes: Array<number | null>,
): Array<number | null> {
  const out: Array<number | null> = Array(closes.length).fill(null)
  for (let i = 1; i < closes.length; i += 1) {
    const high = highs[i]
    const low = lows[i]
    const previousClose = closes[i - 1]
    if (high === null || low === null || previousClose === null) continue
    out[i] = Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose))
  }
  return out
}

export function atr(
  highs: Array<number | null>,
  lows: Array<number | null>,
  closes: Array<number | null>,
  period: number,
): Array<number | null> {
  return sma(trueRange(highs, lows, closes), period)
}

export function roc(values: Array<number | null>, period: number): Array<number | null> {
  return values.map((value, index) => {
    const previous = index >= period ? values[index - period] : null
    if (value === null || previous === null || previous === 0) return null
    return ((value - previous) / previous) * 100
  })
}

export function williamsR(
  highs: Array<number | null>,
  lows: Array<number | null>,
  closes: Array<number | null>,
  period: number,
): Array<number | null> {
  const out: Array<number | null> = Array(closes.length).fill(null)
  for (let i = period - 1; i < closes.length; i += 1) {
    const highWindow = highs.slice(i - period + 1, i + 1)
    const lowWindow = lows.slice(i - period + 1, i + 1)
    const close = closes[i]
    if (close === null || highWindow.some((value) => value === null) || lowWindow.some((value) => value === null)) continue
    const highest = Math.max(...(highWindow as number[]))
    const lowest = Math.min(...(lowWindow as number[]))
    out[i] = highest === lowest ? 0 : -((highest - close) / (highest - lowest)) * 100
  }
  return out
}

export function cci(
  highs: Array<number | null>,
  lows: Array<number | null>,
  closes: Array<number | null>,
  period: number,
): Array<number | null> {
  const typical = closes.map((close, index) => {
    const high = highs[index]
    const low = lows[index]
    return high === null || low === null || close === null ? null : (high + low + close) / 3
  })
  const mean = sma(typical, period)
  const deviation = rollingMeanDeviation(typical, period)
  return typical.map((value, index) => {
    const base = mean[index]
    const dev = deviation[index]
    if (value === null || base === null || dev === null) return null
    return dev === 0 ? 0 : (value - base) / (0.015 * dev)
  })
}

export function obv(
  closes: Array<number | null>,
  volumes: Array<number | null>,
): Array<number | null> {
  const out: Array<number | null> = Array(closes.length).fill(null)
  let total = 0
  for (let i = 0; i < closes.length; i += 1) {
    const close = closes[i]
    const volume = volumes[i]
    if (close === null || volume === null) continue
    const previous = i > 0 ? closes[i - 1] : null
    if (previous !== null) {
      if (close > previous) total += volume
      else if (close < previous) total -= volume
    }
    out[i] = total
  }
  return out
}

export interface BollingerSeries {
  mid: Array<number | null>
  upper: Array<number | null>
  lower: Array<number | null>
}

export function bollinger(
  values: Array<number | null>,
  period = 20,
  deviations = 2,
): BollingerSeries {
  const mid = sma(values, period)
  const std = rollingStd(values, period)
  return {
    mid,
    upper: std.map((value, index) => (value === null || mid[index] === null ? null : mid[index] + value * deviations)),
    lower: std.map((value, index) => (value === null || mid[index] === null ? null : mid[index] - value * deviations)),
  }
}
