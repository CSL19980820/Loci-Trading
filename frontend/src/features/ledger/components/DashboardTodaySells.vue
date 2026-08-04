<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { money, signedMoney } from '@/shared/lib/format'
import type { TodaySell } from '@/shared/types/palace'

const props = defineProps<{
  sells: TodaySell[]
}>()

const totalPnl = computed(() =>
  round2(props.sells.reduce((sum, row) => sum + row.realized_pnl, 0)),
)

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function pnlTone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

const columns: BasicTableColumn[] = [
  { prop: 'code', label: '标的', minWidth: 108, fixed: true, slotName: 'stock' },
  { prop: 'price', label: '成本/卖价', minWidth: 120, slotName: 'price' },
  { prop: 'shares', label: '数量', minWidth: 88, slotName: 'shares' },
  { prop: 'amount', label: '成交额', minWidth: 100, slotName: 'amount' },
  { prop: 'realized_pnl', label: '盈亏', minWidth: 100, slotName: 'pnl' },
  { prop: 'realized_pnl_pct', label: '盈亏%', minWidth: 84, slotName: 'pnlPct' },
  { prop: 'shares_after', label: '余仓', minWidth: 80, slotName: 'remain' },
]

const tableRows = computed(() => props.sells as unknown as Record<string, unknown>[])
</script>

<template>
  <section class="sell-panel" aria-label="当日卖出">
    <header class="sell-banner">
      <div class="sell-head">
        <strong>当日卖出</strong>
        <el-tag size="small" type="info">{{ sells.length }}</el-tag>
      </div>
      <div class="sell-sum" :class="pnlTone(totalPnl)" title="当日卖出已实现合计">
        {{ sells.length ? signedMoney(totalPnl) : '—' }}
      </div>
    </header>

    <BasicTable
      v-if="sells.length"
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      stripe
      empty-text="当日无卖出"
      row-key="id"
      class="sell-table"
    >
      <template #stock="{ row }">
        <StockLink :code="String(row.code)" :name="String(row.name)" />
      </template>
      <template #price="{ row }">
        <span class="cell-pair">
          <span>{{ Number(row.cost_before).toFixed(3) }}</span>
          <span class="cell-sep">/</span>
          <span :class="pnlTone(row.realized_pnl as number)">{{ Number(row.price).toFixed(3) }}</span>
        </span>
      </template>
      <template #shares="{ row }">
        {{ Number(row.shares).toLocaleString('zh-CN') }}
      </template>
      <template #amount="{ row }">
        {{ money(Number(row.amount)) }}
      </template>
      <template #pnl="{ row }">
        <span :class="pnlTone(row.realized_pnl as number)">
          {{ signedMoney(Number(row.realized_pnl)) }}
        </span>
      </template>
      <template #pnlPct="{ row }">
        <span :class="pnlTone(row.realized_pnl_pct as number | null)">
          {{ fmtPct(row.realized_pnl_pct as number | null) }}
        </span>
      </template>
      <template #remain="{ row }">
        {{ Number(row.shares_after).toLocaleString('zh-CN') }}
      </template>
    </BasicTable>

    <p v-else class="sell-empty">当日尚无卖出成交</p>
  </section>
</template>

<style scoped>
.sell-panel {
  border-top: 1px solid var(--rule);
}

.sell-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  min-height: 2.25rem;
  padding: 0.35rem 0.85rem;
  background: color-mix(in srgb, var(--panel-2) 55%, var(--sheet));
  border-bottom: 1px solid var(--rule);
}

.sell-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.sell-sum {
  font-size: 0.9rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
}

.sell-sum.is-up {
  color: var(--up);
}

.sell-sum.is-down {
  color: var(--down);
}

.sell-table {
  width: 100%;
}

.sell-empty {
  margin: 0;
  padding: 0.65rem 0.85rem;
  font-size: 0.8rem;
  color: var(--mist);
}

.cell-pair {
  display: inline-flex;
  align-items: baseline;
  gap: 0.2rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  white-space: nowrap;
}

.cell-sep {
  color: var(--mist);
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}
</style>
