<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { money, signedMoney } from '@/shared/lib/format'
import type { PositionRow } from '@/features/ledger/composables/useDashboardLive'

const props = defineProps<{
  rows: PositionRow[]
}>()

function pnlTone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  return value.toFixed(value >= 1000 ? 2 : 3)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function fmtDays(days: number | null | undefined): string {
  if (days == null) return '—'
  if (days <= 0) return '今'
  return String(days)
}

const columns: BasicTableColumn[] = [
  { prop: 'code', label: '标的', minWidth: 108, fixed: true, slotName: 'stock' },
  { prop: 'shares', label: '持仓/可卖', minWidth: 120, slotName: 'shares' },
  { prop: 'cost', label: '成本/现价', minWidth: 120, slotName: 'price' },
  { prop: 'market_value', label: '市值', minWidth: 100, slotName: 'mv' },
  { prop: 'float_pnl', label: '盈亏', minWidth: 100, slotName: 'pnl' },
  { prop: 'float_pnl_pct', label: '盈亏%', minWidth: 84, slotName: 'pnlPct' },
  { prop: 'holding_days', label: '持仓天数', minWidth: 80, slotName: 'days' },
  { prop: 'pct', label: '涨跌', minWidth: 84, slotName: 'chg' },
]

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])
</script>

<template>
  <BasicTable
    :columns="columns"
    :data-source="tableRows"
    :pagination="false"
    stripe
    empty-text="无持仓"
    row-key="code"
    class="pos-table"
  >
    <template #stock="{ row }">
      <StockLink :code="String(row.code)" :name="String(row.name)" />
    </template>
    <template #shares="{ row }">
      <span class="cell-pair">
        <span>{{ Number(row.shares).toLocaleString('zh-CN') }}</span>
        <span class="cell-sep">/</span>
        <span :class="{ 'is-frozen': Number(row.available) < Number(row.shares) }">
          {{ Number(row.available).toLocaleString('zh-CN') }}
        </span>
      </span>
    </template>
    <template #price="{ row }">
      <span class="cell-pair">
        <span>{{ Number(row.cost).toFixed(3) }}</span>
        <span class="cell-sep">/</span>
        <span :class="pnlTone(row.pct as number | null)">{{ fmtPrice(row.last as number | null) }}</span>
      </span>
    </template>
    <template #mv="{ row }">
      {{
        row.market_value == null
          ? money(Number(row.cost_value))
          : money(Number(row.market_value))
      }}
    </template>
    <template #pnl="{ row }">
      <span :class="pnlTone(row.float_pnl as number | null)">
        {{ row.float_pnl == null ? '—' : signedMoney(Number(row.float_pnl)) }}
      </span>
    </template>
    <template #pnlPct="{ row }">
      <span :class="pnlTone(row.float_pnl_pct as number | null)">
        {{ fmtPct(row.float_pnl_pct as number | null) }}
      </span>
    </template>
    <template #days="{ row }">
      <span :title="row.opened_on ? `开仓 ${row.opened_on}` : undefined">
        {{ fmtDays(row.holding_days as number | null) }}
      </span>
    </template>
    <template #chg="{ row }">
      <span :class="pnlTone(row.pct as number | null)">{{ fmtPct(row.pct as number | null) }}</span>
    </template>
  </BasicTable>
</template>

<style scoped>
.pos-table {
  width: 100%;
}

.cell-pair {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.2rem;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  white-space: nowrap;
}

.cell-sep {
  color: var(--mist);
  font-weight: 400;
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}

.is-frozen {
  color: var(--mist);
}
</style>
