import type { SecondWaveLatest, SecondWaveTrigger } from '@/shared/api/quant_ops'

export const SECOND_WAVE_SLUG = 'dragon-second-wave'
export const SECOND_WAVE_MAX_ROWS = 8

export type SecondWaveRow = {
  code: string
  name: string
  strength: number | null
  price: number | null
  pct: number | null
  tags: string
  alerted: boolean
}

export function snapshotRows(
  snap: SecondWaveLatest | null,
  minStrength: number | null,
): SecondWaveRow[] {
  const triggered = snap?.triggered ?? []
  const pickCodes = new Set(
    (snap?.picks ?? [])
      .map((row) => String((row as { code?: unknown }).code || '').trim())
      .filter(Boolean),
  )
  const floor = minStrength ?? snap?.min_strength ?? 45
  return triggered.slice(0, SECOND_WAVE_MAX_ROWS).map((row: SecondWaveTrigger) => {
    const code = String(row.code || '').trim()
    const strength = Number.isFinite(Number(row.strength)) ? Number(row.strength) : null
    const priceRaw = row.live_price ?? row.price
    const price = Number.isFinite(Number(priceRaw)) ? Number(priceRaw) : null
    const pct = Number.isFinite(Number(row.pct)) ? Number(row.pct) : null
    const tags = Array.isArray(row.tags) ? row.tags.filter(Boolean).join(' ') : ''
    return {
      code,
      name: String(row.name || code).trim() || code,
      strength,
      price,
      pct,
      tags,
      alerted: pickCodes.has(code) || (strength != null && strength >= Number(floor)),
    }
  })
}

export function snapshotMeta(snap: SecondWaveLatest | null, loading: boolean): string {
  if (loading) return '读取扫描…'
  if (!snap?.available) return '尚未跑过 · 盘中每 5 分钟'
  const day = snap.trade_date || '—'
  const at = snap.observed_at ? snap.observed_at.replace('T', ' ').slice(11, 16) : ''
  const source = snap.quote_source ? ` · ${snap.quote_source}` : ''
  return `${day}${at ? ` ${at}` : ''}${source} · 当日现价`
}
