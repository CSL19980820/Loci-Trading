<script setup lang="ts">
import { computed } from 'vue'

import type { HorizonStats } from '@/shared/types/quant'

import { buildHorizonCompareRows } from '../composables/quantBacktestSummary'

const props = defineProps<{
  t1: HorizonStats | null | undefined
  t3: HorizonStats | null | undefined
}>()

const rows = computed(() => buildHorizonCompareRows(props.t1 ?? null, props.t3 ?? null))
</script>

<template>
  <div class="cmp">
    <div class="cmp__head">
      <span>T+1 / T+3 对照</span>
      <span class="cmp__hint">乐观差 = 高点均值 − 收盘均值</span>
    </div>
    <el-table :data="rows" size="small" class="cmp__table">
      <el-table-column prop="label" label="指标" min-width="110" />
      <el-table-column prop="t1" label="T+1" min-width="100" />
      <el-table-column prop="t3" label="T+3" min-width="100" />
    </el-table>
  </div>
</template>

<style scoped>
.cmp {
  border: 1px solid var(--rule);
  border-radius: var(--radius, 8px);
  padding: 0.55rem 0.7rem 0.35rem;
  background: var(--paper, var(--sheet));
}
.cmp__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.35rem 0.75rem;
  margin-bottom: 0.35rem;
  font-size: 0.8rem;
  color: var(--ink);
  font-weight: 600;
}
.cmp__hint {
  font-weight: 400;
  font-size: 0.72rem;
  color: var(--mist);
}
.cmp__table {
  width: 100%;
}
</style>
