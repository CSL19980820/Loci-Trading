<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'

import type { PulsePickRow } from '../composables/usePulseHome'

const props = defineProps<{
  title: string
  note?: string
  rows: PulsePickRow[]
  empty: string
  showStrategy?: boolean
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

function fmtScore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  // 整数原样；小数最多两位，避免「分」列挤成换行
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function tone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="pulse-panel">
    <header class="pulse-panel__head">
      <strong>{{ title }}</strong>
      <span v-if="note" class="pulse-panel__note">{{ note }}</span>
    </header>
    <el-table
      v-if="rows.length"
      :data="rows"
      size="small"
      stripe
      height="100%"
      class="pulse-table"
      empty-text="—"
    >
      <el-table-column prop="rank" label="#" min-width="48" align="right" />
      <el-table-column label="标的" min-width="240">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :batch="batch" />
        </template>
      </el-table-column>
      <el-table-column
        v-if="showStrategy"
        label="策略"
        min-width="160"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <span class="pulse-muted pulse-strategy">{{ row.strategyName }}</span>
        </template>
      </el-table-column>
      <el-table-column label="今涨" min-width="88" align="right">
        <template #default="{ row }">
          <span class="num" :class="tone(row.pct)">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="分" min-width="72" align="right">
        <template #default="{ row }">
          <span class="num pulse-muted">{{ fmtScore(row.score) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="empty" :image-size="56" />
  </section>
</template>

<style scoped>
.pulse-table {
  flex: 1;
  min-height: 180px;
  min-width: 640px;
}

.pulse-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: auto;
}

.pulse-panel__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid var(--rule);
}

.pulse-panel__head strong {
  font-size: 0.88rem;
}

.pulse-panel__note {
  font-size: 0.72rem;
  color: var(--mist);
}

.pulse-table :deep(.el-table__cell) {
  padding: 4px 8px;
}

.pulse-table :deep(.el-table .cell) {
  white-space: nowrap;
  line-height: 1.25;
}

.num {
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
  font-size: 0.8rem;
  white-space: nowrap;
}

.pulse-muted {
  color: var(--mist);
  font-size: 0.78rem;
}

.pulse-strategy {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.is-up {
  color: var(--up, #c23b3b);
}

.is-down {
  color: var(--down, #1a8f5c);
}
</style>
