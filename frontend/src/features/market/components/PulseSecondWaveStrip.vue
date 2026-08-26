<script setup lang="ts">
/**
 * 盘面二波监测条：池/触发/宽度 + 本轮触发名单。数字来自上一轮扫描与当日现价。
 */
import { computed } from 'vue'

import type { SecondWaveLatest } from '@/shared/api/quant_ops'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { pct as fmtPct, price as fmtPrice } from '@/shared/lib/format'

import { snapshotMeta, snapshotRows } from '../composables/pulseSecondWaveLogic'

const props = defineProps<{
  snap: SecondWaveLatest | null
  loading?: boolean
  error?: string
}>()

const rows = computed(() => snapshotRows(props.snap, props.snap?.min_strength ?? null))
const metaText = computed(() => snapshotMeta(props.snap, Boolean(props.loading)))
const gatePass = computed(() => props.snap?.gate_pass === true)
const showBody = computed(() => Boolean(props.snap?.available))

function fmtCount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return String(Math.round(Number(value)))
}

function tone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="pulse-wave" aria-label="二波监测">
    <header class="pulse-wave__head">
      <div class="pulse-wave__brand">
        <strong>二波监测</strong>
      </div>
      <span v-if="metaText" class="pulse-wave__meta">{{ metaText }}</span>
    </header>

    <p v-if="props.error" class="pulse-wave__err">{{ props.error }}</p>

    <div v-if="showBody" class="pulse-wave__metrics">
      <div class="pulse-wave__metric">
        <span class="pulse-wave__k">池</span>
        <strong>{{ fmtCount(snap?.pool_size) }}</strong>
      </div>
      <div class="pulse-wave__metric">
        <span class="pulse-wave__k">触发</span>
        <strong>{{ fmtCount(snap?.triggered?.length) }}</strong>
      </div>
      <div class="pulse-wave__metric">
        <span class="pulse-wave__k">提醒</span>
        <strong>{{ fmtCount(snap?.picks?.length) }}</strong>
      </div>
      <div class="pulse-wave__metric">
        <span class="pulse-wave__k">宽度</span>
        <strong :class="gatePass ? 'is-up' : 'is-down'">
          {{ snap?.breadth_pct == null ? '—' : `${Number(snap.breadth_pct).toFixed(0)}%` }}
        </strong>
      </div>
    </div>

    <el-table
      v-if="rows.length"
      :data="rows"
      size="small"
      stripe
      max-height="11rem"
      class="pulse-wave__table"
      empty-text="本轮无触发"
    >
      <el-table-column label="标的" min-width="120">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :show-code="false" />
        </template>
      </el-table-column>
      <el-table-column label="强度" width="64" align="center" header-align="center">
        <template #default="{ row }">
          <span :class="row.alerted ? 'is-up' : ''">
            {{ row.strength == null ? '—' : row.strength }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="现价" width="80" align="center" header-align="center">
        <template #default="{ row }">{{ fmtPrice(row.price) }}</template>
      </el-table-column>
      <el-table-column label="涨跌" width="80" align="center" header-align="center">
        <template #default="{ row }">
          <span :class="tone(row.pct)">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="依据" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="pulse-wave__tags">{{ row.tags || (row.alerted ? '达线' : '未达线') }}</span>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<style scoped>
.pulse-wave {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem 0.45rem;
  min-width: 0;
}

.pulse-wave__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.75rem;
}

.pulse-wave__head strong {
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.pulse-wave__meta,
.pulse-wave__k,
.pulse-wave__tags,
.pulse-wave__err {
  font-size: 0.72rem;
  color: var(--mist);
}

.pulse-wave__err {
  color: var(--down, #c45656);
}

.pulse-wave__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
}

.pulse-wave__metric {
  display: flex;
  align-items: baseline;
  gap: 0.3rem;
  min-width: 4.2rem;
}

.pulse-wave__metric strong {
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
  font-weight: 600;
}

.pulse-wave__table {
  width: 100%;
}
</style>
