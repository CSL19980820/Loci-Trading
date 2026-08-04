<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import type { BoardRow } from '@/shared/types/quant'

import type { PulseBoardTab } from '../composables/usePulseHome'

const props = defineProps<{
  tab: PulseBoardTab
  rows: BoardRow[]
  note?: string
  pctOf: (row: BoardRow) => number | null
}>()

const emit = defineEmits<{
  'update:tab': [tab: PulseBoardTab]
}>()

const route = useRoute()

const batch = computed(() => ({
  source: '市场榜',
  sourcePath: route.fullPath || '/',
  items: toBatchItems(
    props.rows.map((r) => ({
      code: r.code,
      name: r.name,
      changePct: props.pctOf(r),
    })),
  ),
}))

const tabs: { id: PulseBoardTab; label: string }[] = [
  { id: 'gain', label: '涨幅' },
  { id: 'turnover', label: '换手' },
  { id: 'loss', label: '跌幅' },
]

function fmtPct(value: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtTurnover(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function tone(value: number | null): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="pulse-panel">
    <header class="pulse-panel__head">
      <strong>市场榜</strong>
      <div class="pulse-tabs">
        <el-button
          v-for="t in tabs"
          :key="t.id"
          size="small"
          :type="tab === t.id ? 'primary' : 'default'"
          plain
          @click="emit('update:tab', t.id)"
        >
          {{ t.label }}
        </el-button>
      </div>
    </header>
    <p v-if="note" class="pulse-panel__note">{{ note }}</p>
    <el-table
      v-if="rows.length"
      :data="rows"
      size="small"
      stripe
      height="100%"
      class="pulse-table"
    >
      <el-table-column type="index" label="#" width="42" align="right" />
      <el-table-column label="名称" min-width="110">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
        </template>
      </el-table-column>
      <el-table-column
        :label="tab === 'turnover' ? '换手' : '涨幅'"
        width="78"
        align="right"
      >
        <template #default="{ row }">
          <span
            v-if="tab === 'turnover'"
            class="num"
          >{{ fmtTurnover(row.turnover) }}</span>
          <span v-else class="num" :class="tone(pctOf(row))">{{ fmtPct(pctOf(row)) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="行业" min-width="72">
        <template #default="{ row }">
          <span class="pulse-muted">{{ row.industry || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无榜单，请先同步行情" :image-size="56" />
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
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0.55rem;
  border-bottom: 1px solid var(--rule);
}

.pulse-panel__head strong {
  font-size: 0.88rem;
}

.pulse-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.pulse-panel__note {
  margin: 0;
  padding: 0.25rem 0.65rem 0;
  font-size: 0.7rem;
  color: var(--mist);
}

.pulse-table {
  flex: 1;
  min-height: 180px;
}

.pulse-table :deep(.el-table__cell) {
  padding: 4px 0;
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
