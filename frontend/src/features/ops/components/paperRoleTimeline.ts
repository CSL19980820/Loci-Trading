/**
 * 角色留痕 → 演进图数据（纯函数）。
 * Y 轴用离散档位，不发明盈亏数字。
 */

export const ROLE_RANK: Record<string, number> = {
  failed: 0,
  weakened: 1,
  follower: 2,
  secondary: 3,
  leader: 4,
}

export const ROLE_LABEL_CN: Record<string, string> = {
  leader: '龙头',
  secondary: '中军',
  follower: '跟风',
  weakened: '走弱',
  failed: '结构破坏',
}

export const ROLE_AXIS_LABELS = ['结构破坏', '走弱', '跟风', '中军', '龙头'] as const

export type RoleHistoryRow = {
  code?: string
  name?: string
  role?: string
  trade_date?: string
  observed_at?: string
  theme_name?: string
  role_basis?: string
}

export type RoleTimelineSeries = {
  code: string
  name: string
  /** 与 dates 对齐；无观测为 null */
  ranks: Array<number | null>
  roles: Array<string | null>
}

export type RoleTimelineModel = {
  dates: string[]
  series: RoleTimelineSeries[]
  /** 可供选择的代码（按观测密度优先） */
  codeOptions: Array<{ code: string; name: string; observations: number }>
}

function tradeDateOf(row: RoleHistoryRow): string {
  const day = String(row.trade_date || '').trim()
  if (/^\d{4}-\d{2}-\d{2}/.test(day)) return day.slice(0, 10)
  const at = String(row.observed_at || '').trim()
  if (/^\d{4}-\d{2}-\d{2}/.test(at)) return at.slice(0, 10)
  return ''
}

export function roleRank(role: string | undefined | null): number | null {
  if (!role) return null
  const rank = ROLE_RANK[String(role)]
  return rank === undefined ? null : rank
}

export function roleLabelCn(role: string | undefined | null): string {
  if (!role) return '—'
  return ROLE_LABEL_CN[String(role)] ?? String(role)
}

/** 同日同票多次观测：取 observed_at 最晚的一次。 */
export function latestRoleByCodeDate(
  history: RoleHistoryRow[],
): Map<string, RoleHistoryRow> {
  const map = new Map<string, RoleHistoryRow>()
  for (const row of history) {
    const code = String(row.code || '').trim()
    const day = tradeDateOf(row)
    if (!code || !day || !row.role) continue
    const key = `${code}|${day}`
    const prev = map.get(key)
    if (!prev) {
      map.set(key, row)
      continue
    }
    const prevAt = String(prev.observed_at || '')
    const nextAt = String(row.observed_at || '')
    if (nextAt >= prevAt) map.set(key, row)
  }
  return map
}

export function suggestTimelineCodes(
  history: RoleHistoryRow[],
  opts?: { preferCodes?: string[]; limit?: number },
): string[] {
  const preferCodes = opts?.preferCodes ?? []
  const limit = opts?.limit ?? 5
  const counts = new Map<string, { name: string; n: number }>()
  for (const row of history) {
    const code = String(row.code || '').trim()
    if (!code) continue
    const cur = counts.get(code) || { name: String(row.name || code), n: 0 }
    cur.n += 1
    if (row.name) cur.name = String(row.name)
    counts.set(code, cur)
  }
  const preferred = preferCodes
    .map((c) => String(c || '').trim())
    .filter((c) => c && counts.has(c))
  const rest = [...counts.entries()]
    .filter(([code]) => !preferred.includes(code))
    .sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0]))
    .map(([code]) => code)
  return [...new Set([...preferred, ...rest])].slice(0, Math.max(1, Math.min(limit, 8)))
}

export function buildRoleTimeline(
  history: RoleHistoryRow[],
  opts: { codes: string[] },
): RoleTimelineModel {
  const codes = opts.codes
  const byKey = latestRoleByCodeDate(history)
  const dateSet = new Set<string>()
  const counts = new Map<string, { name: string; n: number }>()

  for (const row of history) {
    const code = String(row.code || '').trim()
    const day = tradeDateOf(row)
    if (!code || !day) continue
    dateSet.add(day)
    const cur = counts.get(code) || { name: String(row.name || code), n: 0 }
    cur.n += 1
    if (row.name) cur.name = String(row.name)
    counts.set(code, cur)
  }

  const dates = [...dateSet].sort()
  const selected = codes.map((c) => String(c || '').trim()).filter(Boolean)

  const series: RoleTimelineSeries[] = selected.map((code) => {
    const meta = counts.get(code)
    const ranks: Array<number | null> = []
    const roles: Array<string | null> = []
    for (const day of dates) {
      const row = byKey.get(`${code}|${day}`)
      const role = row ? String(row.role || '') : ''
      ranks.push(roleRank(role))
      roles.push(role || null)
    }
    return {
      code,
      name: meta?.name || code,
      ranks,
      roles,
    }
  })

  const codeOptions = [...counts.entries()]
    .map(([code, meta]) => ({ code, name: meta.name, observations: meta.n }))
    .sort((a, b) => b.observations - a.observations || a.code.localeCompare(b.code))

  return { dates, series, codeOptions }
}
