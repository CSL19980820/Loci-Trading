<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import KlineChart from '@/shared/components/charts/KlineChart.vue'
import LwKlineChart from '@/shared/components/charts/LwKlineChart.vue'
import type { IndicatorKind } from '@/shared/components/charts/KlineChart.vue'
import type { KPeriod } from '@/shared/lib/indicators'
import type { QuoteSeries } from '@/shared/types/quant'

import { chgClass, fmtPct } from '../composables/dataQueryFormat'

const props = defineProps<{
  detailCode: string
  detailName: string
  quote: QuoteSeries | null
  busy: boolean
  period: KPeriod
  indicator: IndicatorKind
  adjust: 'qfq' | 'hfq' | 'none'
  adjustLabel: string
  lastClose: string
  detailPct: number | null
}>()

const emit = defineEmits<{
  'update:period': [KPeriod]
  'update:indicator': [IndicatorKind]
  'update:adjust': ['qfq' | 'hfq' | 'none']
  close: []
  adjustChange: []
}>()

/** POC：从未写过 localStorage 时默认开；已有偏好不覆盖。开关不写账本。 */
const useLwChart = useLocalStorage('loci.market.useLwChart', true)

function totalHint(): string {
  const q = props.quote
  if (!q) return ''
  if (q.total_rows && q.total_rows > q.rows) return `最近 ${q.rows} / 共 ${q.total_rows} 根`
  return `${q.rows} 根`
}
</script>

<template>
  <section class="detail">
    <header class="detail-head">
      <button type="button" class="detail-back" @click="emit('close')">← 列表</button>
      <div class="detail-id">
        <strong class="detail-name">{{ detailName || detailCode }}</strong>
        <span class="mono detail-code">{{ detailCode }}</span>
        <template v-if="quote">
          <span class="mono detail-close" :class="chgClass(detailPct)">{{ lastClose }}</span>
          <span class="mono detail-pct" :class="chgClass(detailPct)">{{ fmtPct(detailPct) }}</span>
        </template>
      </div>
      <p v-if="quote" class="detail-meta mono">
        {{ totalHint() }} · {{ adjustLabel }} ·
        {{ quote.bars[0]?.trade_date || '—' }} →
        {{ quote.bars[quote.bars.length - 1]?.trade_date || '—' }}
      </p>
    </header>

    <div class="detail-controls">
      <el-radio-group
        :model-value="period"
        size="small"
        @update:model-value="emit('update:period', $event as KPeriod)"
      >
        <el-radio-button value="day">日K</el-radio-button>
        <el-radio-button value="week">周K</el-radio-button>
        <el-radio-button value="month">月K</el-radio-button>
      </el-radio-group>
      <el-radio-group
        :model-value="indicator"
        size="small"
        @update:model-value="emit('update:indicator', $event as IndicatorKind)"
      >
        <el-radio-button value="macd">MACD</el-radio-button>
        <el-radio-button value="kdj">KDJ</el-radio-button>
        <el-radio-button value="none">无副图</el-radio-button>
      </el-radio-group>
      <el-radio-group
        :model-value="adjust"
        size="small"
        @update:model-value="emit('update:adjust', $event as 'qfq' | 'hfq' | 'none'); emit('adjustChange')"
      >
        <el-radio-button value="qfq">前复权</el-radio-button>
        <el-radio-button value="hfq">后复权</el-radio-button>
        <el-radio-button value="none">不复权</el-radio-button>
      </el-radio-group>
      <el-switch
        v-model="useLwChart"
        size="small"
        inline-prompt
        active-text="LW"
        inactive-text="EC"
        title="主图：ECharts / Lightweight Charts POC"
      />
    </div>

    <div v-if="quote" class="detail-chart">
      <LwKlineChart v-if="useLwChart" :bars="quote.bars" :period="period" />
      <KlineChart v-else :bars="quote.bars" :period="period" :indicator="indicator" />
    </div>
    <EmptyState v-else-if="!busy" description="该证券暂无本机日线。" />
  </section>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  min-height: 0;
}

.detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.45rem 0.75rem;
}

.detail-back {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  color: var(--mist);
  font: inherit;
  font-size: 0.82rem;
  padding: 0.15rem 0.25rem;
  border-radius: var(--radius);
  cursor: pointer;
}

.detail-back:hover {
  color: var(--ink);
  background: var(--panel-2);
}

.detail-id {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.4rem 0.65rem;
  min-width: 0;
}

.detail-name {
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 600;
}

.detail-code {
  color: var(--mist);
  font-size: 0.85rem;
}

.detail-close {
  font-size: 1.15rem;
  font-weight: 600;
}

.detail-pct {
  font-size: 0.9rem;
}

.detail-meta {
  margin: 0;
  width: 100%;
  font-size: 0.75rem;
  color: var(--mist);
}

.detail-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.detail-chart {
  min-height: 0;
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}
</style>
