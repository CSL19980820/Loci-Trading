/** 与 ledger/infrastructure/candidates_sql.py 的默认候选列表排除条件保持一致。
 * 只派生展示标签，不改写历史记录的 source / date / created_at。
 */
export function isHistoricalCandidate(
  row: { source?: unknown; date?: unknown; created_at?: unknown } | null | undefined,
): boolean {
  const source = String(row?.source ?? '').toLowerCase()
  if (source.includes('backfill') || source.endsWith(':history')) return true
  return source.startsWith('api:screen')
    && String(row?.created_at ?? '').replaceAll('T', ' ').slice(0, 10) !== String(row?.date ?? '')
}
