<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { signedPct, strategyLabel, strategyShortLabel } from '@/shared/lib/format'
import { sampleBadgeLabel, sampleConfidence, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import type { WinRateSummary } from '@/shared/types/quant'

/**
 * 综合层：横向可比的战法甲板（Deck）+ 详细对比数据表。
 * 整行/卡片可点 → 快速切入该战法专属证据页。
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
  { prop: 'action', label: '', width: 44, align: 'center', headerAlign: 'center', slotName: 'action' },
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

function badgeClass(total: unknown): string {
  return sampleConfidence(Number(total) || 0) === 'low' ? 'sample-badge-low' : 'sample-badge-medium'
}

function toneOf(value: unknown): string {
  const n = Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return 'dim'
  return n >= 0 ? 'tone-up' : 'tone-down'
}
</script>

<template>
  <div v-if="rows.length" class="cmp-container">
    <!-- 顶部战法英雄卡组 (Strategy Deck) -->
    <div class="cmp-deck" aria-label="战法快速概览">
      <div
        v-for="item in rows"
        :key="item.strategy_tag"
        class="deck-card"
        :class="{ 'is-active-card': item.strategy_tag === activeTag }"
        @click="emit('select', item.strategy_tag)"
      >
        <div class="deck-card__top">
          <div class="deck-card__title-wrap">
            <strong class="deck-card__name">{{ strategyShortLabel(item.strategy_tag) }}</strong>
          </div>
          <span class="deck-card__count mono dim">n={{ item.total }}</span>
        </div>

        <div class="deck-card__body">
          <div class="deck-card__rate-box">
            <span class="deck-card__k">T+5 胜率</span>
            <div class="deck-card__v-row">
              <span class="deck-card__rate mono" :class="winRateDisplayTone(item.win_rate, item.total)">
                {{ winRateText(item.win_rate) }}
              </span>
              <span v-if="sampleBadgeLabel(item.total)" class="sample-badge" :class="badgeClass(item.total)">
                {{ sampleBadgeLabel(item.total) }}
              </span>
            </div>
          </div>

          <div class="deck-card__info-box">
            <div class="deck-card__sub-item">
              <span class="deck-card__sub-k">均收益</span>
              <span class="deck-card__sub-v mono" :class="toneOf(item.avg_return)">
                {{ signedPct(item.avg_return) }}
              </span>
            </div>
            <div class="deck-card__sub-item">
              <span class="deck-card__sub-k">最优持股</span>
              <span v-if="item.best_horizon" class="deck-card__best mono">
                T+{{ item.best_horizon.horizon }} ({{ winRateText(item.best_horizon.win_rate) }})
              </span>
              <span v-else class="dim deck-card__sub-v">样本不足</span>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- 下部详细对比数据表 -->
    <div class="cmp-table-wrap">
      <BasicTable
        :columns="columns"
        :data-source="tableRows"
        :pagination="false"
        :row-class-name="rowClass"
        row-key="strategy_tag"
        @row-click="(row: Record<string, unknown>) => emit('select', String(row.strategy_tag ?? ''))"
      >
        <!-- 战法列 -->
        <template #tag="{ row }">
          <el-tooltip placement="top" :content="`${strategyLabel(String(row.strategy_tag ?? ''))} · ${row.strategy_tag}`">
            <div class="cmp-tag-cell">
              <strong class="cmp-tag-title">{{ strategyShortLabel(String(row.strategy_tag ?? '')) }}</strong>
            </div>
          </el-tooltip>
        </template>

        <!-- 口径列 -->
        <template #source="{ row }">
          <span class="dim cmp-source-text">{{ sourceLabel(row.source) }}</span>
        </template>

        <!-- T+5 胜率列：双层量化指示 -->
        <template #winRate="{ row }">
          <div class="cmp-meter">
            <div class="cmp-meter__header">
              <strong class="mono cmp-meter__rate" :class="winRateDisplayTone(Number(row.win_rate), Number(row.total))">
                {{ winRateText(row.win_rate as number | null) }}
              </strong>
              <span class="mono dim cmp-meter__count">{{ row.wins }}/{{ row.total }}</span>
              <span v-if="sampleBadgeLabel(Number(row.total))" class="sample-badge" :class="badgeClass(row.total)">
                {{ sampleBadgeLabel(Number(row.total)) }}
              </span>
            </div>
          </div>
        </template>

        <!-- T+5 均收益 -->
        <template #avgReturn="{ row }">
          <span class="mono cmp-return-text" :class="toneOf(row.avg_return)">
            {{ signedPct(row.avg_return as number | null) }}
          </span>
        </template>

        <!-- T+1 胜率 -->
        <template #t1="{ row }">
          <span class="mono" :class="winRateDisplayTone(horizonStat(row, 't1')?.win_rate ?? null, horizonStat(row, 't1')?.n ?? 0)">
            {{ winRateText(horizonStat(row, 't1')?.win_rate ?? null) }}
          </span>
        </template>

        <!-- T+3 胜率 -->
        <template #t3="{ row }">
          <span class="mono" :class="winRateDisplayTone(horizonStat(row, 't3')?.win_rate ?? null, horizonStat(row, 't3')?.n ?? 0)">
            {{ winRateText(horizonStat(row, 't3')?.win_rate ?? null) }}
          </span>
        </template>

        <!-- 最佳持有期 -->
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

        <!-- 观察中 -->
        <template #observing="{ row }">
          <span class="mono dim">{{ Number(row.observing ?? 0) || '—' }}</span>
        </template>

        <!-- 最近样本 -->
        <template #lastReviewed="{ row }">
          <span class="mono dim">{{ row.last_reviewed || '—' }}</span>
        </template>

        <!-- 下钻指引动作 -->
        <template #action>
          <span class="cmp-arrow" title="查看战法证据">→</span>
        </template>
      </BasicTable>
    </div>
  </div>

  <PageBusy v-else-if="busy" label="加载胜率…" />
  <EmptyState
    v-else
    description="还没有胜率数据"
    reason="选股落池后需等 T+1/T+3/T+5 走完，或补手工复盘收益"
    eta="盘后「候选T+N跟踪」会自动统计"
  >
    <RouterLink to="/reviews"><el-button type="primary">看候选验证</el-button></RouterLink>
  </EmptyState>
</template>

<style scoped src="./WinRateCompareTable.css"></style>
