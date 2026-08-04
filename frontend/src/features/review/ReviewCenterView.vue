<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { CapabilityUnavailableError } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import EquityLineChart from '@/shared/components/charts/EquityLineChart.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel, localToday, money, toneClass } from '@/shared/lib/format'

import RoundTripsPanel from './components/RoundTripsPanel.vue'
import { useCandidateOutcomesQuery } from './composables/useCandidateOutcomesQuery'
import { useEquityQuery } from './composables/useEquityQuery'
import { usePlanOutcomesQuery } from './composables/usePlanOutcomesQuery'
import { useRoundTripsQuery } from './composables/useRoundTripsQuery'

type EquityRange = '7d' | '30d' | '1y' | 'all' | 'custom'

const activeTab = ref('equity')
const reviewTabs = [
  { name: 'equity', label: '资金曲线' },
  { name: 'trips', label: '持仓归因' },
  { name: 'candidates', label: '候选验证' },
  { name: 'plans', label: '预案兑现' },
]

const equityRange = ref<EquityRange>('all')
const customRange = ref<[string, string] | null>(null)

function shiftCalendarDays(base: string, delta: number): string {
  const d = new Date(`${base}T12:00:00`)
  d.setDate(d.getDate() + delta)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const equityQueryOpts = computed(() => {
  const end = localToday()
  const enabled = activeTab.value === 'equity'
  if (equityRange.value === 'all') return { enabled }
  if (equityRange.value === 'custom') {
    if (!customRange.value?.[0] || !customRange.value?.[1]) return { enabled }
    return { start: customRange.value[0], end: customRange.value[1], enabled }
  }
  const days = equityRange.value === '7d' ? 7 : equityRange.value === '30d' ? 30 : 365
  return { start: shiftCalendarDays(end, -(days - 1)), end, enabled }
})

const { curve, isPending: equityPending, error: equityError, refetch: refetchEquity } =
  useEquityQuery(equityQueryOpts)
const { trips, isPending: tripsPending, error: tripsError, refetch: refetchTrips } =
  useRoundTripsQuery(undefined, () => ({ enabled: activeTab.value === 'trips' }))
const {
  candidates,
  isPending: candidatesPending,
  error: candidatesError,
  refetch: refetchCandidates,
} = useCandidateOutcomesQuery(300, () => ({ enabled: activeTab.value === 'candidates' }))
const { plans, isPending: plansPending, error: plansError, refetch: refetchPlans } =
  usePlanOutcomesQuery(() => ({ enabled: activeTab.value === 'plans' }))

const busy = ref(false)
const errorText = ref('')
const horizons = [1, 3, 5, 10, 20, 60]

const candidateColumns = computed<BasicTableColumn[]>(() => {
  const cols: BasicTableColumn[] = [
    { prop: 'base_date', label: '日期', minWidth: 110, slotName: 'date' },
    { prop: 'code', label: '标的', minWidth: 140, slotName: 'stock' },
    { prop: 'decision', label: '裁决', minWidth: 90, slotName: 'decision' },
    { prop: 'base_close', label: '基准价', align: 'right', minWidth: 90, slotName: 'base' },
  ]
  for (const h of horizons) {
    cols.push({
      prop: `t${h}`,
      label: `T+${h}`,
      align: 'right',
      minWidth: 90,
      slotName: `t${h}`,
    })
  }
  return cols
})

const candidateRows = computed(
  () => (candidates.value?.outcomes.slice(0, 40) ?? []) as unknown as Record<string, unknown>[],
)

const planColumns: BasicTableColumn[] = [
  { prop: 'occurred_on', label: '日期', minWidth: 110, slotName: 'date' },
  { prop: 'code', label: '标的', minWidth: 100, slotName: 'code' },
  { prop: 'title', label: '标题', minWidth: 140 },
  { prop: 'stop_price', label: '止损', align: 'right', minWidth: 90, slotName: 'stop' },
  { prop: 'target_price', label: '止盈', align: 'right', minWidth: 90, slotName: 'target' },
  { prop: 'status_final', label: '状态', minWidth: 100, slotName: 'status' },
]

const planRows = computed(() => plans.value as unknown as Record<string, unknown>[])

function formatQueryError(err: unknown): string {
  if (err instanceof CapabilityUnavailableError) return err.message
  return toErrorMessage(err, '加载失败')
}

watch([equityError, tripsError, candidatesError, plansError], ([eq, tr, cd, pl]) => {
  const byTab =
    activeTab.value === 'equity'
      ? eq
      : activeTab.value === 'trips'
        ? tr
        : activeTab.value === 'candidates'
          ? cd
          : pl
  if (byTab) errorText.value = formatQueryError(byTab)
})

const equityDates = computed(() => curve.value?.points.map((p) => p.trade_date) ?? [])
const equityValues = computed(() => curve.value?.points.map((p) => p.total_equity) ?? [])
const lastReturn = computed(() => num('total_return_pct') ?? 0)
const maxDrawdownPct = computed(() => num('max_drawdown_pct'))

function num(key: string): number | null {
  const value = curve.value?.metrics?.[key]
  return typeof value === 'number' ? value : null
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function pnlTone(value: number | null | undefined): 'up' | 'down' | '' {
  if (value == null) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

function planStatus(status: string): string {
  return (
    {
      observing: '观察中',
      stop_hit: '触发止损',
      target_hit: '触发止盈',
      stop_first: '先止损',
      target_first: '先止盈',
      expired: '窗口未兑现',
      no_data: '无行情',
    }[status] ?? status
  )
}

function selectedHorizonText(horizon: number): string {
  const selected = candidates.value?.summary?.selected as
    | Record<string, { win_rate?: number; n?: number } | null>
    | undefined
  const stats = selected?.[`t${horizon}`]
  if (!stats || stats.win_rate == null) return '—'
  return `${stats.win_rate}%（${stats.n ?? 0}）`
}

function onCustomRange(value: [string, string] | null): void {
  customRange.value = value
  if (value?.[0] && value?.[1]) equityRange.value = 'custom'
}

async function reloadActive(): Promise<void> {
  busy.value = true
  errorText.value = ''
  try {
    const task =
      activeTab.value === 'equity'
        ? refetchEquity
        : activeTab.value === 'trips'
          ? refetchTrips
          : activeTab.value === 'candidates'
            ? refetchCandidates
            : refetchPlans
    await task()
    const err =
      activeTab.value === 'equity'
        ? equityError.value
        : activeTab.value === 'trips'
          ? tripsError.value
          : activeTab.value === 'candidates'
            ? candidatesError.value
            : plansError.value
    if (err) errorText.value = formatQueryError(err)
  } catch (caught: unknown) {
    errorText.value = formatQueryError(caught) || '加载失败'
  } finally {
    busy.value = false
  }
}

const pageBusy = computed(() => {
  if (busy.value) return true
  if (activeTab.value === 'equity') return Boolean(equityPending.value)
  if (activeTab.value === 'trips') return Boolean(tripsPending.value)
  if (activeTab.value === 'candidates') return Boolean(candidatesPending.value)
  return Boolean(plansPending.value)
})
</script>

<template>
  <div class="page-fill">
  <el-alert v-if="errorText" :title="errorText" type="error" show-icon closable class="mb" @close="errorText = ''" />

  <PageTabs v-model="activeTab" :items="reviewTabs" :sticky="false" aria-label="绩效分区" />

  <div class="page-scroll">
  <div v-show="activeTab === 'equity'" class="page-pane">
      <Sheet padded plain>
        <template v-if="curve && curve.points.length">
          <div class="range-bar">
            <el-radio-group v-model="equityRange" class="range-group">
              <el-radio-button value="7d">近7日</el-radio-button>
              <el-radio-button value="30d">近30日</el-radio-button>
              <el-radio-button value="1y">近一年</el-radio-button>
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="custom">自定义</el-radio-button>
            </el-radio-group>
            <el-date-picker
              v-if="equityRange === 'custom'"
              :model-value="customRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              unlink-panels
              range-separator="至"
              start-placeholder="开始"
              end-placeholder="结束"
              class="range-picker"
              @update:model-value="onCustomRange"
            />
            <el-button :disabled="pageBusy" @click="reloadActive">刷新</el-button>
          </div>
          <el-alert
            v-if="curve.note"
            :title="curve.note"
            :type="curve.confidence === 'anchored' ? 'info' : 'warning'"
            show-icon
            :closable="false"
            class="mb"
          />
          <p class="equity-formula dim">
            总资产 = 现金 + 持仓市值（收盘价盯市）· 与账本「现金+成本占用」口径不同
          </p>
          <section class="stat-strip cols-4">
            <StatCard layout="row" label="期末总资产" :value="money(num('end_equity'))" />
            <StatCard
              layout="row"
              label="总收益"
              :value="pct(num('total_return_pct'))"
              :tone="pnlTone(num('total_return_pct'))"
            />
            <StatCard
              layout="row"
              label="已实现"
              :value="money(num('realized_pnl'))"
              :tone="pnlTone(num('realized_pnl'))"
            />
            <StatCard
              layout="row"
              label="浮动盈亏"
              :value="money(num('floating_pnl'))"
              :tone="pnlTone(num('floating_pnl'))"
            />
          </section>
          <div class="chart-box">
            <EquityLineChart
              v-if="equityValues.length > 1"
              :dates="equityDates"
              :values="equityValues"
              :color="lastReturn >= 0 ? 'var(--up)' : 'var(--down)'"
              :overlay-text="maxDrawdownPct != null ? `最大回撤 ${pct(maxDrawdownPct)}` : undefined"
              overlay-tone="down"
            />
            <EmptyState v-else :description="`区间内仅 ${curve.points.length} 个交易日，画不出曲线`" :image-size="64" />
          </div>
        </template>
        <EmptyState v-else-if="curve" :description="curve.note || '暂无数据'">
          <RouterLink to="/journal"><el-button type="primary">记成交</el-button></RouterLink>
        </EmptyState>
        <PageBusy v-else-if="pageBusy" label="加载资金曲线…" />
        <EmptyState v-else description="暂无数据" :image-size="56" />
      </Sheet>
  </div>

  <div v-show="activeTab === 'trips'" class="page-pane">
      <Sheet plain padded>
        <RoundTripsPanel
          :trips="trips?.trips ?? null"
          :summary="trips?.summary ?? null"
          :loading="pageBusy"
        />
      </Sheet>
  </div>

  <div v-show="activeTab === 'candidates'">
      <Sheet plain>
        <template v-if="candidates && candidates.outcomes.length">
          <div class="brief">
            <div class="brief-top"><strong class="brief-title">精选短线兑现</strong></div>
            <div class="stat-row">
              <StatCard
                v-for="h in [1, 3, 5]"
                :key="h"
                layout="row"
                :label="`T+${h} 胜率`"
                :value="selectedHorizonText(h)"
              />
            </div>
          </div>
          <div v-if="candidates.summary.missed_winners.length" class="brief">
            <div class="brief-top"><strong class="brief-title">当初否决、事后大涨</strong></div>
            <ul class="rows">
              <li v-for="item in candidates.summary.missed_winners" :key="item.code + item.base_date">
                <div class="row-main">
                  <strong>{{ item.name || item.code }}</strong>
                  <span class="code">{{ item.code }}</span>
                  <span class="tag">{{ decisionLabel(item.decision) }}</span>
                  <span class="mono tone-up">T+20 {{ pct(item.return_t20) }}</span>
                </div>
              </li>
            </ul>
          </div>
          <BasicTable
            :columns="candidateColumns"
            :data-source="candidateRows"
            :pagination="false"
            :row-key="(row) => `${row.code}-${row.base_date}`"
          >
            <template #date="{ row }">
              <span class="mono dim">{{ row.base_date }}</span>
            </template>
            <template #stock="{ row }">
              <StockLink :code="String(row.code)" :name="String(row.name || row.code)" />
            </template>
            <template #decision="{ row }">
              <span class="tag">{{ decisionLabel(String(row.decision)) }}</span>
            </template>
            <template #base="{ row }">
              {{ row.base_close != null ? Number(row.base_close).toFixed(2) : '—' }}
            </template>
            <template v-for="h in horizons" :key="h" #[`t${h}`]="{ row }">
              <span :class="toneClass(Number((row.returns as Record<string, number | null>)?.[`t${h}`] ?? 0))">
                {{ pct((row.returns as Record<string, number | null>)?.[`t${h}`]) }}
              </span>
            </template>
          </BasicTable>
        </template>
        <PageBusy v-else-if="pageBusy" label="加载候选验证…" />
        <EmptyState v-else description="候选池还没有记录">
          <RouterLink to="/pool"><el-button type="primary">去候选池</el-button></RouterLink>
        </EmptyState>
      </Sheet>
  </div>

  <div v-show="activeTab === 'plans'">
      <Sheet title="预案兑现" :chip="plans.length || undefined">
        <BasicTable
          v-if="plans.length"
          :columns="planColumns"
          :data-source="planRows"
          :pagination="false"
          row-key="plan_id"
        >
          <template #date="{ row }">
            <span class="mono dim">{{ row.occurred_on }}</span>
          </template>
          <template #code="{ row }">
            <span class="code">{{ row.code }}</span>
          </template>
          <template #stop="{ row }">{{ row.stop_price ?? '—' }}</template>
          <template #target="{ row }">{{ row.target_price ?? '—' }}</template>
          <template #status="{ row }">
            <span class="tag">{{ planStatus(String(row.status_final ?? '')) }}</span>
          </template>
        </BasicTable>
        <PageBusy v-else-if="pageBusy" label="加载预案…" />
        <EmptyState v-else description="还没有预案。写一份后可自动核对止损止盈是否触发。" />
      </Sheet>
  </div>
  </div>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
}

.range-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.75rem;
}

.range-bar > .el-button {
  margin-left: auto;
}

.range-group :deep(.el-radio-button__inner) {
  padding: 0.45rem 0.95rem;
  font-size: 0.9rem;
}

.range-picker {
  width: min(280px, 100%);
}

.equity-formula {
  margin: 0 0 0.65rem;
  font-size: 0.78rem;
  line-height: 1.4;
}

.dim {
  color: var(--mist);
}

.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 0.5rem;
}

</style>
