<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { CapabilityUnavailableError, getWinRateSummary, getWinRateTrend } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { strategyLabel, strategyShortLabel } from '@/shared/lib/format'
import {
  sampleBadgeLabel,
  sampleConfidence,
  winRateDisplayTone,
  winRateStatTone,
  winRateText,
} from '@/shared/lib/winrate'
import type { WinRateSummary, WinRateTrendPoint } from '@/shared/types/quant'

/** 口径说明只写一份：顶栏 ⓘ 与表内说明共用，避免手抄出两个版本 */
const CALIBER_HINT =
  '主表取精选候选 T+5（另列 T+1/T+3），无候选样本时回退手工复盘；盘后「候选T+N跟踪」每日重算 5 个交易日窗口。下方趋势仍按手工复盘的月/周聚合。'

const summary = ref<WinRateSummary[]>([])
const chartData = ref<WinRateTrendPoint[]>([])
const granularity = ref<'month' | 'week'>('month')
const busy = ref(false)
const error = ref('')
let active = true
let requestVersion = 0

const allTags = computed(() => [...new Set(summary.value.map((row) => row.strategy_tag))])
const activeTags = ref<Set<string>>(new Set())

function toggleTag(tag: string): void {
  const next = new Set(activeTags.value)
  if (next.has(tag)) next.delete(tag)
  else next.add(tag)
  activeTags.value = next
}

const trendRows = computed(() => {
  // 单趟分组：按周粒度跑几年时周期数上百，逐周期全扫点集会退化成 O(周期×点)。
  const byPeriod = new Map<string, Record<string, WinRateTrendPoint>>()
  for (const point of chartData.value) {
    let byTag = byPeriod.get(point.period)
    if (!byTag) {
      byTag = {}
      byPeriod.set(point.period, byTag)
    }
    if (activeTags.value.has(point.strategy_tag)) byTag[point.strategy_tag] = point
  }
  return [...byPeriod.keys()]
    .sort()
    .map((period) => ({ period, byTag: byPeriod.get(period)! }) as Record<string, unknown>)
    .reverse()
})

const summaryRows = computed(() => summary.value as unknown as Record<string, unknown>[])

/** 页头读数：由主表已加载行汇总（wins/total 与行内胜率同口径），不另发请求 */
const overallSamples = computed(() =>
  summary.value.reduce((acc, row) => acc + (Number(row.total) || 0), 0),
)

const overallWinRate = computed(() => {
  if (!overallSamples.value) return null
  const wins = summary.value.reduce((acc, row) => acc + (Number(row.wins) || 0), 0)
  return Math.round((wins / overallSamples.value) * 1000) / 10
})

const overallAvgReturn = computed(() => {
  let weight = 0
  let acc = 0
  for (const row of summary.value) {
    const n = Number(row.total) || 0
    if (typeof row.avg_return === 'number' && n > 0) {
      acc += row.avg_return * n
      weight += n
    }
  }
  return weight > 0 ? acc / weight : null
})

const overallWinRateTone = computed(() => winRateStatTone(overallWinRate.value, overallSamples.value))

const overallAvgTone = computed(() => {
  if (overallAvgReturn.value == null) return ''
  return overallAvgReturn.value >= 0 ? 'up' : 'down'
})

const overallAvgText = computed(() =>
  overallAvgReturn.value == null
    ? '—'
    : `${overallAvgReturn.value >= 0 ? '+' : ''}${overallAvgReturn.value.toFixed(2)}%`,
)

const summaryColumns: BasicTableColumn[] = [
  { prop: 'strategy_tag', label: '战法', minWidth: 120, align: 'center', headerAlign: 'center', slotName: 'tag' },
  { prop: 'source', label: '口径', width: 100, align: 'center', headerAlign: 'center', slotName: 'source' },
  { prop: 'total', label: 'T+5样本', align: 'center', headerAlign: 'center', width: 100 },
  { prop: 'wins', label: '盈利次数', align: 'center', headerAlign: 'center', width: 100 },
  { prop: 'win_rate', label: 'T+5胜率', align: 'center', headerAlign: 'center', minWidth: 120, slotName: 'winRate' },
  { prop: 't1', label: 'T+1', align: 'center', headerAlign: 'center', minWidth: 90, slotName: 't1' },
  { prop: 't3', label: 'T+3', align: 'center', headerAlign: 'center', minWidth: 90, slotName: 't3' },
  { prop: 'avg_return', label: 'T+5均收益', align: 'center', headerAlign: 'center', minWidth: 110, slotName: 'avgReturn' },
  { prop: 'last_reviewed', label: '最近样本', minWidth: 120, align: 'center', headerAlign: 'center', slotName: 'lastReviewed' },
]

const trendColumns = computed<BasicTableColumn[]>(() => {
  const cols: BasicTableColumn[] = [
    {
      prop: 'period',
      label: granularity.value === 'month' ? '月份' : '周',
      width: 120,
      align: 'center',
      headerAlign: 'center',
      slotName: 'period',
    },
  ]
  for (const tag of activeTags.value) {
    cols.push({
      prop: tag,
      label: strategyShortLabel(tag),
      align: 'center',
      headerAlign: 'center',
      minWidth: 110,
      slotName: `tag_${tag}`,
    })
  }
  return cols
})

function sampleBadgeClass(total: number): string {
  return sampleConfidence(total) === 'low' ? 'sample-badge-low' : 'sample-badge-medium'
}

function horizonStats(
  row: Record<string, unknown>,
  key: string,
): { n: number; win_rate: number } | null {
  const horizons = row.horizons as
    | Record<string, { n?: number; win_rate?: number }>
    | undefined
  const stats = horizons?.[key]
  if (!stats || typeof stats.win_rate !== 'number') return null
  return { n: Number(stats.n ?? 0), win_rate: stats.win_rate }
}

function horizonWinRate(row: Record<string, unknown>, key: string): number | null {
  return horizonStats(row, key)?.win_rate ?? null
}

function horizonN(row: Record<string, unknown>, key: string): number {
  return horizonStats(row, key)?.n ?? 0
}

function tagPoint(row: Record<string, unknown>, tag: string): WinRateTrendPoint | undefined {
  const byTag = row.byTag as Record<string, WinRateTrendPoint> | undefined
  return byTag?.[tag]
}

async function loadTrend(version: number): Promise<void> {
  const tags = allTags.value
  if (!tags.length) {
    if (active && version === requestVersion) chartData.value = []
    return
  }
  const requestedGranularity = granularity.value
  try {
    const rows = await getWinRateTrend({
      granularity: requestedGranularity,
      tags: tags.join(','),
    })
    if (!active || version !== requestVersion) return
    chartData.value = rows
  } catch (e: unknown) {
    if (!active || version !== requestVersion) return
    error.value = e instanceof Error ? e.message : '加载明细失败'
  }
}

function refreshTrend(): void {
  const version = ++requestVersion
  void loadTrend(version)
}

async function reload(): Promise<void> {
  const version = ++requestVersion
  busy.value = true
  error.value = ''
  try {
    const rows = await getWinRateSummary()
    if (!active || version !== requestVersion) return
    summary.value = rows
    activeTags.value = new Set(allTags.value)
    await loadTrend(version)
  } catch (e: unknown) {
    if (!active || version !== requestVersion) return
    error.value = e instanceof CapabilityUnavailableError ? e.message : (e instanceof Error ? e.message : '加载失败')
  } finally {
    if (active && version === requestVersion) busy.value = false
  }
}

onMounted(reload)

onUnmounted(() => {
  active = false
  requestVersion += 1
})
</script>

<template>
  <div class="page-fill">
  <!--
    顶栏只剩「读数 + 操作」：页面标题由侧栏高亮的菜单项交代，正文顶上不再印一遍；
    口径全文沉进这一枚 ⓘ，不占正文行（任务 3/7）。
  -->
  <PageToolbar :note="CALIBER_HINT">
    <template #stats>
      <HeaderStat label="综合胜率" lead :tone="overallWinRateTone">
        {{ winRateText(overallWinRate) }}
      </HeaderStat>
      <HeaderStat label="样本数" :value="overallSamples || '—'" />
      <HeaderStat label="T+5 均收益" :tone="overallAvgTone">{{ overallAvgText }}</HeaderStat>
    </template>
    <template #actions>
      <el-button size="small" :disabled="busy" @click="reload">刷新</el-button>
    </template>
  </PageToolbar>

  <div class="page-scroll">
  <el-alert v-if="error" :title="error" type="error" show-icon closable class="mb" @close="error = ''" />

  <!-- 标题「综合胜率」删除：下面就是一张胜率表，遮住标题也认得出（任务 7） -->
  <Sheet margin>
    <BasicTable
      v-if="summary.length"
      :columns="summaryColumns"
      :data-source="summaryRows"
      :pagination="false"
      row-key="strategy_tag"
    >
      <template #tag="{ row }">
        <el-tooltip
          placement="top"
          :content="`${strategyLabel(String(row.strategy_tag ?? ''))} · ${row.strategy_tag}`"
        >
          <strong>{{ strategyShortLabel(String(row.strategy_tag ?? '')) }}</strong>
        </el-tooltip>
      </template>
      <template #source="{ row }">
        <span class="dim">{{ row.source === 'candidates' ? '候选T+N' : row.source === 'reviews' ? '手工复盘' : (row.source || '—') }}</span>
      </template>
      <template #winRate="{ row }">
        <span class="mono" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
          <strong>{{ winRateText(row.win_rate as number | null) }}</strong>
        </span>
        <span
          v-if="sampleBadgeLabel(Number(row.total))"
          class="sample-badge"
          :class="sampleBadgeClass(Number(row.total))"
        >{{ sampleBadgeLabel(Number(row.total)) }}</span>
      </template>
      <template #t1="{ row }">
        <span class="mono" :class="winRateDisplayTone(horizonWinRate(row, 't1'), horizonN(row, 't1'))">
          {{ winRateText(horizonWinRate(row, 't1')) }}
        </span>
      </template>
      <template #t3="{ row }">
        <span class="mono" :class="winRateDisplayTone(horizonWinRate(row, 't3'), horizonN(row, 't3'))">
          {{ winRateText(horizonWinRate(row, 't3')) }}
        </span>
      </template>
      <template #avgReturn="{ row }">
        <span
          class="mono"
          :class="row.avg_return !== null ? (Number(row.avg_return) >= 0 ? 'tone-up' : 'tone-down') : ''"
        >
          {{
            row.avg_return !== null
              ? `${Number(row.avg_return) >= 0 ? '+' : ''}${Number(row.avg_return).toFixed(2)}%`
              : '—'
          }}
        </span>
      </template>
      <template #lastReviewed="{ row }">
        <span class="mono dim">{{ row.last_reviewed || '—' }}</span>
      </template>
    </BasicTable>
    <PageBusy v-else-if="busy" label="加载胜率…" />
    <EmptyState
      v-else
      description="还没有胜率数据"
      reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
      eta="盘后「候选T+N跟踪」会自动统计"
    >
      <RouterLink to="/reviews"><el-button type="primary">看候选验证</el-button></RouterLink>
    </EmptyState>
  </Sheet>

  <Sheet title="分周期明细（复盘样本）">
    <template #actions>
      <el-select
        v-model="granularity"
        size="small"
        class="granularity-select"
        @change="refreshTrend"
      >
        <el-option label="按月" value="month" />
        <el-option label="按周" value="week" />
      </el-select>
      <el-check-tag
        v-for="tag in allTags"
        :key="tag"
        :checked="activeTags.has(tag)"
        @change="() => toggleTag(tag)"
      >
        {{ strategyShortLabel(tag) }}
      </el-check-tag>
    </template>
    <BasicTable
      v-if="chartData.length"
      :columns="trendColumns"
      :data-source="trendRows"
      :pagination="false"
      row-key="period"
    >
      <template #period="{ row }">
        <span class="mono">{{ row.period }}</span>
      </template>
      <template v-for="tag in [...activeTags]" :key="tag" #[`tag_${tag}`]="{ row }">
        <span
          class="mono"
          :class="winRateDisplayTone(tagPoint(row, tag)?.win_rate ?? null, tagPoint(row, tag)?.total ?? 0)"
        >
          {{ winRateText(tagPoint(row, tag)?.win_rate ?? null) }}
        </span>
        <span class="dim"> ({{ tagPoint(row, tag)?.total ?? 0 }})</span>
        <span
          v-if="sampleBadgeLabel(tagPoint(row, tag)?.total ?? 0)"
          class="sample-badge"
          :class="sampleBadgeClass(tagPoint(row, tag)?.total ?? 0)"
        >{{ sampleBadgeLabel(tagPoint(row, tag)?.total ?? 0) }}</span>
      </template>
    </BasicTable>
    <PageBusy v-else-if="busy" />
    <EmptyState v-else description="无周期明细" :image-size="64" />
  </Sheet>
  </div>
  </div>
</template>

<style scoped>
.granularity-select {
  width: 7rem;
  flex-shrink: 0;
}
.mb {
  margin-bottom: var(--gap-2);
}
</style>
