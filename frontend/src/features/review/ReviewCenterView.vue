<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { CapabilityUnavailableError } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import Sparkline from '@/shared/components/charts/Sparkline.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { curveTrustChipClass, curveTrustLabel, reviewEquityChartTitle } from '@/shared/lib/chartTrust'
import { decisionLabel, money, toneClass } from '@/shared/lib/format'

import { useCandidateOutcomesQuery } from './composables/useCandidateOutcomesQuery'
import { useEquityQuery } from './composables/useEquityQuery'
import { usePlanOutcomesQuery } from './composables/usePlanOutcomesQuery'
import { useRoundTripsQuery } from './composables/useRoundTripsQuery'

const activeTab = ref('equity')
const { curve, isPending: equityPending, error: equityError, refetch: refetchEquity } = useEquityQuery()
const { trips, isPending: tripsPending, error: tripsError, refetch: refetchTrips } = useRoundTripsQuery()
const {
  candidates,
  isPending: candidatesPending,
  error: candidatesError,
  refetch: refetchCandidates,
} = useCandidateOutcomesQuery()
const { plans, isPending: plansPending, error: plansError, refetch: refetchPlans } = usePlanOutcomesQuery()

const busy = ref(false)
const errorText = ref('')
const horizons = [5, 10, 20, 60]

function formatQueryError(err: unknown): string {
  if (err instanceof CapabilityUnavailableError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

watch([equityError, tripsError, candidatesError, plansError], ([eq, tr, cd, pl]) => {
  const first = eq ?? tr ?? cd ?? pl
  if (first) errorText.value = formatQueryError(first)
})

const equityValues = computed(() => curve.value?.points.map((p) => p.total_equity) ?? [])
const equityChartTitle = computed(() => reviewEquityChartTitle(curve.value?.confidence))
const lastReturn = computed(() => num('total_return_pct') ?? 0)
const metricCaution = computed(() => {
  const value = curve.value?.metrics?.caution
  return typeof value === 'string' ? value : ''
})

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
      no_data: '无行情',
    }[status] ?? status
  )
}

async function reload(): Promise<void> {
  busy.value = true
  errorText.value = ''
  try {
    await Promise.all([refetchEquity(), refetchTrips(), refetchCandidates(), refetchPlans()])
    const first = equityError.value ?? tripsError.value ?? candidatesError.value ?? plansError.value
    if (first) errorText.value = formatQueryError(first)
  } catch (caught: unknown) {
    errorText.value = formatQueryError(caught) || '加载失败'
  } finally {
    busy.value = false
  }
}

const pageBusy = computed(
  () =>
    busy.value ||
    Boolean(equityPending.value) ||
    Boolean(tripsPending.value) ||
    Boolean(candidatesPending.value) ||
    Boolean(plansPending.value),
)

onMounted(reload)
</script>

<template>
  <PageHeader title="绩效" subtitle="真实账本 + 真实行情">
    <RouterLink to="/reviews/records"><el-button>复盘记录</el-button></RouterLink>
    <el-button :disabled="pageBusy" @click="reload">刷新</el-button>
  </PageHeader>

  <el-alert v-if="errorText" :title="errorText" type="error" show-icon closable class="mb" @close="errorText = ''" />

  <el-tabs v-model="activeTab" class="review-tabs">
    <el-tab-pane label="资金曲线" name="equity">
      <Sheet :title="equityChartTitle" :chip="curve ? `${curve.points.length}d` : undefined" muted-chip>
        <template v-if="curve && curve.points.length">
          <section class="stat-strip cols-5">
            <StatCard label="期末总资产" :value="money(num('end_equity'))" />
            <StatCard label="总收益" :value="pct(num('total_return_pct'))" :tone="pnlTone(num('total_return_pct'))" />
            <StatCard label="最大回撤" :value="pct(num('max_drawdown_pct'))" tone="down" />
            <StatCard label="已实现" :value="money(num('realized_pnl'))" :tone="pnlTone(num('realized_pnl'))" />
            <StatCard label="浮动盈亏" :value="money(num('floating_pnl'))" :tone="pnlTone(num('floating_pnl'))" />
          </section>
          <div class="chart-box">
            <div class="chart-trust-row">
              <span :class="curveTrustChipClass(curve.confidence)">{{ curveTrustLabel(curve.confidence) }}</span>
            </div>
            <Sparkline
              v-if="equityValues.length > 1"
              :values="equityValues"
              :height="96"
              :color="lastReturn >= 0 ? 'var(--up)' : 'var(--down)'"
              label="总资产"
            />
            <EmptyState v-else :description="`账本只覆盖 ${curve.points.length} 个交易日，画不出曲线`" :image-size="64" />
          </div>
          <el-collapse>
            <el-collapse-item title="口径" name="note">
              <p class="form-hint">
                总资产 = 现金 + 持股数 × 当日收盘价；持仓浮亏计入净值，最大回撤才有意义。
              </p>
              <p v-if="curve.confidence === 'estimated'" class="form-hint">{{ curve.note }}</p>
              <p v-if="metricCaution" class="form-error">{{ metricCaution }}</p>
            </el-collapse-item>
          </el-collapse>
        </template>
        <EmptyState v-else-if="curve" :description="curve.note || '暂无数据'">
          <RouterLink to="/journal"><el-button type="primary">记成交</el-button></RouterLink>
        </EmptyState>
        <PageBusy v-else-if="pageBusy" />
        <EmptyState v-else description="暂无数据" :image-size="56" />
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="持仓归因" name="trips">
      <Sheet
        title="持仓归因"
        :chip="trips ? `${trips.summary.closed} 了结 / ${trips.summary.open} 持有` : undefined"
      >
        <template v-if="trips && trips.trips.length">
          <p v-if="trips.summary.hint" class="form-hint highlight-hint">{{ trips.summary.hint }}</p>
          <el-table :data="trips.trips" size="small">
            <el-table-column label="标的" min-width="140">
              <template #default="{ row }">
                <StockLink :code="row.code" :name="row.name || row.code" />
              </template>
            </el-table-column>
            <el-table-column label="区间" min-width="160">
              <template #default="{ row }">
                <span class="mono dim">{{ row.opened_on }} ~ {{ row.closed_on || '至今' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="峰值股数" align="right" width="100">
              <template #default="{ row }">{{ row.peak_shares.toLocaleString('zh-CN') }}</template>
            </el-table-column>
            <el-table-column label="均价" align="right" width="90">
              <template #default="{ row }">{{ row.avg_cost.toFixed(3) }}</template>
            </el-table-column>
            <el-table-column label="收益" align="right" width="100">
              <template #default="{ row }">
                <span :class="toneClass(row.return_pct ?? 0)">
                  {{ row.return_pct === null ? '持有中' : pct(row.return_pct) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="MAE" align="right" width="90">
              <template #default="{ row }"><span class="tone-down">{{ pct(row.mae_pct) }}</span></template>
            </el-table-column>
            <el-table-column label="MFE" align="right" width="90">
              <template #default="{ row }"><span class="tone-up">{{ pct(row.mfe_pct) }}</span></template>
            </el-table-column>
            <el-table-column label="持有" align="right" width="80">
              <template #default="{ row }">{{ row.hold_days ?? '—' }}</template>
            </el-table-column>
          </el-table>
          <dl class="kv">
            <div v-if="trips.summary.win_rate !== undefined">
              <dt>胜率</dt><dd>{{ trips.summary.win_rate }}%</dd>
            </div>
            <div v-if="trips.summary.avg_mfe_pct !== undefined">
              <dt>平均 MFE</dt><dd>{{ pct(trips.summary.avg_mfe_pct) }}</dd>
            </div>
            <div v-if="trips.summary.avg_mae_pct !== undefined">
              <dt>平均 MAE</dt><dd>{{ pct(trips.summary.avg_mae_pct) }}</dd>
            </div>
            <div v-if="trips.summary.winner_avg_mae_pct !== undefined">
              <dt>赢家/输家 MAE</dt>
              <dd>{{ pct(trips.summary.winner_avg_mae_pct) }} vs {{ pct(trips.summary.loser_avg_mae_pct) }}</dd>
            </div>
          </dl>
          <p v-if="trips.summary.caution" class="form-error">{{ trips.summary.caution }}</p>
        </template>
        <EmptyState v-else description="账本里还没有持仓记录">
          <RouterLink to="/journal"><el-button type="primary">记成交</el-button></RouterLink>
        </EmptyState>
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="候选验证" name="candidates">
      <Sheet title="候选池验证" :chip="candidates?.summary.total">
        <el-collapse class="mb-collapse">
          <el-collapse-item title="口径" name="note">
            <p class="form-hint">对全部裁决一视同仁算 T+N——当初否决后来大涨，比买错更能说明规则问题。</p>
          </el-collapse-item>
        </el-collapse>
        <template v-if="candidates && candidates.outcomes.length">
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
          <el-table :data="candidates.outcomes.slice(0, 40)" size="small">
            <el-table-column label="日期" width="110">
              <template #default="{ row }"><span class="mono dim">{{ row.base_date }}</span></template>
            </el-table-column>
            <el-table-column label="标的" min-width="140">
              <template #default="{ row }">
                <StockLink :code="row.code" :name="row.name || row.code" />
              </template>
            </el-table-column>
            <el-table-column label="裁决" width="90">
              <template #default="{ row }"><span class="tag">{{ decisionLabel(row.decision) }}</span></template>
            </el-table-column>
            <el-table-column label="基准价" align="right" width="90">
              <template #default="{ row }">{{ row.base_close?.toFixed(2) ?? '—' }}</template>
            </el-table-column>
            <el-table-column v-for="h in horizons" :key="h" :label="`T+${h}`" align="right" width="90">
              <template #default="{ row }">
                <span :class="toneClass(row.returns[`t${h}`] ?? 0)">{{ pct(row.returns[`t${h}`]) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else description="候选池还没有记录">
          <RouterLink to="/pool"><el-button type="primary">去候选池</el-button></RouterLink>
        </EmptyState>
      </Sheet>
    </el-tab-pane>

    <el-tab-pane label="预案兑现" name="plans">
      <Sheet title="预案兑现" :chip="plans.length || undefined">
        <el-table v-if="plans.length" :data="plans" size="small">
          <el-table-column label="日期" width="110">
            <template #default="{ row }"><span class="mono dim">{{ row.occurred_on }}</span></template>
          </el-table-column>
          <el-table-column label="标的" width="100">
            <template #default="{ row }"><span class="code">{{ row.code }}</span></template>
          </el-table-column>
          <el-table-column label="标题" min-width="140" prop="title" />
          <el-table-column label="止损" align="right" width="90">
            <template #default="{ row }">{{ row.stop_price ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="止盈" align="right" width="90">
            <template #default="{ row }">{{ row.target_price ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><span class="tag">{{ planStatus(row.status_final) }}</span></template>
          </el-table-column>
        </el-table>
        <EmptyState v-else description="还没有预案。写一份后可自动核对止损止盈是否触发。" />
      </Sheet>
    </el-tab-pane>
  </el-tabs>
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
}
.mb-collapse {
  margin-bottom: 0.5rem;
}
.review-tabs :deep(.el-tabs__header) {
  margin-bottom: 0.85rem;
}
</style>
