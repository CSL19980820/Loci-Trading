<script setup lang="ts">
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/shared/components/ui/collapsible'
/** 近选跟踪：手机保留桌面全部指标，展开查看选入信息与个股档案。 */
import { computed } from 'vue'
import { ChevronDown, ArrowUpRight, TrendingUp } from '@lucide/vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { useRoute, useRouter } from 'vue-router'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { price as fmtPrice, signedPct } from '@/shared/lib/format'

import { strategyDisplayName } from '../composables/pulseHomeLogic'
import type { PulseTrackRow } from '../composables/usePulseHome'

import './pulseSkin.css'

const props = defineProps<{
  title: string
  compact?: boolean
  /** 单行元信息（12px 次要色）；长解释请走 `hint` */
  note?: string
  /** 进 tooltip 的口径说明 */
  hint?: string
  rows: PulseTrackRow[]
  /** 空态一行短句（≤14 字） */
  empty: string
  /** 空态长解释 */
  emptyHint?: string
}>()

const route = useRoute()
const router = useRouter()
const isMobile = useMobileLayout()

const batch = computed(() => ({
  source: props.title,
  sourcePath: route.fullPath || '/',
  items: toBatchItems(props.rows),
}))

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

function shortDate(value: string): string {
  if (!value || value.length < 10) return value || '—'
  return value.slice(5)
}

function strategyText(row: PulseTrackRow): string {
  return strategyDisplayName(row.strategyName || row.strategy)
}

function openScreen(): void {
  void router.push('/screen-history')
}

const columns: BasicTableColumn[] = [
  { prop: 'name', label: '名称 · 编码', minWidth: 168, align: 'center', headerAlign: 'center', slotName: 'name' },
  { prop: 'date', label: '选股日', width: 72, align: 'center', headerAlign: 'center', slotName: 'date' },
  { prop: 'entryPrice', label: '选入', minWidth: 72, align: 'center', headerAlign: 'center', slotName: 'entry' },
  { prop: 'latestPrice', label: '最新', minWidth: 72, align: 'center', headerAlign: 'center', slotName: 'latest' },
  { prop: 'changePct', label: '涨跌幅', minWidth: 92, align: 'center', headerAlign: 'center', slotName: 'change' },
  { prop: 'swingPct', label: '低→高', minWidth: 78, align: 'center', headerAlign: 'center', slotName: 'swing' },
  { prop: 't1', label: 'T+1', minWidth: 70, align: 'center', headerAlign: 'center', slotName: 't1' },
  { prop: 't3', label: 'T+3', minWidth: 66, align: 'center', headerAlign: 'center', slotName: 't3' },
  { prop: 'strategy', label: '战法', minWidth: 110, align: 'center', headerAlign: 'center', slotName: 'strategy' },
]

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])
</script>

<template>
  <section class="pulse-panel">
    <header v-if="!compact" class="pulse-panel__head">
      <div class="pulse-panel__lead">
        <span class="pulse-panel__icon-box"><TrendingUp class="pulse-panel__icon" aria-hidden="true" /></span>
        <div class="pulse-panel__titles">
          <h2 class="pulse-panel__title">{{ title }}</h2>
          <Tooltip v-if="hint">
            <TooltipTrigger as-child>
              <span class="pulse-panel__meta">{{ note }}</span>
            </TooltipTrigger>
            <TooltipContent>{{ hint }}</TooltipContent>
          </Tooltip>
          <span v-else class="pulse-panel__meta">{{ note }}</span>
        </div>
      </div>
      <span v-if="rows.length" class="pulse-panel__count">{{ rows.length }}</span>
    </header>

    <!-- 手机：卡片列表 -->
    <template v-if="isMobile">
      <p v-if="compact && note && rows.length" class="track-mobile-note">{{ note }}</p>
      <ul v-if="rows.length" class="pulse-cards">
        <li v-for="row in rows" :key="`${row.date}-${row.code}`" class="track-mobile-row">
          <Collapsible class="track-mobile-card">
            <CollapsibleTrigger class="track-mobile-summary" :aria-label="`${row.name} ${row.code} 跟踪详情`">
              <span class="track-mobile-identity">
                <strong>{{ row.name || row.code }}</strong>
                <span class="track-mobile-meta"><span class="pulse-code">{{ row.code }}</span><span>{{ shortDate(row.date) }} 选入</span></span>
              </span>
              <span class="track-mobile-change"><span class="pulse-card__big" :class="tone(row.changePct)">{{ signedPct(row.changePct) }}</span><span>累计涨跌</span></span>
              <span class="track-mobile-metrics">
                <span>T+1 <b :class="tone(row.t1)">{{ signedPct(row.t1) }}</b></span>
                <span>T+3 <b :class="tone(row.t3)">{{ signedPct(row.t3) }}</b></span>
                <span>低→高 <b :class="tone(row.swingPct)">{{ signedPct(row.swingPct) }}</b></span>
              </span>
              <span class="track-mobile-preview"><span>选入 <span class="pulse-num">{{ fmtPrice(row.entryPrice) }}</span> · 最新 <span class="pulse-num">{{ fmtPrice(row.latestPrice) }}</span></span><span class="track-mobile-toggle"><span class="track-mobile-open-label">查看详情</span><span class="track-mobile-close-label">收起详情</span><ChevronDown aria-hidden="true" /></span></span>
            </CollapsibleTrigger>
            <CollapsibleContent class="track-mobile-detail">
              <dl class="track-mobile-facts">
                <div><dt>选股日</dt><dd>{{ row.date || '—' }}</dd></div>
                <div><dt>选入价</dt><dd>{{ fmtPrice(row.entryPrice) }}</dd></div>
                <div><dt>最新价</dt><dd>{{ fmtPrice(row.latestPrice) }}</dd></div>
                <div class="track-mobile-strategy"><dt>战法</dt><dd>{{ strategyText(row) }}</dd></div>
              </dl>
              <p class="track-mobile-help">累计涨跌按选入价与最新价计算；— 表示暂无数据。</p>
              <p v-if="hint" class="track-mobile-help">{{ hint }}</p>
              <div class="track-mobile-archive"><StockLink :code="row.code" name="查看个股档案" :batch="batch" :show-code="false" /><ArrowUpRight aria-hidden="true" /></div>
            </CollapsibleContent>
          </Collapsible>
        </li>
      </ul>
      <EmptyState v-else class="pulse-panel__empty" :description="empty" :reason="emptyHint" :icon="TrendingUp">
        <Button access="read" size="sm" variant="outline" @click="openScreen">去选股</Button>
      </EmptyState>
    </template>

    <!-- 桌面：密度表 -->
    <BasicTable
      v-else
      class="pulse-table"
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      height="100%"
    >
      <template #name="{ row }">
        <span class="pulse-cell-inline" :title="`${row.name} ${row.code}`">
          <StockLink :code="String(row.code ?? '')" :name="String(row.name ?? '')" :batch="batch" :show-code="false" class="pulse-name" />
          <span class="pulse-code">{{ row.code }}</span>
        </span>
      </template>
      <template #date="{ row }">
        <span class="pulse-num pulse-dim">{{ shortDate(String(row.date ?? '')) }}</span>
      </template>
      <template #entry="{ row }">
        <span class="pulse-num">{{ fmtPrice(row.entryPrice as number | null) }}</span>
      </template>
      <template #latest="{ row }">
        <span class="pulse-num">{{ fmtPrice(row.latestPrice as number | null) }}</span>
      </template>
      <template #change="{ row }">
        <span class="pulse-chip" :class="tone(row.changePct as number | null)">{{ signedPct(row.changePct as number | null) }}</span>
      </template>
      <template #swing="{ row }">
        <span class="pulse-num" :class="tone(row.swingPct as number | null)">{{ signedPct(row.swingPct as number | null) }}</span>
      </template>
      <template #t1="{ row }">
        <span class="pulse-num" :class="tone(row.t1 as number | null)">{{ signedPct(row.t1 as number | null) }}</span>
      </template>
      <template #t3="{ row }">
        <span class="pulse-num" :class="tone(row.t3 as number | null)">{{ signedPct(row.t3 as number | null) }}</span>
      </template>
      <template #strategy="{ row }">
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="pulse-dim pulse-clip">{{ strategyText(row as unknown as PulseTrackRow) }}</span>
          </TooltipTrigger>
          <TooltipContent>{{ strategyText(row as unknown as PulseTrackRow) }}</TooltipContent>
        </Tooltip>
      </template>
      <template #empty>
        <EmptyState class="pulse-panel__empty" :description="empty" :reason="emptyHint" :icon="TrendingUp">
          <Button access="read" size="sm" variant="outline" @click="openScreen">去选股</Button>
        </EmptyState>
      </template>
    </BasicTable>
  </section>
</template>

<style scoped>
.track-mobile-note { margin: 0; padding: 10px 14px 4px; color: var(--text-tertiary); font-size: var(--fs-aux); }
.track-mobile-row { border-bottom: 1px solid var(--rule-soft); }
.track-mobile-row:last-child { border-bottom: 0; }
.track-mobile-summary { width:100%; text-align:left; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px 12px; padding: 14px; cursor: pointer; list-style: none; -webkit-tap-highlight-color: transparent; }
.track-mobile-summary::-webkit-details-marker { display: none; }
.track-mobile-summary:focus-visible { outline: 2px solid var(--seal); outline-offset: -3px; border-radius: var(--radius); }
.track-mobile-summary:active { background: var(--surface-hover); }
.track-mobile-identity { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.track-mobile-identity strong { color: var(--text-primary); font-size: var(--fs-body); overflow-wrap: anywhere; }
.track-mobile-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--text-tertiary); font-size: var(--fs-aux); }
.track-mobile-change { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; color: var(--text-tertiary); font-size: var(--fs-micro); }
.track-mobile-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; color: var(--text-tertiary); font-size: var(--fs-aux); }
.track-mobile-metrics > span { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 5px; }
.track-mobile-metrics b { font-family: var(--mono); font-variant-numeric: tabular-nums; font-weight: 600; }
.track-mobile-preview { grid-column: 1 / -1; display: flex; justify-content: space-between; gap: 8px; color: var(--text-secondary); font-size: var(--fs-aux); }
.track-mobile-toggle { display: inline-flex; align-items: center; gap: 4px; color: var(--text-tertiary); }
.track-mobile-toggle svg, .track-mobile-archive svg { width: 14px; height: 14px; }
.track-mobile-close-label { display: none; }
.track-mobile-card[data-state="open"] .track-mobile-open-label { display: none; }
.track-mobile-card[data-state="open"] .track-mobile-close-label { display: inline; }
.track-mobile-card[data-state="open"] .track-mobile-toggle svg { transform: rotate(180deg); }
.track-mobile-detail { padding: 0 14px 12px; }
.track-mobile-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0; padding: 12px 0; border-top: 1px solid var(--rule-soft); }
.track-mobile-facts dt { color: var(--text-tertiary); font-size: var(--fs-aux); }
.track-mobile-facts dd { margin: 4px 0 0; color: var(--text-primary); font-size: var(--fs-ui); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.track-mobile-strategy { grid-column: 1 / -1; }
.track-mobile-help { margin: 4px 0; color: var(--text-tertiary); font-size: var(--fs-aux); line-height: 1.6; overflow-wrap: anywhere; }
.track-mobile-archive { display: flex; align-items: center; gap: 4px; width: fit-content; min-height: 44px; color: var(--seal-ink); font-size: var(--fs-ui); }
</style>
