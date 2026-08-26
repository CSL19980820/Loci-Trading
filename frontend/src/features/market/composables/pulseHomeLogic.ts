/** 首页盘面纯逻辑（可单测）。 */
import type { BoardRow } from '@/shared/types/quant'

export type PulseBoardTab = 'gain' | 'turnover' | 'sector'

export function localIsoDate(d = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function effectivePct(row: BoardRow): number | null {
  if (row.pct != null && Number.isFinite(Number(row.pct))) return Number(row.pct)
  if (row.local_pct != null && Number.isFinite(Number(row.local_pct))) return Number(row.local_pct)
  return null
}

/** 市场榜行按 code 索引，供轮询叠价复用、减少 codes spot 请求。 */
export function boardRowsToSpotMap(rows: BoardRow[]): Map<string, BoardRow> {
  const map = new Map<string, BoardRow>()
  for (const row of rows) {
    const code = String(row.code || '').trim()
    if (code) map.set(code, row)
  }
  return map
}

/** 涨幅榜叠 live 后按有效涨跌重排；换手榜保持服务端顺序。 */
export function rankBoardRows(rows: BoardRow[], tab: PulseBoardTab): BoardRow[] {
  if (tab === 'turnover') return rows.slice(0, 10)
  if (tab === 'sector') return []
  const sorted = [...rows].sort((a, b) => {
    const ap = effectivePct(a)
    const bp = effectivePct(b)
    if (ap == null && bp == null) return 0
    if (ap == null) return 1
    if (bp == null) return -1
    return bp - ap
  })
  return sorted.slice(0, 10)
}

export type SectorBoardRow = {
  name: string
  pct: number | null
  count: number
}

/** 库内按行业聚合涨幅（成交额加权）；供「板块」页，不是个股榜。 */
export function rankSectorRows(rows: BoardRow[], limit = 10): SectorBoardRow[] {
  const buckets = new Map<string, { weight: number; pctWeight: number; count: number }>()
  for (const row of rows) {
    const name = String(row.industry || '').trim()
    if (!name) continue
    const pct = effectivePct(row)
    if (pct == null || !Number.isFinite(pct)) continue
    const amount = row.amount != null ? Number(row.amount) : NaN
    const weight = Number.isFinite(amount) && amount > 0 ? amount : 1
    const prev = buckets.get(name) ?? { weight: 0, pctWeight: 0, count: 0 }
    prev.weight += weight
    prev.pctWeight += pct * weight
    prev.count += 1
    buckets.set(name, prev)
  }
  return [...buckets.entries()]
    .map(([name, bucket]) => ({
      name,
      pct: bucket.weight > 0 ? bucket.pctWeight / bucket.weight : null,
      count: bucket.count,
    }))
    .sort((a, b) => (b.pct ?? Number.NEGATIVE_INFINITY) - (a.pct ?? Number.NEGATIVE_INFINITY))
    .slice(0, limit)
}

/**
 * 「今日选股」锚点交易日。
 * 开盘前 last_trading_day 常已切到自然交易日，但盘后真选仍落在覆盖日（昨收）。
 */
export function screenSessionDay(input: {
  calendarToday: string
  lastTradingDay?: string | null
  coverageLastDate?: string | null
  expectedLastDate?: string | null
  liveReason?: string | null
}): string {
  const today = (input.calendarToday || '').trim()
  const coverage = (input.coverageLastDate || input.expectedLastDate || '').trim()
  const last = (input.lastTradingDay || coverage || today).trim()
  if (input.liveReason === 'before_open' && coverage && today && coverage < today) {
    return coverage
  }
  return last || today
}

/**
 * 拆分「今日选股 / 昨选今涨」对应的入库日。
 * ``sessionDay``：最近已收盘交易日（休市日用 last_trading_day，勿用自然日周六）。
 */
export function splitScreenDates(
  datesDesc: string[],
  calendarToday: string,
  sessionDay: string = calendarToday,
): { todayHit: string; ydayHit: string } {
  const session = (sessionDay || calendarToday || '').trim()
  const todayHit =
    datesDesc.find((d) => d === session) ||
    datesDesc.find((d) => d === calendarToday) ||
    datesDesc.find((d) => d >= calendarToday) ||
    ''
  const ydayHit = datesDesc.find((d) => d < (todayHit || session || calendarToday)) || ''
  return { todayHit, ydayHit }
}

/** 选入价→最新价的累计涨跌幅（%）；缺一侧则 null。 */
export function changeFromEntry(
  entry: number | null | undefined,
  latest: number | null | undefined,
): number | null {
  if (entry == null || latest == null) return null
  const e = Number(entry)
  const l = Number(latest)
  if (!(e > 0) || !Number.isFinite(l)) return null
  return ((l - e) / e) * 100
}

/** 最低价→最高价涨幅（%）；用于近选跟踪「低→高」列。 */
export function swingFromLowHigh(
  low: number | null | undefined,
  high: number | null | undefined,
): number | null {
  if (low == null || high == null) return null
  const floor = Number(low)
  const peak = Number(high)
  if (!(floor > 0) || !Number.isFinite(peak) || peak < floor) return null
  return ((peak - floor) / floor) * 100
}

/**
 * 近选跟踪锚点：优先最近已收盘日（严格早于日历今天）。
 * 当天选出的票只进「今日选股」，由 excludeTodayFromTrack 再兜底剔除。
 */
export function trackAsOfDate(
  calendarToday: string,
  sessionDay: string,
  _isTradingDay = false,
): string {
  const today = (calendarToday || '').trim()
  const session = (sessionDay || '').trim()
  if (session && (!today || session < today)) return session
  return session || today
}

/** 近选跟踪去掉选股日=当天的行（当天只在「今日选股」展示）。 */
export function excludeTodayFromTrack<T extends { date: string }>(
  rows: T[],
  calendarToday: string,
): T[] {
  const today = (calendarToday || '').trim()
  if (!today) return rows
  return rows.filter((row) => String(row.date || '').trim() !== today)
}

/** 从 CandidateOutcome.returns 取 t1/t3。 */
export function horizonReturn(
  returns: Record<string, number | null> | undefined,
  horizon: 1 | 3,
): number | null {
  if (!returns) return null
  const raw = returns[`t${horizon}`]
  if (raw == null || !Number.isFinite(Number(raw))) return null
  return Number(raw)
}

/** 近选跟踪展示优先级：现行战法靠前；同票同日只留一行。 */
const TRACK_STRATEGY_RANK: Record<string, number> = {
  'qianlong-close-v3': 10,
  'sanyuan-tail-v1': 20,
  'yangshi-tail-v1': 30,
  // 已归档对照版：仍可能出现在历史行，排到最后
  'rsi30-dip': 890,
  'qianfu-close': 891,
  'qianfu-1450': 892,
  'qianlong-tail-v1': 900,
  'lugw-haidi': 905,
  'qianlong-close': 910,
  'qianlong-close-v2': 920,
  'lugw-sanwai': 930,
  'lugw-sanwai-v2': 940,
  'lugw-chouma': 950,
}

export type TrackDedupeRow = {
  code: string
  date: string
  strategy: string
  score?: number | null
}

function trackStrategyRank(slug: string): number {
  const key = String(slug || '').trim()
  if (!key) return 800
  return TRACK_STRATEGY_RANK[key] ?? 100
}

/** 同选股日同代码只保留一行；优先现行战法，其次更高 score。 */
export function dedupeTrackRowsByDayCode<T extends TrackDedupeRow>(rows: T[]): T[] {
  const best = new Map<string, T>()
  for (const row of rows) {
    const code = String(row.code || '').trim()
    const date = String(row.date || '').trim()
    if (!code || !date) continue
    const key = `${date}|${code}`
    const prev = best.get(key)
    if (!prev) {
      best.set(key, row)
      continue
    }
    const rank = trackStrategyRank(row.strategy)
    const prevRank = trackStrategyRank(prev.strategy)
    if (rank !== prevRank) {
      if (rank < prevRank) best.set(key, row)
      continue
    }
    if ((row.score ?? -1) > (prev.score ?? -1)) best.set(key, row)
  }
  return [...best.values()]
}
