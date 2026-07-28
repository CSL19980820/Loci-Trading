<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { CapabilityUnavailableError, getWinRateSummary, getWinRateTrend } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import {
  sampleBadgeLabel,
  sampleConfidence,
  winRateDisplayTone,
  winRateText,
} from '@/shared/lib/winrate'
import type { WinRateSummary, WinRateTrendPoint } from '@/shared/types/quant'

const summary = ref<WinRateSummary[]>([])
const chartData = ref<WinRateTrendPoint[]>([])
const granularity = ref<'month' | 'week'>('month')
const busy = ref(false)
const error = ref('')

const allTags = computed(() => [...new Set(summary.value.map((row) => row.strategy_tag))])
const activeTags = ref<Set<string>>(new Set())

function toggleTag(tag: string): void {
  const next = new Set(activeTags.value)
  if (next.has(tag)) next.delete(tag)
  else next.add(tag)
  activeTags.value = next
}

const trendRows = computed(() => {
  const periods = [...new Set(chartData.value.map((p) => p.period))].sort()
  return periods.map((period) => {
    const byTag: Record<string, WinRateTrendPoint> = {}
    for (const point of chartData.value) {
      if (point.period === period && activeTags.value.has(point.strategy_tag)) {
        byTag[point.strategy_tag] = point
      }
    }
    return { period, byTag }
  }).reverse()
})

const pageSubtitle = computed(() => {
  if (!summary.value.length) return '复盘样本'
  return `复盘样本 · ${summary.value.length} 个战法`
})

function sampleBadgeClass(total: number): string {
  return sampleConfidence(total) === 'low' ? 'sample-badge-low' : 'sample-badge-medium'
}

async function loadTrend(): Promise<void> {
  if (!allTags.value.length) return
  try {
    chartData.value = await getWinRateTrend({
      granularity: granularity.value,
      tags: allTags.value.join(','),
    })
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载明细失败'
  }
}

async function reload(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    summary.value = await getWinRateSummary()
    activeTags.value = new Set(allTags.value)
    await loadTrend()
  } catch (e: unknown) {
    error.value = e instanceof CapabilityUnavailableError ? e.message : (e instanceof Error ? e.message : '加载失败')
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>

<template>
  <PageHeader title="胜率统计" :subtitle="pageSubtitle">
    <el-select v-model="granularity" style="width: 7rem" @change="loadTrend">
      <el-option label="按月" value="month" />
      <el-option label="按周" value="week" />
    </el-select>
    <el-button :disabled="busy" @click="reload">刷新</el-button>
  </PageHeader>

  <el-alert v-if="error" :title="error" type="error" show-icon closable class="mb" @close="error = ''" />

  <el-alert
    type="info"
    show-icon
    :closable="false"
    class="mb source-alert"
    title="口径说明"
  >
    <p class="source-copy">
      本页胜率均来自<strong>复盘样本</strong>（复盘里填写了收益率的记录），与总览「交割已实现」胜率不是同一套数。
      笔数少于 5 时仅供参考，不宜过度解读。
    </p>
  </el-alert>

  <Sheet title="综合胜率（复盘样本 · 全时段）" margin>
    <el-table v-if="summary.length" :data="summary" size="small">
      <el-table-column label="战法" min-width="120">
        <template #default="{ row }"><strong>{{ row.strategy_tag }}</strong></template>
      </el-table-column>
      <el-table-column label="复盘总数" align="right" width="100" prop="total" />
      <el-table-column label="盈利次数" align="right" width="100" prop="wins" />
      <el-table-column label="复盘胜率" align="right" width="130">
        <template #default="{ row }">
          <span class="mono" :class="winRateDisplayTone(row.win_rate, row.total)">
            <strong>{{ winRateText(row.win_rate) }}</strong>
          </span>
          <span
            v-if="sampleBadgeLabel(row.total)"
            class="sample-badge"
            :class="sampleBadgeClass(row.total)"
          >{{ sampleBadgeLabel(row.total) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="平均收益" align="right" width="110">
        <template #default="{ row }">
          <span
            class="mono"
            :class="row.avg_return !== null ? (row.avg_return >= 0 ? 'tone-up' : 'tone-down') : ''"
          >
            {{ row.avg_return !== null ? `${row.avg_return >= 0 ? '+' : ''}${row.avg_return.toFixed(2)}%` : '—' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="最近复盘" width="120">
        <template #default="{ row }"><span class="mono dim">{{ row.last_reviewed || '—' }}</span></template>
      </el-table-column>
    </el-table>
    <EmptyState
      v-else
      description="还没有胜率数据"
      reason="复盘记录缺少收益字段"
      eta="补收益后刷新"
    >
      <RouterLink to="/reviews/records"><el-button type="primary">去补复盘</el-button></RouterLink>
    </EmptyState>
  </Sheet>

  <Sheet title="分周期明细（复盘样本）">
    <template #actions>
      <el-check-tag
        v-for="tag in allTags"
        :key="tag"
        :checked="activeTags.has(tag)"
        @change="() => toggleTag(tag)"
      >
        {{ tag }}
      </el-check-tag>
    </template>
    <el-table v-if="chartData.length" :data="trendRows" size="small">
      <el-table-column :label="granularity === 'month' ? '月份' : '周'" width="120">
        <template #default="{ row }"><span class="mono">{{ row.period }}</span></template>
      </el-table-column>
      <el-table-column v-for="tag in [...activeTags]" :key="tag" :label="tag" align="right" min-width="110">
        <template #default="{ row }">
          <span
            class="mono"
            :class="winRateDisplayTone(row.byTag[tag]?.win_rate ?? null, row.byTag[tag]?.total ?? 0)"
          >
            {{ winRateText(row.byTag[tag]?.win_rate ?? null) }}
          </span>
          <span class="dim"> ({{ row.byTag[tag]?.total ?? 0 }})</span>
          <span
            v-if="sampleBadgeLabel(row.byTag[tag]?.total ?? 0)"
            class="sample-badge"
            :class="sampleBadgeClass(row.byTag[tag]?.total ?? 0)"
          >{{ sampleBadgeLabel(row.byTag[tag]?.total ?? 0) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <PageBusy v-else-if="busy" />
    <EmptyState v-else description="无周期明细" :image-size="64" />
    <p class="form-hint">
      括号内为该周期复盘笔数。胜率 = 正收益次数 / 总次数（复盘样本口径）。
      笔数少于 5 时仅供参考。
    </p>
  </Sheet>
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}

.source-alert {
  margin-bottom: 0.65rem;
}

.source-copy {
  margin: 0.25rem 0 0;
  font-size: 0.85rem;
  line-height: 1.55;
  color: var(--muted);
}

.source-copy strong {
  font-weight: 650;
  color: var(--ink);
}
</style>
