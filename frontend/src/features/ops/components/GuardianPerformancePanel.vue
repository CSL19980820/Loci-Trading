<script setup lang="ts">
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as Pager } from '@/shared/components/ui/app/Pager.vue'

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
  <div class="workspace-list guardian-performance" aria-label="累计个股盈亏">
    <Notice v-if="error" :title="error" tone="error" :closable="false"><ActionButton access="read" variant="link" @click="load()">重试</ActionButton></Notice>

    <DataGrid :data="performanceRows" row-key="code" empty-text="成交后按股票累计盈亏，清仓记录持续保留">
          <DataColumn label="股票" min-width="130"><template #default="{ row }">{{ row.name }}<small class="cell-note">（{{ row.code }}）</small></template></DataColumn>
          <DataColumn label="累计买入 / 股" prop="bought_quantity" align="right" min-width="115" />
          <DataColumn label="累计卖出 / 股" prop="sold_quantity" align="right" min-width="115" />
          <DataColumn label="当前持仓 / 股" prop="quantity" align="right" min-width="115" />
          <DataColumn label="已实现 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.realized_pnl_cents) }}</template></DataColumn>
          <DataColumn label="浮动 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.floating) }}</template></DataColumn>
          <DataColumn label="累计盈亏 / 元" align="right" min-width="125"><template #default="{ row }"><span :class="pnlClass(row.total)">{{ money(row.total) }}</span></template></DataColumn>
          <DataColumn label="累计费用 / 元" align="right" min-width="120"><template #default="{ row }">{{ money(row.fees_cents) }}</template></DataColumn>
        </DataGrid>
    <div class="guardian-mobile-ledger" aria-label="移动端个股盈亏">
      <article v-for="row in performanceRows" :key="row.code" class="ledger-card">
        <header><strong>{{ row.name }} <small>{{ row.code }}</small></strong><strong :class="pnlClass(row.total)">{{ money(row.total) }}</strong></header>
        <dl>
          <div><dt>当前持仓</dt><dd>{{ row.quantity }} 股</dd></div><div><dt>浮动盈亏</dt><dd :class="pnlClass(row.floating)">{{ money(row.floating) }}</dd></div>
          <div><dt>累计买入</dt><dd>{{ row.bought_quantity }} 股</dd></div><div><dt>累计卖出</dt><dd>{{ row.sold_quantity }} 股</dd></div>
          <div><dt>已实现</dt><dd :class="pnlClass(row.realized_pnl_cents)">{{ money(row.realized_pnl_cents) }}</dd></div><div><dt>累计费用</dt><dd>{{ money(row.fees_cents) }}</dd></div>
        </dl>
      </article>
      <p v-if="!performanceRows.length && !loading" class="ledger-empty">暂无个股成交记录</p>
    </div>
    <Pager :current-page="page" :page-size="range.limit" :page-sizes="[20,50,100,200]" :total="total" layout="total, sizes, prev, pager, next" :disabled="loading" @current-change="changePage" @size-change="apply({ ...range, limit: $event })" />
  </div>
</template>
<style scoped src="./GuardianAccountPanel.css"></style>
