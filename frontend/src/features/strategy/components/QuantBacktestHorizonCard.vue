<script setup lang="ts">
import { computed } from 'vue'

import StatCard from '@/shared/components/ui/StatCard.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { HorizonStats } from '@/shared/types/quant'

import { pnlTone, signed } from '../composables/quantFormat'
import { optimismGapPct } from '../composables/quantBacktestSummary'
import QuantBacktestDistBars from './QuantBacktestDistBars.vue'
import QuantBacktestExtremeTape from './QuantBacktestExtremeTape.vue'

const props = defineProps<{
  title: string
  stats: HorizonStats | null
}>()

const confidenceLabel = computed(() => {
  const c = props.stats?.sample_confidence
  if (c === 'high') return '样本充足'
  if (c === 'medium') return '样本一般'
  if (c === 'low') return '样本偏少'
  return ''
})

const gap = computed(() => optimismGapPct(props.stats?.avg, props.stats?.close_avg ?? null))

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return signed(v)
}

function fmtNum(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}${suffix}`
}
</script>

<template>
  <section class="hz-card">
    <header class="hz-card__head">
      <!-- 标题与样本读数同一行：两块 T+N 卡片并排，标题要留着区分，但不许占两行 -->
      <div class="hz-card__id">
        <h3>{{ title }}</h3>
        <span class="hz-card__n">
          有效样本 {{ stats?.n ?? 0 }}
          <template v-if="confidenceLabel"> · {{ confidenceLabel }}</template>
        </span>
      </div>
      <template v-if="stats">
        <div class="hz-hero">
          <div class="hz-hero__win">
            <span class="hz-hero__k">胜率</span>
            <span class="hz-hero__v">{{ stats.win_rate.toFixed(1) }}%</span>
          </div>
          <div class="hz-hero__avg" :class="pnlTone(stats.avg)">
            <span class="hz-hero__k">均值(高点)</span>
            <span class="hz-hero__v">{{ signed(stats.avg) }}</span>
          </div>
        </div>
      </template>
    </header>

    <EmptyState
      v-if="!stats"
      description="该窗口无有效事件（尾部信号或缺行情已剔除）"
    />

    <template v-else>
      <el-alert
        v-if="stats.caution"
        :title="stats.caution"
        type="warning"
        :closable="false"
        show-icon
        class="hz-caution"
      />

      <div class="hz-grid">
        <StatCard label="中位数" :value="fmtPct(stats.median)" :tone="pnlTone(stats.median ?? 0)" layout="row" />
        <StatCard label="标准差" :value="fmtNum(stats.std, 2, '%')" layout="row" />
        <StatCard label="盈亏比" :value="fmtNum(stats.payoff_ratio, 2)" layout="row" />
        <StatCard label="P25 / P75" :value="`${fmtPct(stats.percentiles?.p25)} / ${fmtPct(stats.percentiles?.p75)}`" layout="row" />
      </div>

      <div v-if="stats.distribution?.length" class="hz-dist">
        <div class="hz-dist__title">高点收益分布</div>
        <QuantBacktestDistBars :bins="stats.distribution" />
      </div>

      <div v-if="stats.close_avg != null" class="hz-close">
        <div class="hz-close__title">收盘口径（更接近可兑现）</div>
        <div class="hz-close__row">
          <span>胜率 {{ fmtNum(stats.close_win_rate, 1, '%') }}</span>
          <span :class="pnlTone(stats.close_avg)">均值 {{ fmtPct(stats.close_avg) }}</span>
          <span :class="pnlTone(stats.close_median ?? 0)">中位 {{ fmtPct(stats.close_median) }}</span>
          <span v-if="gap != null" class="hz-gap" :class="pnlTone(gap)">
            乐观差 {{ fmtPct(gap) }}
          </span>
        </div>
        <p v-if="stats.close_note" class="hz-close__note">{{ stats.close_note }}</p>
      </div>

      <div class="hz-extremes">
        <QuantBacktestExtremeTape kind="best" :event="stats.best_event" />
        <QuantBacktestExtremeTape kind="worst" :event="stats.worst_event" />
      </div>

      <el-table
        v-if="stats.by_month?.length"
        :data="stats.by_month"
        size="small"
        stripe
        class="hz-month"
        max-height="180"
      >
        <el-table-column prop="period" label="月份" width="90" />
        <el-table-column prop="n" label="样本" width="64" />
        <el-table-column label="胜率" width="80">
          <template #default="{ row }">{{ Number(row.win_rate).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="均值">
          <template #default="{ row }">
            <span :class="pnlTone(row.avg)">{{ signed(row.avg) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <p v-if="stats.mark_basis_note" class="hz-note">{{ stats.mark_basis_note }}</p>
    </template>
  </section>
</template>

<style scoped>
.hz-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius, 8px);
  background: var(--paper, var(--sheet));
  min-width: 0;
}
.hz-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.65rem 1rem;
}
/* 标题 + 样本读数同一行 */
.hz-card__id {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
}
.hz-card__head h3 {
  margin: 0;
  font-size: var(--fs-hero);
  font-weight: 700;
  letter-spacing: .03em;
  color: var(--ink);
}
.hz-card__n {
  font-size: var(--fs-aux);
  color: var(--mist);
}
.hz-hero {
  display: flex;
  gap: 1.1rem;
}
.hz-hero__k {
  display: block;
  font-size: 0.72rem;
  color: var(--mist);
}
.hz-hero__v {
  font: 700 1.35rem/1.1 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.hz-hero__avg.up .hz-hero__v {
  color: var(--up);
}
.hz-hero__avg.down .hz-hero__v {
  color: var(--down);
}
.hz-caution {
  margin: 0;
}
.hz-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
}
.hz-dist {
  padding: 0.45rem 0.55rem 0.35rem;
  border: 1px dashed var(--rule);
  border-radius: var(--radius, 8px);
}
.hz-dist__title {
  font-size: 0.72rem;
  color: var(--mist);
  margin-bottom: 0.25rem;
}
.hz-close {
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius, 8px);
  background: color-mix(in srgb, var(--sheet) 70%, var(--paper));
  border: 1px dashed var(--rule);
}
.hz-close__title {
  font-size: 0.75rem;
  color: var(--mist);
  margin-bottom: 0.25rem;
}
.hz-close__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font: 0.85rem/1.35 var(--mono);
  font-variant-numeric: tabular-nums;
}
.hz-close__row .up {
  color: var(--up);
}
.hz-close__row .down {
  color: var(--down);
}
.hz-gap {
  margin-left: auto;
  font-weight: 600;
}
.hz-close__note,
.hz-note {
  margin: 0.35rem 0 0;
  font-size: 0.75rem;
  color: var(--mist);
  line-height: 1.4;
}
.hz-extremes {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.hz-month {
  width: 100%;
}
</style>
