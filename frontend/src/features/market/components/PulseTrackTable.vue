<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'

import type { PulseTrackRow } from '../composables/usePulseHome'

const props = defineProps<{
  title: string
  note?: string
  rows: PulseTrackRow[]
  empty: string
}>()

const route = useRoute()

const batch = computed(() => ({
  source: props.title,
  sourcePath: route.fullPath || '/',
  items: toBatchItems(props.rows),
}))

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(2)
}

function tone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

function shortDate(value: string): string {
  if (!value || value.length < 10) return value || '—'
  return value.slice(5)
}
</script>

<template>
  <section class="pulse-panel pulse-track">
    <header class="pulse-panel__head">
      <div class="pulse-track__title">
        <strong>{{ title }}</strong>
        <em class="pulse-track__chip">T～T+4</em>
      </div>
      <span v-if="note" class="pulse-panel__note">{{ note }}</span>
    </header>
    <el-table
      v-if="rows.length"
      :data="rows"
      size="small"
      stripe
      height="100%"
      class="pulse-table pulse-track__table"
      empty-text="—"
    >
      <el-table-column label="名称" min-width="108">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :batch="batch" />
        </template>
      </el-table-column>
      <el-table-column label="选股日" width="64" align="center">
        <template #default="{ row }">
          <span class="num pulse-muted">{{ shortDate(row.date) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="策略" min-width="88">
        <template #default="{ row }">
          <span class="pulse-muted pulse-track__strat">{{ row.strategyName }}</span>
        </template>
      </el-table-column>
      <el-table-column label="选入" width="72" align="right">
        <template #default="{ row }">
          <span class="num">{{ fmtPrice(row.entryPrice) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最新" width="72" align="right">
        <template #default="{ row }">
          <span class="num">{{ fmtPrice(row.latestPrice) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨跌幅" width="78" align="right">
        <template #default="{ row }">
          <span class="num" :class="tone(row.changePct)">{{ fmtPct(row.changePct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="T+1" width="72" align="right">
        <template #default="{ row }">
          <span class="num" :class="tone(row.t1)">{{ fmtPct(row.t1) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="T+3" width="72" align="right">
        <template #default="{ row }">
          <span class="num" :class="tone(row.t3)">{{ fmtPct(row.t3) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="empty" :image-size="56" />
  </section>
</template>

<style scoped>
.pulse-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pulse-panel__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid var(--rule);
}

.pulse-track__title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}

.pulse-panel__head strong {
  font-size: 0.88rem;
}

.pulse-track__chip {
  font-style: normal;
  font-size: 0.62rem;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: var(--seal-ink, #8f1529);
  background: color-mix(in srgb, var(--seal-soft, #fce8ec) 70%, #fff);
  border: 1px solid color-mix(in srgb, var(--seal, #c41e3a) 28%, var(--rule));
  padding: 0.08rem 0.32rem;
  line-height: 1.2;
}

.pulse-panel__note {
  font-size: 0.72rem;
  color: var(--mist);
}

.pulse-table {
  flex: 1;
  min-height: 200px;
}

.pulse-table :deep(.el-table__cell) {
  padding: 4px 0;
}

.pulse-track__strat {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.num {
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
  font-size: 0.8rem;
}

.pulse-muted {
  color: var(--mist);
  font-size: 0.78rem;
}

.is-up {
  color: var(--up, #c23b3b);
}

.is-down {
  color: var(--down, #1a8f5c);
}
</style>
