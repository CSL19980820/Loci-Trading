/**
 * 战法足迹：某只股票被哪些战法、在哪些交易日选出过。
 *
 * 数据只有两处来源：账本候选（`/candidates/list?code=`）是事实，战法目录与定时台
 * 决定「哪些战法当前处于激活」——有启用中的 `screen:{slug}` 定时任务即算激活。
 * 目录与任务表跨股票不变，按 60 秒缓存一次，批次翻股时只重拉候选。
 */
import { computed, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'

import { listCandidates } from '@/shared/api/palace'
import { getJobs, getStrategies } from '@/shared/api/quant'
import { decisionLabel, strategyLabel as formatStrategyLabel } from '@/shared/lib/format'
import type { Candidate } from '@/shared/types/palace'
import type { Job, StrategyInfo } from '@/shared/types/quant'

export type FootprintTone = 'pick' | 'watch' | 'drop'

export interface FootprintPick {
  id: string
  date: string
  decisionText: string
  tone: FootprintTone
  score: number | null
  reason: string
  backfill: boolean
}

export interface FootprintLane {
  slug: string
  name: string
  active: boolean
  /** 按选出日倒序 */
  picks: FootprintPick[]
  latest: string
}

export interface FootprintCatalog {
  names: Map<string, string>
  active: Set<string>
}

const CATALOG_TTL_MS = 60_000
let catalogCache: { at: number; promise: Promise<FootprintCatalog> } | null = null

export function loadFootprintCatalog(): Promise<FootprintCatalog> {
  const now = Date.now()
  if (catalogCache && now - catalogCache.at < CATALOG_TTL_MS) return catalogCache.promise
  const promise = Promise.all([
    getStrategies().catch((): StrategyInfo[] => []),
    getJobs().catch((): Job[] => []),
  ]).then(([strategies, jobs]) => ({
    names: new Map(strategies.map((item) => [item.slug, item.name] as const)),
    active: new Set(
      jobs
        .filter((job) => job.enabled && job.kind === 'screen' && job.name.startsWith('screen:'))
        .map((job) => job.name.slice('screen:'.length))
        .filter(Boolean),
    ),
  }))
  catalogCache = { at: now, promise }
  promise.catch(() => {
    catalogCache = null
  })
  return promise
}

/** 候选里的战法标识：`rule_version` 即战法 slug；老记录只剩池号 `slug@date`。 */
export function candidateStrategySlug(row: Pick<Candidate, 'rule_version' | 'pool_id'>): string {
  const rule = String(row.rule_version || '').trim()
  if (rule) return rule
  return String(row.pool_id || '').split('@')[0]?.trim() ?? ''
}

function toneOf(decision: string): FootprintTone {
  const label = decisionLabel(decision)
  if (label === '精选') return 'pick'
  if (label === '观察') return 'watch'
  return 'drop'
}

function toPick(row: Candidate): FootprintPick {
  const score = row.score == null || !Number.isFinite(Number(row.score)) ? null : Number(row.score)
  return {
    id: row.id,
    date: String(row.date || '').slice(0, 10),
    decisionText: decisionLabel(row.decision),
    tone: toneOf(row.decision),
    score,
    reason: String(row.reason || ''),
    backfill: String(row.source || '').includes('backfill'),
  }
}

export function buildFootprintLanes(rows: Candidate[], catalog: FootprintCatalog | null): FootprintLane[] {
  const bySlug = new Map<string, FootprintPick[]>()
  for (const row of rows) {
    const slug = candidateStrategySlug(row)
    if (!slug || !row.date) continue
    const list = bySlug.get(slug) ?? []
    list.push(toPick(row))
    bySlug.set(slug, list)
  }
  const slugs = new Set<string>([...(catalog?.active ?? []), ...bySlug.keys()])
  const lanes: FootprintLane[] = [...slugs].map((slug) => {
    const picks = [...(bySlug.get(slug) ?? [])].sort((a, b) => b.date.localeCompare(a.date))
    return {
      slug,
      name: catalog?.names.get(slug) || formatStrategyLabel(slug),
      active: catalog?.active.has(slug) ?? false,
      picks,
      latest: picks[0]?.date ?? '',
    }
  })
  return lanes.sort(
    (a, b) =>
      Number(b.active) - Number(a.active)
      || b.latest.localeCompare(a.latest)
      || a.name.localeCompare(b.name, 'zh-CN'),
  )
}

export function useStrategyFootprints(code: MaybeRefOrGetter<string>) {
  const candidates = ref<Candidate[]>([])
  const catalog = ref<FootprintCatalog | null>(null)
  const loading = ref(false)
  let seq = 0

  async function load(target: string): Promise<void> {
    const request = ++seq
    const value = target.trim()
    if (!value) {
      candidates.value = []
      loading.value = false
      return
    }
    loading.value = true
    try {
      const [rows, cat] = await Promise.all([
        listCandidates({ code: value, limit: 500, include_backfill: true }).catch((): Candidate[] => []),
        loadFootprintCatalog().catch((): FootprintCatalog | null => null),
      ])
      if (request !== seq) return
      candidates.value = rows
      catalog.value = cat
    } finally {
      if (request === seq) loading.value = false
    }
  }

  watch(() => toValue(code), (value) => void load(value), { immediate: true })

  const lanes = computed(() => buildFootprintLanes(candidates.value, catalog.value))

  return {
    candidates,
    lanes,
    loading,
    reload: () => load(toValue(code)),
  }
}
