/**
 * 同批条目构造辅助：列表页开批时用。
 */
import type { BatchItem } from '@/shared/stores/batchBrowse'

export function toBatchItems(
  rows: Array<{ code?: string | null; name?: string | null; pct?: number | null; changePct?: number | null }>,
): BatchItem[] {
  return rows
    .map((row) => ({
      code: String(row.code || '').trim(),
      name: row.name ? String(row.name) : undefined,
      pct: row.pct ?? row.changePct ?? null,
    }))
    .filter((row) => Boolean(row.code))
}

/** 拆「策略名 · YYYY-MM-DD」，避免侧栏/顶栏把选股日截断藏掉。 */
export function parseBatchSource(source: string): {
  title: string
  date: string | null
  full: string
} {
  const full = String(source || '').trim() || '本批'
  const match = full.match(/^(.*?)(?:\s*[·•]\s*)(\d{4}-\d{2}-\d{2})\s*$/)
  if (!match) return { title: full, date: null, full }
  const title = match[1]?.trim() || '本批'
  return { title, date: match[2] ?? null, full }
}

/**
 * 侧栏涨跌展示。契约：pct 是百分数点（-0.71 → -0.71%），与行情台/盘面一致。
 * 不要用「|x|≤1 再 ×100」——会把 -0.71% 误显示成 -71%。
 */
export function formatBatchPct(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return ''
  const n = Number(pct)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

/** 有名称只显示名称；名称尾部若误拼代码则剥掉。无名称才回退代码。 */
export function batchItemLabel(item: Pick<BatchItem, 'code' | 'name'>): string {
  const code = String(item.code || '').trim()
  const raw = String(item.name || '').trim()
  if (!raw) return code
  if (!code) return raw
  if (raw === code) return code
  const stripped = raw.replace(new RegExp(`(?:\\s*[/·\\-]?\\s*)?${code}$`), '').trim()
  return stripped || raw
}
