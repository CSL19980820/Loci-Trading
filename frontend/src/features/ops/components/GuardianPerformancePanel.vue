<script setup lang="ts">
import { computed } from 'vue'
import { getGuardianPerformance } from '@/shared/api/guardian'
import type { GuardianAccount } from '@/shared/types/guardian'
import { useGuardianHistory } from '../composables/useGuardianHistory'
const props = defineProps<{ account: GuardianAccount }>()
const { range, page, items, total, loading, error, apply, changePage, load } = useGuardianHistory((query, signal) => getGuardianPerformance(query.offset, query.limit, signal), false)
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const performanceRows = computed(() => items.value.map(item => {
  const position = props.account.positions.find(p => p.code === item.code)
  return { ...item, quantity: position?.quantity ?? 0, floating: position?.unrealized_pnl_cents ?? 0,
    total: item.realized_pnl_cents + (position?.unrealized_pnl_cents ?? 0) }
}))
</script>
<template>
  <div aria-label="累计个股盈亏">
    <p class="cell-note">累计口径保留全部成交流水；按股票分页，仅打开此页时计算。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button link @click="load()">重试</el-button></el-alert>

        <el-table :data="performanceRows" row-key="code" empty-text="成交后按股票累计盈亏，清仓记录持续保留" max-height="350">
          <el-table-column label="股票" min-width="130"><template #default="{ row }">{{ row.name }}<small class="cell-note">（{{ row.code }}）</small></template></el-table-column>
          <el-table-column label="累计买入 / 股" prop="bought_quantity" align="right" min-width="115" />
          <el-table-column label="累计卖出 / 股" prop="sold_quantity" align="right" min-width="115" />
          <el-table-column label="当前持仓 / 股" prop="quantity" align="right" min-width="115" />
          <el-table-column label="已实现 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.realized_pnl_cents) }}</template></el-table-column>
          <el-table-column label="浮动 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.floating) }}</template></el-table-column>
          <el-table-column label="累计盈亏 / 元" align="right" min-width="125"><template #default="{ row }"><span :class="pnlClass(row.total)">{{ money(row.total) }}</span></template></el-table-column>
          <el-table-column label="累计费用 / 元" align="right" min-width="120"><template #default="{ row }">{{ money(row.fees_cents) }}</template></el-table-column>
        </el-table>
    <el-pagination :current-page="page" :page-size="range.limit" :page-sizes="[20,50,100,200]" :total="total" layout="total, sizes, prev, pager, next" :disabled="loading" @current-change="changePage" @size-change="apply({ ...range, limit: $event })" />
  </div>
</template>
<style scoped src="./GuardianAccountPanel.css"></style>
