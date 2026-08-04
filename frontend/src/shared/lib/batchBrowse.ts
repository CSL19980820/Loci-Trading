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
