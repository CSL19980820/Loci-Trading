/**
 * 战法足迹：某只股票被哪些战法、在哪些交易日选出过。
 *
 * 数据只有两处来源：账本候选（`/candidates/list?code=&slim=true`）是事实，战法目录与
 * 定时台决定「哪些战法当前处于激活」——有启用中的 `screen:{slug}` 定时任务即算激活。
 * 两边都按精确 slug 对齐：候选的 `rule_version` 会被后端归一成中文展示名，不能当键。
 * 目录与任务表跨股票不变，按「账号 × 租户」缓存 60 秒，批次翻股时只重拉候选。
 */
import { computed, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'

import { listCandidates } from '@/shared/api/palace'
import { getJobs, getStrategies } from '@/shared/api/quant'
import {
  decisionLabel,
  decisionTone,
  strategyLabel as formatStrategyLabel,
  type DecisionTone,
} from '@/shared/lib/format'
import { useUserStore } from '@/shared/stores/user'
import type { Candidate } from '@/shared/types/palace'
import type { Job, StrategyInfo } from '@/shared/types/quant'

export type FootprintTone = DecisionTone

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
  /** 按选出日倒序；同一战法同一天只留一条（取裁决最强的那条） */
  picks: FootprintPick[]
  latest: string
}

export interface FootprintCatalog {
  names: Map<string, string>
  active: Set<string>
}

const CATALOG_TTL_MS = 60_000
const catalogCache = new Map<string, { at: number; promise: Promise<FootprintCatalog> }>()

export function loadFootprintCatalog(scope: string): Promise<FootprintCatalog> {
  const now = Date.now()
  const hit = catalogCache.get(scope)
  if (hit && now - hit.at < CATALOG_TTL_MS) return hit.promise
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
  catalogCache.set(scope, { at: now, promise })
  promise.catch(() => {
    catalogCache.delete(scope)
  })
  return promise
}

/**
 * 候选里的精确战法 slug。优先 `strategy_slug`（与定时任务同一个键）；
 * 老记录没有时退回 `rule_version`，再退回池号 `slug@date` 的前半段。
 */
export function candidateStrategySlug(
  row: Pick<Candidate, 'rule_version' | 'pool_id'> & { strategy_slug?: string },
): string {
  const exact = String(row.strategy_slug || '').trim()
  if (exact) return exact
  const rule = String(row.rule_version || '').trim()
  if (rule) return rule
  return String(row.pool_id || '').split('@')[0]?.trim() ?? ''
}

const TONE_RANK: Record<FootprintTone, number> = { pick: 2, watch: 1, drop: 0 }

function toPick(row: Candidate): FootprintPick {
  const score = row.score == null || !Number.isFinite(Number(row.score)) ? null : Number(row.score)
  return {
    id: row.id,
    date: String(row.date || '').slice(0, 10),
    decisionText: decisionLabel(row.decision),
    tone: decisionTone(row.decision),
    score,
    reason: String(row.reason || ''),
    backfill: String(row.source || '').includes('backfill'),
  }
}

export function buildFootprintLanes(rows: Candidate[], catalog: FootprintCatalog | null): FootprintLane[] {
  const bySlug = new Map<string, Map<string, FootprintPick>>()
  for (const row of rows) {
    const slug = candidateStrategySlug(row)
    if (!slug || !row.date) continue
    const pick = toPick(row)
    const days = bySlug.get(slug) ?? new Map<string, FootprintPick>()
    const current = days.get(pick.date)
    // 同日重跑或多时点：保留裁决最强的一条，实盘优先于回填
    if (
      !current
      || TONE_RANK[pick.tone] > TONE_RANK[current.tone]
      || (TONE_RANK[pick.tone] === TONE_RANK[current.tone] && current.backfill && !pick.backfill)
    ) {
      days.set(pick.date, pick)
    }
    bySlug.set(slug, days)
  }
  const slugs = new Set<string>([...(catalog?.active ?? []), ...bySlug.keys()])
  const lanes: FootprintLane[] = [...slugs].map((slug) => {
    const picks = [...(bySlug.get(slug)?.values() ?? [])].sort((a, b) => b.date.localeCompare(a.date))
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
  const userStore = useUserStore()
  const candidates = ref<Candidate[]>([])
  const catalog = ref<FootprintCatalog | null>(null)
  const loading = ref(false)
  let seq = 0

  /** 缓存分区：同一浏览器里换账号 / 换租户视角，不能读到上一位的战法与定时表 */
  const scope = computed(() => {
    const user = userStore.user
    return `${user?.id ?? ''}:${user?.view_tenant_id || user?.tenant_id || ''}`
  })

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
        listCandidates({ code: value, limit: 500, include_backfill: true, slim: true }).catch((): Candidate[] => []),
        loadFootprintCatalog(scope.value).catch((): FootprintCatalog | null => null),
      ])
      if (request !== seq) return
      candidates.value = rows
      catalog.value = cat
    } finally {
      if (request === seq) loading.value = false
    }
  }

  watch(
    () => [toValue(code), scope.value] as const,
    ([value]) => void load(value),
    { immediate: true },
  )

  const lanes = computed(() => buildFootprintLanes(candidates.value, catalog.value))

  return {
    candidates,
    lanes,
    loading,
    reload: () => load(toValue(code)),
  }
}
