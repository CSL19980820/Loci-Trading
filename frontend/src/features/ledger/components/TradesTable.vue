<script setup lang="ts">
import StockLink from '@/shared/components/ui/StockLink.vue'
import { actionLabel, money, signedMoney, toneClass } from '@/shared/lib/format'
import type { TradeRecord } from '@/shared/types/palace'

withDefaults(
  defineProps<{
    trades: TradeRecord[]
    showStock?: boolean
    rowClickable?: boolean
  }>(),
  {
    showStock: false,
    rowClickable: false,
  },
)

const emit = defineEmits<{
  'row-click': [row: TradeRecord]
}>()

function displayCost(row: TradeRecord): string {
  const value = row.action === 'SELL' ? row.cost_before : row.cost_after
  if (!value) return '—'
  return value.toFixed(3)
}
</script>

<template>
  <el-table
    :data="trades"
    size="small"
    @row-click="rowClickable ? emit('row-click', $event as TradeRecord) : undefined"
  >
    <el-table-column label="日期" prop="date" width="110" />
    <el-table-column label="动作" width="90">
      <template #default="{ row }">
        <span class="action-chip" :class="`action-${row.action.toLowerCase()}`">
          {{ actionLabel(row.action) }}
        </span>
      </template>
    </el-table-column>
    <el-table-column v-if="showStock" label="标的" min-width="140">
      <template #default="{ row }">
        <StockLink :code="row.code" :name="row.name" stop />
      </template>
    </el-table-column>
    <el-table-column label="数量" align="right" width="90">
      <template #default="{ row }">{{ row.shares.toLocaleString('zh-CN') }}</template>
    </el-table-column>
    <el-table-column label="价" align="right" width="90">
      <template #default="{ row }">{{ row.price.toFixed(3) }}</template>
    </el-table-column>
    <el-table-column label="额" align="right" width="110">
      <template #default="{ row }">{{ money(row.amount) }}</template>
    </el-table-column>
    <el-table-column label="余仓" align="right" width="90">
      <template #default="{ row }">{{ row.shares_after.toLocaleString('zh-CN') }}</template>
    </el-table-column>
    <el-table-column label="成本" align="right" width="90">
      <template #default="{ row }">
        <!-- 卖出看卖出前成本；买/开仓看成交后成本。清仓 cost_after=0 勿显示成「无成本」。 -->
        <span>{{ displayCost(row) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="已实现" align="right" width="110">
      <template #default="{ row }">
        <span :class="toneClass(row.realized_pnl)">{{ signedMoney(row.realized_pnl) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="备注" min-width="120" show-overflow-tooltip>
      <template #default="{ row }">{{ row.reason || '—' }}</template>
    </el-table-column>
  </el-table>
</template>
