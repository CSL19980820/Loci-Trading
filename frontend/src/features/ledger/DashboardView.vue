<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getLiveTape, type LiveTapeItem } from '@/shared/api/quant'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import type { LiveReason } from '@/shared/lib/marketSession'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import Sparkline from '@/shared/components/charts/Sparkline.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { money, signedMoney, toneClass } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import type { Position } from '@/shared/types/palace'

type LivePos = LiveTapeItem & { code: string }

type PositionRow = Position & {
  last: number | null
  pct: number | null
  market_value: number | null
  float_pnl: number | null
  float_pnl_pct: number | null
  today_buy: number
  available: number
  live_ok: boolean
}

const store = usePalaceStore()
const dashboard = computed(() => store.dashboard)
const liveByCode = ref<Record<string, LivePos>>({})
const liveAsOf = ref('')
const liveError = ref('')

const equityValues = computed(() => store.analytics?.equity_curve.map((item) => item.cumulative_pnl) ?? [])
const lastEquity = computed(() => equityValues.value[equityValues.value.length - 1] ?? 0)

const isEmptyLedger = computed(() => {
  const d = dashboard.value
  if (!d) return false
  return (
    d.positions.length === 0 &&
    d.account.realized_pnl === 0 &&
    d.account.total_assets === null &&
    d.evolution.review_count === 0
  )
})

const candidateBriefVisible = computed(() => {
  const s = dashboard.value?.candidate_summary
  if (!s) return false
  return Boolean(s.headline || s.note || s.filtered_count)
})

const positionRows = computed<PositionRow[]>(() => {
  const positions = dashboard.value?.positions ?? []
  const rows = positions.map((p) => {
    const live = liveByCode.value[p.code]
    const last = live?.price ?? null
    const costValue = p.cost_value
    const marketValue =
      last != null && p.shares ? round2(last * p.shares) : live?.market_value ?? null
    const floatPnl = marketValue != null ? round2(marketValue - costValue) : null
    const floatPct =
      live?.pnl_pct ??
      (last != null && p.cost ? round2((last / p.cost - 1) * 100) : null)
    const todayBuy = p.today_buy_shares ?? Math.max(0, p.shares - (p.available_shares ?? p.shares))
    const available = p.available_shares ?? Math.max(0, p.shares - todayBuy)
    return {
      ...p,
      last,
      pct: live?.pct ?? null,
      market_value: marketValue,
      float_pnl: floatPnl,
      float_pnl_pct: floatPct,
      today_buy: todayBuy,
      available,
      live_ok: Boolean(live?.ok),
    }
  })
  // 券商习惯：市值降序
  return rows.sort((a, b) => (b.market_value ?? b.cost_value) - (a.market_value ?? a.cost_value))
})

const liveMarketValue = computed(() => {
  const vals = positionRows.value.map((r) => r.market_value).filter((v): v is number => v != null)
  if (!vals.length) return null
  return round2(vals.reduce((a, b) => a + b, 0))
})

const liveFloatPnl = computed(() => {
  const vals = positionRows.value.map((r) => r.float_pnl).filter((v): v is number => v != null)
  if (!vals.length) return null
  return round2(vals.reduce((a, b) => a + b, 0))
})

/** 有现金快照时用 现金+市值 估总资产；否则退回账本快照 */
const displayTotalAssets = computed(() => {
  const d = dashboard.value
  if (!d) return null
  const cash = d.account.cash
  const mv = liveMarketValue.value
  if (cash != null && mv != null) return round2(cash + mv)
  return d.account.total_assets
})

const liveExposurePct = computed(() => {
  const assets = displayTotalAssets.value
  const mv = liveMarketValue.value ?? dashboard.value?.account.cost_exposure ?? null
  if (assets == null || assets <= 0 || mv == null) return dashboard.value?.account.cost_exposure_pct ?? null
  return round2((mv / assets) * 100)
})

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function scoreTone(score: number | null): string {
  if (score === null) return 'score-neutral'
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}

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

function liveReasonLabel(reason: LiveReason | undefined): string {
  if (reason === 'non_trading_day') return '非交易日'
  if (reason === 'before_open') return '开盘前·库内'
  if (reason?.startsWith('after_close')) return '已收盘·库内'
  return '库内'
}

const posLiveText = computed(() => {
  if (liveError.value) return liveError.value
  if (!liveAllowed.value) return liveReasonLabel(session.value?.live_reason)
  if (liveAsOf.value) return `实时 ${liveAsOf.value.slice(11, 19)} · 8s`
  return '行情接入中'
})

async function refreshLive(): Promise<void> {
  try {
    const tape = await getLiveTape(true)
    const map: Record<string, LivePos> = {}
    for (const item of tape.positions || []) {
      map[item.code] = item
    }
    liveByCode.value = map
    liveAsOf.value = tape.as_of || ''
    liveError.value = tape.error || ''
  } catch (caught: unknown) {
    liveError.value = caught instanceof Error ? caught.message : '行情拉取失败'
  }
}

const { session, liveAllowed } = useLivePolling({ intervalMs: 8000, tick: refreshLive })

onMounted(() => {
  void refreshLive()
})
</script>

<template>
  <PageHeader title="总览" :subtitle="dashboard?.as_of" />

  <el-alert
    v-if="dashboard && isEmptyLedger"
    type="warning"
    show-icon
    :closable="false"
    class="mb"
    title="账本还是空的——数字来自交割 / 资产快照"
  >
    <p class="hint">
      用侧栏「记一笔」写入成交或资产；选股与行情同步请到「选股」或「工坊」。
    </p>
    <div class="alert-actions">
      <RouterLink to="/screen-history"><el-button size="small" type="primary">去选股</el-button></RouterLink>
      <RouterLink to="/quant"><el-button size="small">工坊</el-button></RouterLink>
    </div>
  </el-alert>

  <template v-if="dashboard">
    <section class="metric-rail" aria-label="核心指标">
      <div class="metric-cell">
        <span class="metric-k">
          总资产
          <span v-if="dashboard.account.snapshot_date" class="metric-h">{{ dashboard.account.snapshot_date }}</span>
        </span>
        <span class="metric-v">
          {{ displayTotalAssets === null ? '—' : money(displayTotalAssets) }}
        </span>
      </div>
      <div v-if="dashboard.account.cash != null" class="metric-cell">
        <span class="metric-k">现金</span>
        <span class="metric-v">{{ money(dashboard.account.cash) }}</span>
      </div>
      <div class="metric-cell">
        <span class="metric-k">当日</span>
        <span class="metric-v" :class="pnlTone(dashboard.account.today_realized_pnl)">
          {{ signedMoney(dashboard.account.today_realized_pnl) }}
        </span>
      </div>
      <div class="metric-cell">
        <span class="metric-k">浮盈 <span class="metric-h">实时</span></span>
        <span class="metric-v" :class="pnlTone(liveFloatPnl)">
          {{ liveFloatPnl == null ? '—' : signedMoney(liveFloatPnl) }}
        </span>
      </div>
      <div class="metric-cell">
        <span class="metric-k">
          市值
          <span v-if="liveExposurePct != null" class="metric-h">仓 {{ liveExposurePct }}%</span>
        </span>
        <span class="metric-v">
          {{ liveMarketValue == null ? money(dashboard.account.cost_exposure) : money(liveMarketValue) }}
        </span>
      </div>
      <div class="metric-cell">
        <span class="metric-k">累计</span>
        <span class="metric-v" :class="pnlTone(dashboard.account.realized_pnl)">
          {{ signedMoney(dashboard.account.realized_pnl) }}
        </span>
      </div>
      <div class="metric-cell">
        <span class="metric-k">
          胜率
          <span class="metric-h">{{ dashboard.evolution.review_count }}/{{ dashboard.evolution.gate }}</span>
        </span>
        <span class="metric-v">
          {{ dashboard.scorecard.win_rate === null ? '—' : `${dashboard.scorecard.win_rate}%` }}
        </span>
      </div>
    </section>

    <section class="pos-panel">
      <div class="pos-head">
        <div class="pos-head-left">
          <strong>持仓</strong>
          <el-tag size="small" type="info">{{ dashboard.positions.length }}</el-tag>
          <span class="pos-live" :class="{ 'is-err': !!liveError }">
            {{ posLiveText }}
          </span>
        </div>
        <RouterLink class="text-link" to="/journal">交割</RouterLink>
      </div>
      <el-table :data="positionRows" size="small" empty-text="无持仓" class="pos-table">
        <el-table-column label="标的" min-width="128" fixed>
          <template #default="{ row }">
            <StockLink :code="row.code" :name="row.name" />
          </template>
        </el-table-column>
        <el-table-column label="持仓" align="right" width="80">
          <template #default="{ row }">{{ row.shares.toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="可卖" align="right" width="80">
          <template #default="{ row }">
            <span :class="{ 'is-frozen': row.available < row.shares }">
              {{ row.available.toLocaleString('zh-CN') }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="今买" align="right" width="72">
          <template #default="{ row }">
            {{ row.today_buy ? row.today_buy.toLocaleString('zh-CN') : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="成本" align="right" width="92">
          <template #default="{ row }">{{ row.cost.toFixed(3) }}</template>
        </el-table-column>
        <el-table-column label="现价" align="right" width="92">
          <template #default="{ row }">
            <span :class="pnlTone(row.pct)">{{ fmtPrice(row.last) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="市值" align="right" width="110">
          <template #default="{ row }">
            {{ row.market_value == null ? money(row.cost_value) : money(row.market_value) }}
          </template>
        </el-table-column>
        <el-table-column label="盈亏" align="right" width="110">
          <template #default="{ row }">
            <span :class="pnlTone(row.float_pnl)">
              {{ row.float_pnl == null ? '—' : signedMoney(row.float_pnl) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏%" align="right" width="88">
          <template #default="{ row }">
            <span :class="pnlTone(row.float_pnl_pct)">{{ fmtPct(row.float_pnl_pct) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="天" align="right" width="48">
          <template #default="{ row }">
            <span :title="row.opened_on ? `开仓 ${row.opened_on}` : undefined">
              {{ fmtDays(row.holding_days) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌" align="right" width="88">
          <template #default="{ row }">
            <span :class="pnlTone(row.pct)">{{ fmtPct(row.pct) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p class="pos-foot">
        可卖 = 持仓 − 今买（T+1）。天数按当前这轮开仓日起算；「今」= 当日建仓。浮盈约每 8 秒刷新。
      </p>
    </section>

    <section class="grid-2 secondary-grid">
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <strong>预案</strong>
              <el-tag size="small" class="ml">{{ dashboard.plans.length }}</el-tag>
            </div>
          </div>
        </template>
        <ul v-if="dashboard.plans.length" class="rows">
          <li v-for="plan in dashboard.plans" :key="plan.id">
            <div class="row-main">
              <strong>{{ plan.title }}</strong>
              <span class="code">{{ plan.code }}</span>
            </div>
            <div class="row-meta">
              <span>{{ plan.entry_zone || '—' }}</span>
              <span class="dim">止 {{ plan.invalidation || '—' }}</span>
            </div>
          </li>
        </ul>
        <EmptyState v-else description="暂无预案" :image-size="56" />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <strong>候选</strong>
              <el-tag size="small" class="ml">{{ dashboard.candidates.length }}</el-tag>
            </div>
            <RouterLink class="text-link" to="/pool">候选池</RouterLink>
          </div>
        </template>
        <div v-if="dashboard.candidate_summary && candidateBriefVisible" class="brief brief-compact">
          <div class="brief-top">
            <strong class="brief-title">{{ dashboard.candidate_summary.headline }}</strong>
          </div>
          <p v-if="dashboard.candidate_summary.note" class="brief-note">
            {{ dashboard.candidate_summary.note }}
          </p>
        </div>
        <ul v-if="dashboard.candidates.length" class="rows">
          <li v-for="c in dashboard.candidates.slice(0, 8)" :key="c.id" class="cand">
            <span class="score" :class="scoreTone(c.score)">{{ c.score ?? '—' }}</span>
            <div class="grow">
              <div class="row-main">
                <strong>{{ c.name }}</strong>
                <span class="code">{{ c.code }}</span>
                <el-tag size="small" type="info">{{ c.decision }}</el-tag>
              </div>
              <p class="reason">{{ c.reason }}</p>
            </div>
          </li>
        </ul>
        <EmptyState v-else description="暂无候选" :image-size="56" />
      </el-card>
    </section>

    <section class="foot-strip">
      <div class="foot-score">
        <span>盈亏比 {{ dashboard.scorecard.profit_factor ?? '—' }}</span>
        <span :class="toneClass(dashboard.scorecard.average_realized)">
          均盈亏 {{ signedMoney(dashboard.scorecard.average_realized) }}
        </span>
        <span>胜/负 {{ dashboard.scorecard.wins }}/{{ dashboard.scorecard.losses }}</span>
        <RouterLink class="text-link" to="/reviews">绩效</RouterLink>
      </div>
      <div class="foot-chart">
        <Sparkline
          v-if="equityValues.length"
          :values="equityValues"
          :height="40"
          :color="lastEquity >= 0 ? 'var(--up)' : 'var(--down)'"
          label="累计盈亏"
        />
        <span v-else class="dim">记几笔成交后会出现曲线</span>
      </div>
    </section>
  </template>

  <PageBusy v-else-if="store.loading" />
  <EmptyState v-else description="暂无总览数据" />
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
}

.ml {
  margin-left: 0.4rem;
}

.hint {
  margin: 0.35rem 0 0.65rem;
  color: var(--muted);
  font-size: 0.88rem;
  line-height: 1.5;
}

.alert-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.metric-rail {
  display: flex;
  flex-wrap: nowrap;
  align-items: stretch;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  margin-bottom: 0.65rem;
  overflow-x: auto;
  overflow-y: hidden;
  min-height: 2.75rem;
}

.metric-cell {
  flex: 1 1 0;
  min-width: 5.5rem;
  padding: 0.4rem 0.65rem;
  border-left: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.05rem;
}

.metric-cell:first-child {
  border-left: 0;
}

.metric-k {
  font-size: 0.62rem;
  color: var(--mist);
  letter-spacing: 0.04em;
  white-space: nowrap;
  display: flex;
  gap: 0.35rem;
  align-items: baseline;
}

.metric-v {
  font-size: 0.9rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  line-height: 1.2;
  color: var(--ink);
  white-space: nowrap;
}

.metric-h {
  font-size: 0.62rem;
  color: var(--mist);
  font-weight: 400;
}

.metric-v.is-up {
  color: var(--up);
}

.metric-v.is-down {
  color: var(--down);
}

.pos-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  margin-bottom: 0.75rem;
  overflow: hidden;
}

.pos-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--rule);
}

.pos-head-left {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.pos-live {
  font-size: 0.72rem;
  color: var(--mist);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pos-live.is-err {
  color: var(--seal-ink);
}

.pos-table {
  width: 100%;
}

.pos-table :deep(.is-up) {
  color: var(--up);
}

.pos-table :deep(.is-down) {
  color: var(--down);
}

.pos-table :deep(.is-frozen) {
  color: var(--mist);
}

.pos-foot {
  margin: 0;
  padding: 0.45rem 0.75rem 0.55rem;
  border-top: 1px solid var(--rule);
  font-size: 0.72rem;
  color: var(--mist);
}

.secondary-grid {
  margin-bottom: 0.75rem;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}

.foot-strip {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 0.75rem;
  align-items: center;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.foot-score {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem 1rem;
  font-size: 0.82rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.foot-chart {
  min-height: 40px;
}

@media (max-width: 900px) {
  .foot-strip {
    grid-template-columns: 1fr;
  }

  .secondary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
