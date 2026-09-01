/** 本机市场货架：数据源 · 量化战法 · Skills，全部来自本机目录。 */
import { computed, onScopeDispose, ref } from 'vue'

import {
  fetchLanesCatalog,
  getAkshareSources,
  getSkills,
  getStrategies,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import { entryTimingLabel, strategyLabel } from '@/shared/lib/format'
import type {
  AkshareCatalogSource,
  LaneProvider,
  Skill,
  StrategyInfo,
} from '@/shared/types/quant'

export type MarketKind = 'source' | 'strategy' | 'skill'
export type MarketTrust = 'official' | 'local'
export type MarketTab = 'browse' | 'installed' | 'publish'

export type MarketPackage = {
  id: string
  kind: MarketKind
  slug: string
  name: string
  description: string
  version: string
  trust: MarketTrust
  installed: boolean
  enabled: boolean
  /** 契约徽标文案 */
  badges: string[]
  removable: boolean
  editable?: boolean
  source_kind?: string
  /** 数据源可用工具数；后端提供后覆盖「线路条数」口径 */
  toolCount?: number
  /** 数据源站点，仅供人核对出处 */
  baseUrl?: string
}

export const KIND_LABEL: Record<MarketKind, string> = {
  source: '数据源',
  strategy: '量化战法',
  skill: 'Skills',
}

export function parseMarketKind(raw: unknown): MarketKind | 'all' {
  const value = String(raw || 'all')
  if (value === 'source' || value === 'strategy' || value === 'skill') return value
  return 'all'
}

export function parseMarketTab(raw: unknown): MarketTab {
  const value = String(raw || 'browse')
  if (value === 'installed' || value === 'publish') return value
  return 'browse'
}

/**
 * 货架名一律中文。后端 `name` 缺失、或它本身就是 slug 形状
 * （`sanyuan-tail-v1`）时退回共享词表，货架、详情弹窗与卸载确认里都不会
 * 再冒出英文编码。
 */
function displayName(name: string | null | undefined, slug: string): string {
  const text = String(name || '').trim()
  if (text && !/^[a-z0-9][a-z0-9._-]*$/.test(text)) return text
  return strategyLabel(slug || text)
}

function fromStrategy(row: StrategyInfo): MarketPackage {
  return {
    id: `strategy:${row.slug}`,
    kind: 'strategy',
    slug: row.slug,
    name: displayName(row.name, row.slug),
    description: row.description || '',
    version: 'bundled',
    trust: 'official',
    installed: true,
    enabled: true,
    badges: [
      row.source_kind === 'builtin' ? '内置' : '公式',
      entryTimingLabel(row.entry_timing),
    ],
    removable: false,
    editable: row.editable === true,
    source_kind: row.source_kind ?? 'builtin',
  }
}

function fromSkill(row: Skill): MarketPackage {
  const badges: string[] = []
  if (row.version) badges.push(`版本 ${row.version}`)
  if (row.allowed_tools?.length) badges.push(`工具 ${row.allowed_tools.length}`)
  if (row.agents?.length) badges.push(`智能体 ${row.agents.length}`)
  if (row.policy === 'trading_voice') badges.push('交易口径')
  return {
    id: `skill:${row.slug}`,
    kind: 'skill',
    slug: row.slug,
    name: displayName(row.name, row.slug),
    description: row.description || '',
    version: row.version || '—',
    trust: 'local',
    installed: true,
    enabled: row.enabled !== false,
    badges,
    removable: true,
  }
}

/** 数据源契约只报工具数；后端未给出时回落线路条数。 */
function sourceContractBadge(toolCount: number | undefined, laneCount: number): string {
  if (toolCount === undefined) return `${laneCount} 条线路`
  return `工具 ${toolCount}`
}

function fromProvider(row: LaneProvider, toolCount?: number): MarketPackage {
  const laneCount = (row.lanes || []).length
  return {
    id: `source:${row.id}`,
    kind: 'source',
    slug: row.id,
    name: row.label,
    description: row.description || '',
    version: 'bundled',
    trust: 'official',
    installed: true,
    enabled: row.enabled !== false,
    badges: [sourceContractBadge(toolCount, laneCount)],
    removable: false,
    toolCount,
    baseUrl: row.base_url || '',
  }
}

export function useMarketCatalog() {
  const items = ref<MarketPackage[]>([])
  const loading = ref(false)
  const error = ref('')
  const kindFilter = ref<MarketKind | 'all'>('all')
  const selectedId = ref('')
  let loadSeq = 0

  onScopeDispose(() => {
    loadSeq += 1
  })

  const filtered = computed(() => {
    if (kindFilter.value === 'all') return items.value
    return items.value.filter((row) => row.kind === kindFilter.value)
  })

  const installed = computed(() => filtered.value.filter((row) => row.installed))

  const selected = computed(
    () => items.value.find((row) => row.id === selectedId.value) ?? null,
  )

  const counts = computed(() => ({
    all: items.value.length,
    source: items.value.filter((r) => r.kind === 'source').length,
    strategy: items.value.filter((r) => r.kind === 'strategy').length,
    skill: items.value.filter((r) => r.kind === 'skill').length,
  }))

  function select(id: string): void {
    selectedId.value = id
  }

  async function load(): Promise<void> {
    const seq = ++loadSeq
    loading.value = true
    error.value = ''
    try {
      const [strategies, skills, lanes, sources] = await Promise.all([
        getStrategies().catch(() => [] as StrategyInfo[]),
        getSkills().catch(() => [] as Skill[]),
        fetchLanesCatalog().catch(() => ({ lanes: [], providers: [] as LaneProvider[] })),
        // 没装 akshare 时数不出工具，回落线路条数即可，不该拖垮整个货架
        getAkshareSources().catch(() => ({ sources: [] as AkshareCatalogSource[] })),
      ])
      if (seq !== loadSeq) return

      const toolCounts = new Map((sources.sources || []).map((s) => [s.id, s.count]))
      const next: MarketPackage[] = [
        ...strategies.map(fromStrategy),
        ...skills.map(fromSkill),
        ...(lanes.providers || []).map((row) => fromProvider(row, toolCounts.get(row.id))),
      ]
      next.sort((a, b) => {
        const kindOrder = { strategy: 0, skill: 1, source: 2 } as const
        const d = kindOrder[a.kind] - kindOrder[b.kind]
        if (d !== 0) return d
        return a.name.localeCompare(b.name, 'zh')
      })
      items.value = next
      if (selectedId.value && !next.some((row) => row.id === selectedId.value)) {
        selectedId.value = ''
      }
    } catch (caught: unknown) {
      if (seq !== loadSeq) return
      error.value = toErrorMessage(caught, '加载市场货架失败')
      items.value = []
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  return {
    items,
    filtered,
    installed,
    selected,
    selectedId,
    kindFilter,
    loading,
    error,
    counts,
    select,
    load,
  }
}
