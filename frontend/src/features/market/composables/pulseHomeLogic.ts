/** 首页盘面纯逻辑（可单测）。 */
import type { BoardRow } from '@/shared/types/quant'

export type PulseBoardTab = 'gain' | 'turnover' | 'loss'

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

/** 涨跌榜叠 live 后按有效涨跌重排；换手榜保持服务端顺序。 */
export function rankBoardRows(rows: BoardRow[], tab: PulseBoardTab): BoardRow[] {
  if (tab === 'turnover') return rows.slice(0, 10)
  const sorted = [...rows].sort((a, b) => {
    const ap = effectivePct(a)
    const bp = effectivePct(b)
    if (ap == null && bp == null) return 0
    if (ap == null) return 1
    if (bp == null) return -1
    return tab === 'loss' ? ap - bp : bp - ap
  })
  return sorted.slice(0, 10)
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
  'qianlong-tail-v1': 20,
  'sanyuan-tail-v1': 30,
  'lugw-haidi': 40,
  'rsi30-dip': 50,
  // 已归档对照版：仍可能出现在历史行，排到最后
  'qianlong-close': 900,
  'qianlong-close-v2': 910,
  'lugw-sanwai': 920,
  'lugw-sanwai-v2': 930,
  'lugw-chouma': 940,
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
