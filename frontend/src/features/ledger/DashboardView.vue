<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import DashboardHoldingsTable from '@/features/ledger/components/DashboardHoldingsTable.vue'
import DashboardMonthPnlCard from '@/features/ledger/components/DashboardMonthPnlCard.vue'
import DashboardTodaySells from '@/features/ledger/components/DashboardTodaySells.vue'
import { useDashboardLive } from '@/features/ledger/composables/useDashboardLive'
import { createSnapshot } from '@/shared/api/palace'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import Sparkline from '@/shared/components/charts/Sparkline.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { money, signedMoney, toneClass } from '@/shared/lib/format'
import { usePalaceStore } from '@/shared/stores/palace'
import type { MonthPnlPoint, TodaySell } from '@/shared/types/palace'

const store = usePalaceStore()
const route = useRoute()
const dashboard = computed(() => store.dashboard)
const assetDialogOpen = ref(false)
const editCash = ref<number | undefined>(undefined)
const assetSaving = ref(false)

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

const {
  liveError,
  liveMarketValue,
  positionRows,
  posLiveText,
  round2,
} = useDashboardLive(() => dashboard.value?.positions ?? [])

const todaySells = computed<TodaySell[]>(() => dashboard.value?.today_sells ?? [])
const monthCurve = computed<MonthPnlPoint[]>(() => dashboard.value?.month_pnl_curve ?? [])

const displayTotalAssets = computed(() => {
  const d = dashboard.value
  if (!d) return null
  const cash = d.account.cash
  const mv = liveMarketValue.value
  if (cash != null && mv != null) return round2(cash + mv)
  if (cash != null) return d.account.total_assets ?? round2(cash + d.account.cost_exposure)
  return d.account.total_assets
})

const liveExposurePct = computed(() => {
  const assets = displayTotalAssets.value
  const mv = liveMarketValue.value ?? dashboard.value?.account.cost_exposure ?? null
  if (assets == null || assets <= 0 || mv == null) return dashboard.value?.account.cost_exposure_pct ?? null
  return round2((mv / assets) * 100)
})

/** 本月参考盈亏：金额 + 收益率（盯市总资产优先） */
const monthPnl = computed(() => dashboard.value?.account.month_realized_pnl ?? 0)
const monthPct = computed(() => {
  const assets = displayTotalAssets.value
  const month = monthPnl.value
  if (assets != null && assets > 0) return round2((month / assets) * 100)
  return dashboard.value?.account.month_realized_pnl_pct ?? null
})

const lockedMarketValue = computed(() => {
  return liveMarketValue.value ?? dashboard.value?.account.cost_exposure ?? 0
})

function openAssetDialog(): void {
  const assets = displayTotalAssets.value
  const mv = lockedMarketValue.value
  if (assets == null) {
    editCash.value = dashboard.value?.account.cash ?? 0
  } else {
    editCash.value = round2(Math.max(0, assets - mv))
  }
  assetDialogOpen.value = true
}

async function saveAssetSnapshot(): Promise<void> {
  const cash = Number(editCash.value)
  if (!Number.isFinite(cash) || cash < 0) {
    ElMessage.warning('现金不能为负')
    return
  }
  const mv = lockedMarketValue.value
  const total = round2(cash + mv)
  assetSaving.value = true
  try {
    await createSnapshot({
      total_assets: total,
      cash,
      note: '校准现金锚点（总资产=现金+市值，买卖自动滚动现金）',
    })
    ElMessage.success('已校准现金锚点')
    assetDialogOpen.value = false
    await store.loadRoute(route, true)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存失败'))
  } finally {
    assetSaving.value = false
  }
}

function pnlTone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <div class="page-fill">
  <div class="page-scroll">
  <el-alert
    v-if="dashboard && isEmptyLedger"
    type="warning"
    show-icon
    :closable="false"
    class="mb"
    title="账本还是空的——数字来自交割 / 资产快照"
  >
    <p class="hint">
      用侧栏「记一笔」写入成交或资产；市场榜与当日选股请到「盘面」。
    </p>
    <div class="alert-actions">
      <RouterLink to="/"><el-button size="small" type="primary">去盘面</el-button></RouterLink>
      <RouterLink to="/journal"><el-button size="small">交割</el-button></RouterLink>
    </div>
  </el-alert>

  <template v-if="dashboard">
    <section class="pos-panel" aria-label="持仓与核心指标">
      <header class="pos-banner">
        <div class="pos-head">
          <strong>账本</strong>
          <el-tag size="small" type="info">{{ dashboard.positions.length }}</el-tag>
          <span class="pos-live" :class="{ 'is-err': !!liveError }">
            {{ posLiveText }}
          </span>
        </div>
        <div class="metric-rail" aria-label="核心指标">
          <div
            class="metric-cell metric-cell--editable"
            role="button"
            tabindex="0"
            title="点击校准现金锚点；买卖后现金会自动滚动"
            @click="openAssetDialog"
            @keydown.enter.prevent="openAssetDialog"
          >
            <span class="metric-inner">
              <span class="metric-k">总资产</span>
              <span class="metric-v">
                {{ displayTotalAssets === null ? '—' : money(displayTotalAssets) }}
              </span>
            </span>
          </div>
          <div class="metric-cell">
            <span class="metric-inner">
              <span class="metric-k">当日</span>
              <span class="metric-v" :class="pnlTone(dashboard.account.today_realized_pnl)">
                {{ signedMoney(dashboard.account.today_realized_pnl) }}
              </span>
            </span>
          </div>
          <div class="metric-cell">
            <span class="metric-inner">
              <span class="metric-k">仓位</span>
              <span class="metric-v">
                {{ liveExposurePct == null ? '—' : `${liveExposurePct}%` }}
              </span>
            </span>
          </div>
          <div class="metric-cell">
            <span class="metric-inner">
              <span class="metric-k">累计</span>
              <span class="metric-v" :class="pnlTone(dashboard.account.realized_pnl)">
                {{ signedMoney(dashboard.account.realized_pnl) }}
              </span>
            </span>
          </div>
        </div>
      </header>

      <DashboardHoldingsTable :rows="positionRows" />
      <DashboardTodaySells :sells="todaySells" />

      <footer class="pos-score" aria-label="交割绩效">
        <div class="pos-score__stats">
          <div class="pos-score__cell">
            <span class="pos-score__inner">
              <span class="pos-score__k">胜率</span>
              <strong class="pos-score__v">
                {{ dashboard.scorecard.win_rate === null ? '—' : `${dashboard.scorecard.win_rate}%` }}
              </strong>
              <span
                v-if="dashboard.scorecard.wins || dashboard.scorecard.losses"
                class="pos-score__h"
              >
                {{ dashboard.scorecard.wins }}/{{ dashboard.scorecard.losses }}
              </span>
            </span>
          </div>
          <div class="pos-score__cell">
            <span class="pos-score__inner">
              <span class="pos-score__k">盈亏比</span>
              <strong class="pos-score__v">{{ dashboard.scorecard.profit_factor ?? '—' }}</strong>
            </span>
          </div>
          <div class="pos-score__cell">
            <span class="pos-score__inner">
              <span class="pos-score__k">均盈亏</span>
              <strong class="pos-score__v" :class="toneClass(dashboard.scorecard.average_realized)">
                {{ signedMoney(dashboard.scorecard.average_realized) }}
              </strong>
            </span>
          </div>
        </div>
        <div class="pos-score__tape">
          <Sparkline
            v-if="equityValues.length"
            class="pos-score__spark"
            :values="equityValues"
            :height="28"
            :color="lastEquity >= 0 ? 'var(--up)' : 'var(--down)'"
            label="累计盈亏"
          />
          <RouterLink class="pos-score__link" to="/reviews">绩效</RouterLink>
        </div>
      </footer>

      <p class="pos-foot">
        持仓/可卖：可卖 = 持仓 − 今买（T+1）。参考盈亏为当月已实现曲线（不含浮盈）。当日卖出对照卖出前成本。
      </p>

      <DashboardMonthPnlCard
        :as-of="dashboard.as_of"
        :pnl="monthPnl"
        :pnl-pct="monthPct"
        :curve="monthCurve"
        :note="dashboard.account.month_realized_note"
      />
    </section>
  </template>

  <PageBusy v-else-if="store.loading" />
  <EmptyState v-else description="暂无账本数据" />

  <el-dialog v-model="assetDialogOpen" title="校准现金锚点" width="26rem" destroy-on-close>
    <el-form label-width="5.5rem" @submit.prevent="saveAssetSnapshot">
      <el-form-item label="锁定市值">
        <span class="mono">{{ money(lockedMarketValue) }}</span>
      </el-form-item>
      <el-form-item label="可用现金">
        <el-input-number
          v-model="editCash"
          :min="0"
          :max="1e12"
          :step="100"
          :precision="2"
          controls-position="right"
          class="asset-cash-input"
        />
      </el-form-item>
      <el-form-item label="总资产">
        <span class="mono">
          {{ money(round2((Number(editCash) || 0) + lockedMarketValue)) }}
        </span>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="assetDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="assetSaving" @click="saveAssetSnapshot">保存快照</el-button>
    </template>
  </el-dialog>
  </div>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.85rem;
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

.pos-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  margin: 0 0.15rem 0.85rem;
  overflow: hidden;
  flex-shrink: 0;
}

.pos-banner {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--rule);
  min-height: 2.5rem;
}

.pos-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-shrink: 0;
  padding: 0.4rem 0.85rem;
  min-width: 0;
  border-right: 1px solid var(--rule);
}

.metric-rail {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: nowrap;
  align-items: stretch;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.metric-cell {
  flex: 1 1 0;
  min-width: 6.5rem;
  padding: 0.35rem 0.75rem;
  border-right: 1px solid var(--rule);
  display: flex;
  align-items: center;
  justify-content: center;
}

.metric-cell:last-child {
  border-right: 0;
}

.metric-cell--editable {
  cursor: pointer;
}

.metric-cell--editable:hover {
  background: color-mix(in srgb, var(--seal-soft) 55%, transparent);
}

.metric-inner {
  display: inline-flex;
  flex-direction: row;
  align-items: baseline;
  justify-content: center;
  gap: 0.4rem;
  max-width: 100%;
}

.metric-k {
  font-size: 0.72rem;
  color: var(--mist);
  letter-spacing: 0.04em;
  white-space: nowrap;
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

.metric-v.is-up {
  color: var(--up);
}

.metric-v.is-down {
  color: var(--down);
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

.asset-cash-input {
  width: 100%;
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.pos-score {
  display: flex;
  align-items: stretch;
  min-height: 2.65rem;
  border-top: 1px solid var(--rule);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 70%, var(--sheet)) 0%, var(--sheet) 100%);
}

.pos-score__stats {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
}

.pos-score__cell {
  flex: 1 1 0;
  min-width: 7rem;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem 0.75rem;
  border-right: 1px solid var(--rule);
}

.pos-score__inner {
  display: inline-flex;
  flex-direction: row;
  align-items: baseline;
  gap: 0.4rem;
  white-space: nowrap;
}

.pos-score__k {
  font-size: 0.72rem;
  color: var(--mist);
  letter-spacing: 0.04em;
}

.pos-score__v {
  font-size: 0.95rem;
  font-weight: 700;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  line-height: 1.15;
}

.pos-score__v.tone-up {
  color: var(--up);
}

.pos-score__v.tone-down {
  color: var(--down);
}

.pos-score__h {
  font-size: 0.7rem;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
}

.pos-score__tape {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex: 0 1 15rem;
  min-width: 10rem;
  max-width: 18rem;
  padding: 0.3rem 0.85rem 0.3rem 0.75rem;
  background:
    repeating-linear-gradient(
      -12deg,
      transparent,
      transparent 5px,
      color-mix(in srgb, var(--rule) 35%, transparent) 5px,
      color-mix(in srgb, var(--rule) 35%, transparent) 6px
    );
}

.pos-score__spark {
  flex: 1 1 auto;
  min-width: 0;
  opacity: 0.95;
}

.pos-score__link {
  flex-shrink: 0;
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--seal-ink);
  text-decoration: none;
  letter-spacing: 0.06em;
  padding: 0.15rem 0;
  border-bottom: 1px solid color-mix(in srgb, var(--seal) 35%, transparent);
}

.pos-score__link:hover {
  color: var(--seal);
  border-bottom-color: var(--seal);
}

.pos-foot {
  margin: 0;
  padding: 0.4rem 0.85rem 0.5rem;
  border-top: 1px solid var(--rule);
  font-size: 0.72rem;
  color: var(--mist);
}

@media (max-width: 900px) {
  .pos-banner {
    flex-direction: column;
  }

  .pos-head {
    border-right: 0;
    border-bottom: 1px solid var(--rule);
    padding-top: 0.45rem;
    padding-bottom: 0.45rem;
  }

  .metric-cell:last-child {
    border-right: 0;
  }

  .pos-score {
    flex-direction: column;
  }

  .pos-score__tape {
    max-width: none;
    width: 100%;
    border-top: 1px solid var(--rule);
    justify-content: space-between;
  }
}
</style>
