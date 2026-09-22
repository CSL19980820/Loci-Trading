<script setup lang="ts">
import { computed } from 'vue'

import BasicTable from '@/shared/components/ui/BasicTable.vue'
import type { BasicTableColumn } from '@/shared/components/ui/basicTableTypes'
import type { HorizonStats } from '@/shared/types/quant'

import { buildHorizonCompareRows } from '../composables/quantBacktestSummary'

const props = defineProps<{
  t1: HorizonStats | null | undefined
  t3: HorizonStats | null | undefined
}>()

const rows = computed(() => buildHorizonCompareRows(props.t1 ?? null, props.t3 ?? null))

const columns: BasicTableColumn[] = [
  { prop: 'label', label: '指标', minWidth: 110 },
  { prop: 't1', label: 'T+1', minWidth: 100 },
  { prop: 't3', label: 'T+3', minWidth: 100 },
]
</script>

<template>
  <div class="cmp">
    <div class="cmp__head">
      <span>T+1 / T+3 对照</span>
      <span class="cmp__hint">乐观差 = 高点均值 − 收盘均值</span>
    </div>
    <BasicTable :columns="columns" :data-source="rows" :pagination="false" size="small" class="cmp__table" />
  </div>
</template>

<style scoped>
.cmp {
  padding: var(--gap-2) var(--gap-4) var(--gap-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}
.cmp__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-1) var(--gap-3);
  margin-bottom: var(--gap-2);
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
}
.cmp__hint {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 400;
}
.cmp__table {
  width: 100%;
}
</style>
