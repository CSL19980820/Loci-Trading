<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { signedPct, strategyLabel, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateSummary } from '@/shared/types/quant'

/**
 * 综合层用同一张表比较战法；行末按钮提供键盘可达的样本入口。
 */
const props = defineProps<{
  rows: WinRateSummary[]
  activeTag?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  select: [tag: string]
}>()

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'strategy_tag', label: '战法', minWidth: 140, slotName: 'tag' },
  { prop: 'source', label: '口径', width: 84, slotName: 'source' },
  { prop: 'win_rate', label: 'T+5 胜率', width: 160, slotName: 'winRate' },
  { prop: 'avg_return', label: 'T+5 均收益', width: 100, align: 'right', headerAlign: 'right', slotName: 'avgReturn' },
  { prop: 't1', label: 'T+1 胜率', width: 88, align: 'right', headerAlign: 'right', slotName: 't1' },
  { prop: 't3', label: 'T+3 胜率', width: 88, align: 'right', headerAlign: 'right', slotName: 't3' },
  { prop: 'best_horizon', label: '最佳持有期', width: 160, slotName: 'bestHorizon' },
  { prop: 'observing', label: '观察中', width: 72, align: 'right', headerAlign: 'right', slotName: 'observing' },
  { prop: 'last_reviewed', label: '最近样本', minWidth: 104, align: 'right', headerAlign: 'right', slotName: 'lastReviewed' },
  { prop: 'action', label: '样本', width: 72, align: 'center', headerAlign: 'center', slotName: 'action' },
]

function sourceLabel(source: unknown): string {
  if (source === 'candidates') return '候选T+N'
  if (source === 'reviews') return '手工复盘'
  return String(source || '—')
}

function horizonStat(row: Record<string, unknown>, key: string): { n: number; win_rate: number } | null {
  const horizons = row.horizons as Record<string, { n?: number; win_rate?: number }> | undefined
  const stat = horizons?.[key]
  if (!stat || typeof stat.win_rate !== 'number') return null
  return { n: Number(stat.n ?? 0), win_rate: stat.win_rate }
}

function bestHorizon(row: Record<string, unknown>) {
  return row.best_horizon as { horizon?: number; n?: number; win_rate?: number; avg?: number } | null
}

function rowClass(data: { row: Record<string, unknown> }): string {
  const classes = ['is-clickable', 'cmp-row']
  if (data.row.strategy_tag === props.activeTag) classes.push('is-active-row')
  return classes.join(' ')
}


function toneOf(value: unknown): string {
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return 'dim'
  return n >= 0 ? 'tone-up' : 'tone-down'
}
</script>

<template>
  <div class="cmp-container" :aria-busy="busy">
    <!-- 下部详细对比数据表 -->
    <div class="cmp-table-wrap">
      <BasicTable
        :columns="columns"
        :data-source="tableRows"
        :loading="busy"
        :pagination="false"
        :row-class-name="rowClass"
        height="100%"
        row-key="strategy_tag"
        empty-text="还没有胜率数据"
        empty-reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
        @row-click="(row: Record<string, unknown>) => emit('select', String(row.strategy_tag ?? ''))"
      >
        <template #tag="{ row }">
          <el-tooltip placement="top" :content="`${strategyLabel(String(row.strategy_tag ?? ''))} · ${row.strategy_tag}`">
            <div class="cmp-tag-cell">
              <strong class="cmp-tag-title">{{ strategyShortLabel(String(row.strategy_tag ?? '')) }}</strong>
            </div>
          </el-tooltip>
        </template>
        <template #source="{ row }">
          <span class="dim cmp-source-text">{{ sourceLabel(row.source) }}</span>
        </template>
        <template #winRate="{ row }">
          <div class="cmp-meter">
            <div class="cmp-meter__header">
              <strong class="mono cmp-meter__rate" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
                {{ winRateText(row.win_rate as number | null) }}
              </strong>
              <span class="mono dim cmp-meter__count">{{ row.wins }}/{{ row.total }}</span>
              <UiBadge v-if="sampleBadgeLabel(Number(row.total))" :variant="Number(row.total) < 10 ? 'secondary' : 'warn'">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </UiBadge>
            </div>
          </div>
        </template>
        <template #avgReturn="{ row }">
          <span class="mono cmp-return-text" :class="toneOf(row.avg_return)">
            {{ signedPct(row.avg_return as number | null) }}
          </span>
        </template>
        <template #t1="{ row }">
          <span class="mono" :class="winRateDisplayTone(horizonStat(row, 't1')?.win_rate ?? null, horizonStat(row, 't1')?.n ?? 0)">
            {{ winRateText(horizonStat(row, 't1')?.win_rate ?? null) }}
          </span>
        </template>
        <template #t3="{ row }">
          <span class="mono" :class="winRateDisplayTone(horizonStat(row, 't3')?.win_rate ?? null, horizonStat(row, 't3')?.n ?? 0)">
            {{ winRateText(horizonStat(row, 't3')?.win_rate ?? null) }}
          </span>
        </template>
        <template #bestHorizon="{ row }">
          <div v-if="bestHorizon(row)" class="cmp-best-pill">
            <span class="cmp-best-tag mono">T+{{ bestHorizon(row)?.horizon }}</span>
            <span class="mono cmp-best-rate" :class="winRateDisplayTone(bestHorizon(row)?.win_rate ?? null, bestHorizon(row)?.n ?? 0)">
              {{ winRateText(bestHorizon(row)?.win_rate ?? null) }}
            </span>
            <span class="mono cmp-best-avg" :class="toneOf(bestHorizon(row)?.avg)">
              {{ signedPct(bestHorizon(row)?.avg ?? null) }}
            </span>
          </div>
          <span v-else class="dim">样本不足</span>
        </template>
        <template #observing="{ row }">
          <span class="mono dim">{{ Number(row.observing ?? 0) || '—' }}</span>
        </template>
        <template #lastReviewed="{ row }">
          <span class="mono dim">{{ row.last_reviewed || '—' }}</span>
        </template>
        <template #action="{ row }">
          <el-button text size="small" :icon="ArrowRight" :aria-label="`查看${strategyShortLabel(String(row.strategy_tag))}样本`" title="查看样本证据" @click.stop="emit('select', String(row.strategy_tag))" />
        </template>
        <template #empty>
          <EmptyState
            description="还没有胜率数据"
            reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
            eta="盘后「候选T+N跟踪」会自动统计"
          >
            <RouterLink to="/reviews"><el-button type="primary">看候选验证</el-button></RouterLink>
          </EmptyState>
        </template>
      </BasicTable>
    </div>
  </div>
</template>

<style scoped src="./WinRateCompareTable.css"></style>
