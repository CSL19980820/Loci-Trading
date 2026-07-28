/** 日线重采样与常见技术指标（MA / MACD / KDJ）。 */

export interface OhlcBar {
  trade_date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  amount?: number | null
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

/** 由日线合成周/月 K：开=首、高=max、低=min、收=末、量额求和。 */
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
    }
    out.push({
      trade_date: last.trade_date,
      open: num(first.open),
      high: high === -Infinity ? null : high,
      low: low === Infinity ? null : low,
      close: num(last.close),
      volume: hasVol ? volume : null,
      amount: hasAmt ? amount : null,
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

function ema(values: Array<number | null>, period: number): Array<number | null> {
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
    const start = Math.max(0, i - n + 1)
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
  let prevK = 50
  let prevD = 50
  for (let i = 0; i < closes.length; i += 1) {
    const r = rsv[i]
    if (r === null) continue
    const curK = (prevK * (m1 - 1) + r) / m1
    const curD = (prevD * (m2 - 1) + curK) / m2
    k[i] = curK
    d[i] = curD
    j[i] = 3 * curK - 2 * curD
    prevK = curK
    prevD = curD
  }
  return { k, d, j }
}
