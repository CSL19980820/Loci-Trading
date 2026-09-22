<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Trophy } from '@lucide/vue'
import { useMediaQuery } from '@vueuse/core'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { signedPct, strategyLabel, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateSummary } from '@/shared/types/quant'

/**
 * 综合层：同一张表比较战法。
 * 桌面：战法（名称 + 口径两行）· T+5 胜率（大数 + n/total + 样本角标）· 均收益 · T+1 · T+3 · 最佳持有期 · 观察中 · 最近样本 · →
 * 手机：卡片列表——名称 + 胜率大数 + 一行「n/total · 均收益 · 最佳 T+N」，整卡可点。
 */
const props = defineProps<{
  rows: WinRateSummary[]
  names?: Map<string, string>
  activeTag?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  select: [tag: string]
}>()

const isMobile = useMediaQuery('(max-width: 640px)')
const fillDesktop = useMediaQuery('(min-width:1024px) and (min-height:600px)')

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'strategy_tag', label: '战法', minWidth: 170, slotName: 'tag' },
  { prop: 'win_rate', label: 'T+5 胜率', minWidth: 170, slotName: 'winRate' },
  { prop: 'avg_return', label: 'T+5 均收益', width: 104, align: 'right', headerAlign: 'right', slotName: 'avgReturn' },
  { prop: 't1', label: 'T+1', width: 84, align: 'right', headerAlign: 'right', slotName: 't1' },
  { prop: 't3', label: 'T+3', width: 84, align: 'right', headerAlign: 'right', slotName: 't3' },
  { prop: 'best_horizon', label: '最佳持有期', minWidth: 170, slotName: 'bestHorizon' },
  { prop: 'observing', label: '观察中', width: 80, align: 'right', headerAlign: 'right', slotName: 'observing' },
  { prop: 'last_reviewed', label: '最近样本', width: 112, align: 'right', headerAlign: 'right', slotName: 'lastReviewed' },
  { prop: 'action', label: '', width: 48, align: 'center', headerAlign: 'center', slotName: 'action' },
]

function sourceLabel(source: unknown): string {
  if (source === 'candidates') return '候选 T+N'
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
  if (value === null || value === undefined || !Number.isFinite(n)) return 'cmp-dim'
  return n >= 0 ? 'tone-up' : 'tone-down'
}

/** 样本量角标：<5 样本不足（中性）、5–29 初步（警示浅底）、≥30 不标 */
function sampleVariant(total: number): 'secondary' | 'warn' {
  return total < 5 ? 'secondary' : 'warn'
}

function select(row: Record<string, unknown>): void {
  emit('select', String(row.strategy_tag ?? ''))
}
</script>

<template>
  <div class="cmp-container" :aria-busy="busy">
    <!-- 手机：卡片列表 -->
    <template v-if="isMobile">
      <ul v-if="rows.length" class="cmp-cards" aria-label="战法横向对比">
        <li
          v-for="row in tableRows"
          :key="String(row.strategy_tag)"
          class="cmp-card"
          :class="{ 'is-active': row.strategy_tag === activeTag }"
          tabindex="0"
          role="button"
          :aria-label="`查看${strategyShortLabel(String(row.strategy_tag ?? ''), names)}样本`"
          @click="select(row)"
          @keydown.enter.prevent="select(row)"
        >
          <div class="cmp-card__main">
            <div class="cmp-card__name">
              <strong>{{ strategyShortLabel(String(row.strategy_tag ?? ''), names) }}</strong>
              <UiBadge v-if="sampleBadgeLabel(Number(row.total))" :variant="sampleVariant(Number(row.total))">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </UiBadge>
            </div>
            <div class="cmp-card__sub">
              <span class="cmp-dim">{{ sourceLabel(row.source) }}</span>
              <span class="cmp-num">{{ row.wins }}/{{ row.total }}</span>
              <span class="cmp-num" :class="toneOf(row.avg_return)">均 {{ signedPct(row.avg_return as number | null) }}</span>
              <span v-if="bestHorizon(row)" class="cmp-num cmp-dim">最佳 T+{{ bestHorizon(row)?.horizon }}</span>
            </div>
          </div>
          <div class="cmp-card__num">
            <span class="cmp-card__big cmp-num" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
              {{ winRateText(row.win_rate as number | null) }}
            </span>
            <span class="cmp-card__small">T+5 胜率</span>
          </div>
        </li>
      </ul>
      <EmptyState
        v-else-if="!busy"
        class="cmp-empty"
        description="还没有胜率数据"
        reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
        :icon="Trophy"
      >
        <RouterLink to="/reviews"><Button access="read" size="sm" variant="outline">看候选验证</Button></RouterLink>
      </EmptyState>
    </template>

    <!-- 桌面：密度表 -->
    <BasicTable
      v-else
      class="cmp-table"
      :columns="columns"
      :data-source="tableRows"
      :loading="busy"
      :pagination="false" :height="fillDesktop ? '100%' : undefined"
      :row-class-name="rowClass"
      row-key="strategy_tag"
      empty-text="还没有胜率数据"
      empty-reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
      @row-click="select"
    >
      <template #tag="{ row }">
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="cmp-cell-name">
              <strong class="cmp-name">{{ strategyShortLabel(String(row.strategy_tag ?? ''), names) }}</strong>
              <span class="cmp-source">{{ sourceLabel(row.source) }}</span>
            </span>
          </TooltipTrigger>
          <TooltipContent>{{ strategyLabel(String(row.strategy_tag ?? ''), names) }}</TooltipContent>
        </Tooltip>
      </template>
      <template #winRate="{ row }">
        <span class="cmp-rate">
          <strong class="cmp-num cmp-rate__val" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
            {{ winRateText(row.win_rate as number | null) }}
          </strong>
          <span class="cmp-num cmp-dim cmp-rate__count">{{ row.wins }}/{{ row.total }}</span>
          <UiBadge v-if="sampleBadgeLabel(Number(row.total))" :variant="sampleVariant(Number(row.total))">
            {{ sampleBadgeLabel(Number(row.total)) }}
          </UiBadge>
        </span>
      </template>
      <template #avgReturn="{ row }">
        <span class="cmp-num cmp-strong" :class="toneOf(row.avg_return)">
          {{ signedPct(row.avg_return as number | null) }}
        </span>
      </template>
      <template #t1="{ row }">
        <span class="cmp-num" :class="winRateDisplayTone(horizonStat(row, 't1')?.win_rate ?? null, horizonStat(row, 't1')?.n ?? 0)">
          {{ winRateText(horizonStat(row, 't1')?.win_rate ?? null) }}
        </span>
      </template>
      <template #t3="{ row }">
        <span class="cmp-num" :class="winRateDisplayTone(horizonStat(row, 't3')?.win_rate ?? null, horizonStat(row, 't3')?.n ?? 0)">
          {{ winRateText(horizonStat(row, 't3')?.win_rate ?? null) }}
        </span>
      </template>
      <template #bestHorizon="{ row }">
        <span v-if="bestHorizon(row)" class="cmp-best">
          <span class="cmp-best__tag">T+{{ bestHorizon(row)?.horizon }}</span>
          <span class="cmp-num cmp-strong" :class="winRateDisplayTone(bestHorizon(row)?.win_rate ?? null, bestHorizon(row)?.n ?? 0)">
            {{ winRateText(bestHorizon(row)?.win_rate ?? null) }}
          </span>
          <span class="cmp-num" :class="toneOf(bestHorizon(row)?.avg)">{{ signedPct(bestHorizon(row)?.avg ?? null) }}</span>
        </span>
        <span v-else class="cmp-dim">样本不足</span>
      </template>
      <template #observing="{ row }">
        <span class="cmp-num cmp-dim">{{ Number(row.observing ?? 0) || '—' }}</span>
      </template>
      <template #lastReviewed="{ row }">
        <span class="cmp-num cmp-dim">{{ row.last_reviewed || '—' }}</span>
      </template>
      <template #action="{ row }">
        <Button access="read"
          variant="ghost"
          size="icon-xs"
          class="cmp-arrow"
          :aria-label="`查看${strategyShortLabel(String(row.strategy_tag), names)}样本`"
          title="查看样本证据"
          @click.stop="emit('select', String(row.strategy_tag))"
        >
          <ArrowRight aria-hidden="true" />
        </Button>
      </template>
      <template #empty>
        <EmptyState
          class="cmp-empty"
          description="还没有胜率数据"
          reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
          eta="盘后「候选T+N跟踪」会自动统计"
          :icon="Trophy"
        >
          <RouterLink to="/reviews"><Button access="read" size="sm" variant="outline">看候选验证</Button></RouterLink>
        </EmptyState>
      </template>
    </BasicTable>
  </div>
</template>

<style scoped src="./WinRateCompareTable.css"></style>
