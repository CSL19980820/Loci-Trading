import type { AiChartArtifact } from '@/shared/types/ai_assistant'

/** Metadata only: never guess a stock name from the ticker. */
export function artifactIdentity(artifact: AiChartArtifact): { code: string; name: string } {
  const data = artifact.data ?? {}
  const code = String(data.code ?? data.stock_code ?? '').trim() || artifact.title?.match(/\b\d{6}\b/)?.[0] || ''
  const name = String(data.name ?? data.stock_name ?? '').trim()
  return { code, name }
}

function sameLegacyTarget(a: AiChartArtifact, b: AiChartArtifact): boolean {
  if (a.kind !== b.kind || !a.title?.trim() || a.title.trim() !== b.title?.trim()) return false
  const left = artifactIdentity(a), right = artifactIdentity(b)
  return !left.code || !right.code || left.code === right.code
}

/** Reconcile old event-ID placeholders, without collapsing independent completed charts. */
export function normalizeArtifacts(items: readonly AiChartArtifact[], active = false): AiChartArtifact[] {
  const result: AiChartArtifact[] = []
  for (const item of items) {
    let index = result.findIndex(prior => prior.id === item.id)
    if (index < 0 && item.status !== 'loading') {
      const candidates = result.map((prior, at) => prior.status === 'loading' && sameLegacyTarget(prior, item) ? at : -1).filter(at => at >= 0)
      if (candidates.length === 1) index = candidates[0]!
    }
    if (index >= 0) {
      const prior = result[index]!
      result[index] = { ...prior, ...item, title:item.title || prior.title, data:{ ...prior.data, ...item.data } }
    } else result.push(item)
  }
  return active ? result : result.map(item => item.status === 'loading'
    ? { ...item, status:'error', data:{ ...item.data, error:'本轮已结束，未收到这张图表的完整数据。' } }
    : item)
}
