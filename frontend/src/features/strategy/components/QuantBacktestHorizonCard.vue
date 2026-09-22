<script setup lang="ts">
import { computed } from 'vue'
import { TriangleAlert } from '@lucide/vue'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
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

const monthColumns: BasicTableColumn[] = [
  { prop: 'period', label: '月份', width: 90 },
  { prop: 'n', label: '样本', width: 64 },
  {
    label: '胜率',
    width: 80,
    render: (_h, { row }) => `${Number(row.win_rate).toFixed(1)}%`,
  },
  {
    label: '均值',
    render: (h, { row }) =>
      h('span', { class: pnlTone(Number(row.avg)) }, signed(Number(row.avg))),
  },
]

/**
 * 逐月行先摊平成 `Record<string, unknown>[]` 再交给 BasicTable。
 * `HorizonPeriodRow` 是 interface（没有隐式索引签名），直接传会被表格的
 * `dataSource?: Record<string, unknown>[]` 拒收；这里按本地列定义列字段，
 * 既满足表格约束，也让列与字段的对应关系留在同一屏内。
 */
const monthRows = computed<Record<string, unknown>[]>(() =>
  (props.stats?.by_month ?? []).map((row) => ({
    period: row.period,
    n: row.n,
    win_rate: row.win_rate,
    avg: row.avg,
  })),
)
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
      <Alert v-if="stats.caution" class="hz-caution text-warn">
        <TriangleAlert />
        <AlertTitle class="line-clamp-none min-w-0">{{ stats.caution }}</AlertTitle>
      </Alert>

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

      <BasicTable
        v-if="monthRows.length"
        :columns="monthColumns"
        :data-source="monthRows"
        :pagination="false"
        size="small"
        class="hz-month"
        max-height="180"
      />

      <p v-if="stats.mark_basis_note" class="hz-note">{{ stats.mark_basis_note }}</p>
    </template>
  </section>
</template>

<style scoped>
.hz-card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  padding: var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  min-width: 0;
  container-type: inline-size;
}
.hz-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-4);
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
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0.02em;
}
.hz-card__n {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}
.hz-hero {
  display: flex;
  gap: var(--gap-5);
}
.hz-hero__k {
  display: block;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}
.hz-hero__v {
  color: var(--text-primary);
  font: 600 var(--fs-tape) / 1.1 var(--mono);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-2);
}
.hz-dist {
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}
.hz-dist__title {
  margin-bottom: var(--gap-1);
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}
.hz-close {
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}
.hz-close__title {
  margin-bottom: var(--gap-1);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}
.hz-close__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-3);
  color: var(--text-primary);
  font: var(--fs-ui) / 1.35 var(--mono);
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
  margin: var(--gap-1) 0 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.4;
}
.hz-extremes {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
}
.hz-month {
  width: 100%;
}
@container (max-width: 460px) {
  .hz-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .hz-hero {
    flex-wrap: wrap;
    gap: var(--gap-3);
  }
}
</style>
