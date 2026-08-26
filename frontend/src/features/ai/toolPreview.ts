/**
 * Format tool receipt previews for UI — never dump raw JSON blobs.
 *
 * `ledger_dashboard` / `ledger_positions` 这两个摘要分支对应的工具已随持仓下线删除，
 * 但**保留**：历史会话里存着它们的回执，没有摘要就会退回裸 JSON。勿随工具一起删。
 */

export function formatToolPreview(name: string | undefined | null, preview: string | undefined | null): string {
  const raw = String(preview ?? '').trim()
  if (!raw) return ''
  if (!looksLikeJson(raw)) return raw
  try {
    const data = JSON.parse(raw) as unknown
    const summary = summarizeStructured(String(name ?? ''), data)
    if (summary) return summary
  } catch {
    /* keep clipped raw below */
  }
  return clip(raw.replace(/\s+/g, ' '), 160)
}

function looksLikeJson(text: string): boolean {
  return text.startsWith('{') || text.startsWith('[')
}

function summarizeStructured(name: string, data: unknown): string {
  if (name === 'ledger_dashboard' && data && typeof data === 'object' && !Array.isArray(data)) {
    return summarizeDashboard(data as Record<string, unknown>)
  }
  if (name === 'ledger_positions' && Array.isArray(data)) {
    return summarizePositions(data)
  }
  if (Array.isArray(data)) return `${data.length} 条`
  if (data && typeof data === 'object') {
    const row = data as Record<string, unknown>
    for (const key of ['positions', 'trades', 'candidates', 'items', 'rows', 'results'] as const) {
      const value = row[key]
      if (Array.isArray(value)) return `${key} ${value.length} 条`
    }
  }
  return ''
}

function summarizeDashboard(data: Record<string, unknown>): string {
  const account = asRecord(data.account)
  const positions = Array.isArray(data.positions) ? data.positions : []
  const parts: string[] = []
  const asOf = String(data.as_of ?? '').trim()
  if (asOf) parts.push(asOf)
  parts.push(`持仓 ${positions.length} 只`)
  const cost = asNumber(account?.cost_exposure)
  if (cost != null) parts.push(`成本敞口 ${money(cost)}`)
  const today = asNumber(account?.today_realized_pnl)
  if (today != null) parts.push(`今日已实现 ${signed(today)}`)
  const unrealized = asNumber(account?.unrealized_pnl)
  if (unrealized != null) parts.push(`浮动 ${signed(unrealized)}`)
  return parts.join(' · ')
}

function summarizePositions(rows: unknown[]): string {
  const clean = rows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'))
  if (!clean.length) return '空仓'
  let cost = 0
  let unrealized = 0
  let hasUnrealized = false
  const names: string[] = []
  for (const row of clean) {
    cost += asNumber(row.cost_value) ?? 0
    const upnl = asNumber(row.unrealized_pnl)
    if (upnl != null) {
      hasUnrealized = true
      unrealized += upnl
    }
    const name = String(row.name ?? row.code ?? '').trim()
    if (name && names.length < 3) names.push(name)
  }
  const parts = [`持仓 ${clean.length} 只`, `成本 ${money(cost)}`]
  if (hasUnrealized) parts.push(`浮动 ${signed(unrealized)}`)
  if (names.length) {
    parts.push(clean.length > names.length ? `${names.join('、')} 等` : names.join('、'))
  }
  return parts.join(' · ')
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function money(value: number): string {
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function signed(value: number): string {
  const body = money(value)
  return value > 0 ? `+${body}` : body
}

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`
}
