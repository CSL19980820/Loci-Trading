<script setup lang="ts">
import Sheet from '@/shared/components/layout/Sheet.vue'
import QueryFilterBar from '@/shared/components/ui/QueryFilterBar.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { actionLabel } from '@/shared/lib/format'
import type { TradeRecord } from '@/shared/types/palace'

import { pnlClass } from '../composables/dataQueryFormat'

defineProps<{
  tradeCode: string
  trades: TradeRecord[]
  busy: boolean
}>()

const emit = defineEmits<{
  'update:tradeCode': [string]
  query: []
}>()
</script>

<template>
  <QueryFilterBar
    :model-value="tradeCode"
    placeholder="6 位代码，空=全部"
    :busy="busy"
    :maxlength="6"
    @update:model-value="emit('update:tradeCode', $event)"
    @query="emit('query')"
  />
  <Sheet title="交割记录" :chip="trades.length">
    <el-table :data="trades" size="small" empty-text="无交割">
      <el-table-column label="日期" prop="date" width="110" />
      <el-table-column label="动作" width="90">
        <template #default="{ row }">{{ actionLabel(row.action) }}</template>
      </el-table-column>
      <el-table-column label="标的" min-width="140">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" />
        </template>
      </el-table-column>
      <el-table-column label="数量" align="right" width="90" prop="shares" />
      <el-table-column label="价" align="right" width="90">
        <template #default="{ row }">{{ Number(row.price).toFixed(3) }}</template>
      </el-table-column>
      <el-table-column label="已实现" align="right" width="110">
        <template #default="{ row }">
          <span class="mono" :class="pnlClass(row.realized_pnl)">{{ row.realized_pnl }}</span>
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="140" prop="reason" show-overflow-tooltip />
    </el-table>
  </Sheet>
</template>

<style scoped>
.mono {
  font-family: var(--mono);
}
.is-up {
  color: var(--up);
}
.is-down {
  color: var(--down);
}
</style>
