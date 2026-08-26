<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { pct as fmtPct } from '@/shared/lib/format'

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
      <el-table-column
        prop="rank"
        label="序号"
        width="60"
        align="center"
        header-align="center"
      />
      <el-table-column label="标的" width="200" align="center" header-align="center">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
        </template>
      </el-table-column>
      <el-table-column
        v-if="showStrategy"
        label="战法"
        min-width="240"
        align="center"
        header-align="center"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <span class="pulse-muted pulse-strategy">{{ row.strategyName }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="今涨"
        width="160"
        align="center"
        header-align="center"
      >
        <template #default="{ row }">
          <span class="num" :class="tone(row.pct)">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="评分"
        width="160"
        align="center"
        header-align="center"
      >
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
  min-height: 0;
  min-width: 0;
  width: 100%;
}

.pulse-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  min-height: 0;
  height: 100%;
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
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.is-up {
  color: var(--up, #c41e3a);
}

.is-down {
  color: var(--down, #0f6b5c);
}
</style>
