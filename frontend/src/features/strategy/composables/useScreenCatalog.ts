/** 选股工作台目录：引擎战法 + Agent 技能，挂复盘胜率/均收益/衰减。 */
import { computed, onScopeDispose, ref } from 'vue'

import { getDecay, getSkills, getStrategies, getWinRateSummary } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { Skill, StrategyInfo, WinRateSummary } from '@/shared/types/quant'

export type ScreenKind = 'engine' | 'skill'

export type ScreenCatalogItem = {
  id: string
  kind: ScreenKind
  slug: string
  name: string
  description: string
  enabled: boolean
  entryTiming?: string
  /** 复盘胜率% = 赚钱概率 */
  winRate: number | null
  /** 平均收益% */
  avgReturn: number | null
  sample: number
  wins: number
  recentWinRate: number | null
  decaySignal: string | null
  lastReviewed: string
}

function matchSummary(
  slug: string,
  name: string,
  byTag: Map<string, WinRateSummary>,
): WinRateSummary | undefined {
  return (
    byTag.get(slug) ||
    byTag.get(name) ||
    [...byTag.values()].find(
      (row) =>
        row.strategy_tag === slug ||
        row.strategy_tag === name ||
        row.strategy_tag.toLowerCase() === slug.toLowerCase(),
    )
  )
}

export function useScreenCatalog() {
  const items = ref<ScreenCatalogItem[]>([])
  const strategies = ref<StrategyInfo[]>([])
  const skills = ref<Skill[]>([])
  const loading = ref(false)
  const error = ref('')
  const kindFilter = ref<'all' | ScreenKind>('all')
  const selectedId = ref('')
  let loadSeq = 0

  onScopeDispose(() => {
    loadSeq += 1
  })

  const filtered = computed(() => {
    if (kindFilter.value === 'all') return items.value
    return items.value.filter((row) => row.kind === kindFilter.value)
  })

  const selected = computed(
    () => items.value.find((row) => row.id === selectedId.value) ?? null,
  )

  const selectedStrategy = computed(() => {
    const row = selected.value
    if (!row || row.kind !== 'engine') return null
    return strategies.value.find((s) => s.slug === row.slug) ?? null
  })

  const selectedSkill = computed(() => {
    const row = selected.value
    if (!row || row.kind !== 'skill') return null
    return skills.value.find((s) => s.slug === row.slug) ?? null
  })

  async function load(): Promise<void> {
    const seq = ++loadSeq
    loading.value = true
    error.value = ''
    try {
      const [strategyList, skillList, summary, decay] = await Promise.all([
        getStrategies().catch(() => [] as StrategyInfo[]),
        getSkills().catch(() => [] as Skill[]),
        getWinRateSummary().catch(() => [] as WinRateSummary[]),
        getDecay({ window: 20 }).catch(() => [] as Record<string, unknown>[]),
      ])

      if (seq !== loadSeq) return

      strategies.value = strategyList
      skills.value = skillList

      const byTag = new Map(summary.map((row) => [row.strategy_tag, row]))
      const decayByTag = new Map<string, { recent: number | null; signal: string }>()
      for (const row of decay) {
        const tag = String(row.strategy_tag ?? '')
        if (!tag) continue
        decayByTag.set(tag, {
          recent: typeof row.recent_win_rate === 'number' ? row.recent_win_rate : null,
          signal: String(row.signal ?? row.decay_signal ?? ''),
        })
      }

      const next: ScreenCatalogItem[] = []

      for (const s of strategyList) {
        const wr = matchSummary(s.slug, s.name, byTag)
        const dec = decayByTag.get(s.slug) || decayByTag.get(s.name)
        next.push({
          id: `engine:${s.slug}`,
          kind: 'engine',
          slug: s.slug,
          name: s.name,
          description: s.description || '',
          enabled: true,
          entryTiming: s.entry_timing,
          winRate: wr?.win_rate ?? null,
          avgReturn: wr?.avg_return ?? null,
          sample: wr?.total ?? 0,
          wins: wr?.wins ?? 0,
          recentWinRate: dec?.recent ?? null,
          decaySignal: dec?.signal || null,
          lastReviewed: wr?.last_reviewed || '',
        })
      }

      for (const sk of skillList) {
        const wr = matchSummary(sk.slug, sk.name, byTag)
        const dec = decayByTag.get(sk.slug) || decayByTag.get(sk.name)
        next.push({
          id: `skill:${sk.slug}`,
          kind: 'skill',
          slug: sk.slug,
          name: sk.name,
          description: sk.description || '',
          enabled: sk.enabled !== false,
          winRate: wr?.win_rate ?? null,
          avgReturn: wr?.avg_return ?? null,
          sample: wr?.total ?? 0,
          wins: wr?.wins ?? 0,
          recentWinRate: dec?.recent ?? null,
          decaySignal: dec?.signal || null,
          lastReviewed: wr?.last_reviewed || '',
        })
      }

      next.sort((a, b) => {
        const sa = a.sample
        const sb = b.sample
        if (sb !== sa) return sb - sa
        return a.name.localeCompare(b.name, 'zh')
      })

      items.value = next
      if (selectedId.value && !next.some((row) => row.id === selectedId.value)) {
        selectedId.value = ''
      }
      if (!selectedId.value && next.length) {
        selectedId.value = next[0].id
      }
    } catch (caught: unknown) {
      if (seq !== loadSeq) return
      error.value = toErrorMessage(caught, '加载选股技能目录失败')
      items.value = []
      strategies.value = []
      skills.value = []
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  function select(id: string): void {
    selectedId.value = id
  }

  return {
    items,
    strategies,
    skills,
    filtered,
    selected,
    selectedStrategy,
    selectedSkill,
    selectedId,
    kindFilter,
    loading,
    error,
    load,
    select,
  }
}
