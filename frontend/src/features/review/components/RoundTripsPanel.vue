<script setup lang="ts">
import { computed, ref } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import SegmentSwitch from '@/shared/components/ui/SegmentSwitch.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { money, toneClass } from '@/shared/lib/format'
import type { RoundTrip, RoundTripSummary } from '@/shared/types/quant'

const props = defineProps<{
  trips: RoundTrip[] | null
  summary: RoundTripSummary | null
  loading?: boolean
}>()

/** 默认持有在前 */
const tripScope = ref<'open' | 'closed'>('open')

const openTrips = computed(() => {
  const list = (props.trips ?? []).filter((t) => t.is_open)
  return [...list].sort((a, b) => b.opened_on.localeCompare(a.opened_on) || a.code.localeCompare(b.code))
})

const closedTrips = computed(() => {
  const list = (props.trips ?? []).filter((t) => !t.is_open)
  return [...list].sort((a, b) => {
    const da = a.closed_on || a.opened_on
    const db = b.closed_on || b.opened_on
    return db.localeCompare(da) || a.code.localeCompare(b.code)
  })
})

const scopeItems = computed(() => [
  { name: 'open', label: `持有 ${props.summary?.open ?? openTrips.value.length}` },
  { name: 'closed', label: `了结 ${props.summary?.closed ?? closedTrips.value.length}` },
])

const visibleTrips = computed(() =>
  tripScope.value === 'open' ? openTrips.value : closedTrips.value,
)

const tableRows = computed(() => visibleTrips.value as unknown as Record<string, unknown>[])

const tripColumns = computed<BasicTableColumn[]>(() => {
  const cols: BasicTableColumn[] = [
    { prop: 'code', label: '标的', minWidth: 140, slotName: 'stock' },
    { prop: 'range', label: '区间', minWidth: 160, slotName: 'range' },
    { prop: 'peak_shares', label: '峰值股数', align: 'right', minWidth: 100, slotName: 'peak' },
    { prop: 'avg_cost', label: '均价', align: 'right', minWidth: 90, slotName: 'cost' },
    { prop: 'return_pct', label: '收益', align: 'right', minWidth: 100, slotName: 'ret' },
    { prop: 'mae_pct', label: '最深浮亏', align: 'right', minWidth: 100, slotName: 'mae' },
    { prop: 'mfe_pct', label: '最高浮盈', align: 'right', minWidth: 100, slotName: 'mfe' },
    { prop: 'hold_days', label: '持有', align: 'right', minWidth: 80, slotName: 'hold' },
  ]
  return cols
})

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function pnlTone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

const s = computed(() => props.summary)
</script>

<template>
  <div class="trips-panel">
    <template v-if="trips && trips.length && summary">
      <!-- 同花顺式指标轨：标签左、数值右；了结样本的归因数字 -->
      <header class="attr-rail" aria-label="了结归因统计">
        <div class="attr-cell">
          <span class="attr-k">胜率</span>
          <span class="attr-v">{{ s?.win_rate == null ? '—' : `${s.win_rate}%` }}</span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">已实现</span>
          <span class="attr-v" :class="pnlTone(s?.realized_pnl)">
            {{ s?.realized_pnl == null ? '—' : money(s.realized_pnl) }}
          </span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">均收益</span>
          <span class="attr-v" :class="pnlTone(s?.avg_return_pct)">
            {{ pct(s?.avg_return_pct) }}
          </span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">均浮盈</span>
          <span class="attr-v is-up">{{ pct(s?.avg_mfe_pct) }}</span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">均浮亏</span>
          <span class="attr-v is-down">{{ pct(s?.avg_mae_pct) }}</span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">吐回</span>
          <span class="attr-v" :class="pnlTone(-(s?.profit_give_back_pct ?? 0))">
            {{ pct(s?.profit_give_back_pct) }}
          </span>
        </div>
        <div class="attr-cell">
          <span class="attr-k">均持有</span>
          <span class="attr-v">
            {{ s?.avg_hold_days == null ? '—' : `${s.avg_hold_days}日` }}
          </span>
        </div>
      </header>

      <div v-if="s?.winner_avg_mae_pct != null && s?.loser_avg_mae_pct != null" class="attr-note">
        赢家均浮亏 {{ pct(s.winner_avg_mae_pct) }}
        · 输家均浮亏 {{ pct(s.loser_avg_mae_pct) }}
        <span v-if="s.profit_factor != null"> · 盈亏比 {{ s.profit_factor }}</span>
      </div>

      <div class="trips-toolbar">
        <SegmentSwitch v-model="tripScope" :items="scopeItems" aria-label="持有或了结" />
        <span class="trips-hint dim">
          {{ tripScope === 'open' ? '按开仓日倒序' : '按了结日倒序' }}
        </span>
      </div>

      <BasicTable
        v-if="visibleTrips.length"
        :columns="tripColumns"
        :data-source="tableRows"
        :pagination="false"
        :row-key="(row) => `${row.code}-${row.opened_on}`"
      >
        <template #stock="{ row }">
          <StockLink :code="String(row.code)" :name="String(row.name || row.code)" />
        </template>
        <template #range="{ row }">
          <span class="mono dim">{{ row.opened_on }} ~ {{ row.closed_on || '至今' }}</span>
        </template>
        <template #peak="{ row }">
          {{ Number(row.peak_shares).toLocaleString('zh-CN') }}
        </template>
        <template #cost="{ row }">{{ Number(row.avg_cost).toFixed(3) }}</template>
        <template #ret="{ row }">
          <span :class="toneClass(Number(row.return_pct ?? 0))">
            {{ row.return_pct === null ? '持有中' : pct(row.return_pct as number | null) }}
          </span>
        </template>
        <template #mae="{ row }">
          <span class="tone-down">{{ pct(row.mae_pct as number | null) }}</span>
        </template>
        <template #mfe="{ row }">
          <span class="tone-up">{{ pct(row.mfe_pct as number | null) }}</span>
        </template>
        <template #hold="{ row }">{{ row.hold_days ?? '—' }}</template>
      </BasicTable>
      <EmptyState
        v-else
        :description="tripScope === 'open' ? '当前没有持有中的仓位' : '还没有已了结的完整周期'"
        :image-size="56"
      />
    </template>

    <PageBusy v-else-if="loading" label="加载持仓归因…" />
    <EmptyState v-else description="账本里还没有持仓记录">
      <RouterLink to="/journal"><el-button type="primary">记成交</el-button></RouterLink>
    </EmptyState>
  </div>
</template>

<style scoped>
.trips-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}

.attr-rail {
  display: flex;
  flex-wrap: nowrap;
  align-items: stretch;
  min-width: 0;
  overflow-x: auto;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.attr-cell {
  flex: 1 1 0;
  min-width: 6.25rem;
  padding: 0.4rem 0.75rem;
  border-right: 1px solid var(--rule);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
}

.attr-cell:last-child {
  border-right: 0;
}

.attr-k {
  font-size: 0.72rem;
  color: var(--mist);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.attr-v {
  font-size: 0.9rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  line-height: 1.2;
  color: var(--ink);
  white-space: nowrap;
}

.attr-v.is-up {
  color: var(--up);
}

.attr-v.is-down {
  color: var(--down);
}

.attr-note {
  margin: 0.45rem 0 0;
  padding: 0 0.15rem;
  font-size: 0.75rem;
  color: var(--mist);
  line-height: 1.4;
}

.trips-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  margin: 0.75rem 0 0.55rem;
}

.trips-hint {
  font-size: 0.75rem;
}

.dim {
  color: var(--mist);
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 720px) {
  .attr-rail {
    flex-wrap: wrap;
  }

  .attr-cell {
    flex: 1 1 42%;
    border-bottom: 1px solid var(--rule);
  }
}
</style>
