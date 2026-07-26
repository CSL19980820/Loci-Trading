<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>复盘中心</h1>
      <span class="muted mono">真实账本 + 真实行情，不经过 AI</span>
    </div>
    <button class="quiet-button" type="button" :disabled="busy" @click="reload">刷新</button>
  </header>

  <p v-if="errorText" class="error-banner" role="alert"><span>{{ errorText }}</span></p>

  <!-- 资金曲线 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>资金曲线</h2>
      <span v-if="curve" class="chip muted-chip mono">{{ curve.points.length }}d</span>
    </div>
    <template v-if="curve && curve.points.length">
      <section class="stat-strip">
        <div class="stat">
          <span class="stat-k">期末总资产</span>
          <span class="stat-v">{{ money(num('end_equity')) }}</span>
        </div>
        <div class="stat" :class="toneClass(num('total_return_pct') ?? 0)">
          <span class="stat-k">总收益</span>
          <span class="stat-v">{{ pct(num('total_return_pct')) }}</span>
        </div>
        <div class="stat tone-down">
          <span class="stat-k">最大回撤</span>
          <span class="stat-v">{{ pct(num('max_drawdown_pct')) }}</span>
        </div>
        <div class="stat" :class="toneClass(num('realized_pnl') ?? 0)">
          <span class="stat-k">已实现</span>
          <span class="stat-v">{{ money(num('realized_pnl')) }}</span>
        </div>
        <div class="stat" :class="toneClass(num('floating_pnl') ?? 0)">
          <span class="stat-k">浮动盈亏</span>
          <span class="stat-v">{{ money(num('floating_pnl')) }}</span>
        </div>
        <div v-if="num('sharpe') !== null" class="stat">
          <span class="stat-k">夏普</span>
          <span class="stat-v">{{ num('sharpe') }}</span>
        </div>
      </section>

      <div class="chart-box">
        <Sparkline
          v-if="equityValues.length > 1"
          :values="equityValues"
          :height="96"
          :color="lastReturn >= 0 ? 'var(--up)' : 'var(--down)'"
          label="总资产"
        />
        <p v-else class="empty">账本只覆盖 {{ curve.points.length }} 个交易日，画不出曲线</p>
      </div>

      <!-- 这条线区别于旧曲线的关键：持仓期间的浮亏也在里面，回撤才有意义 -->
      <p class="form-hint">
        与此前那条"已实现盈亏累加"的曲线不同：这里的总资产 = 现金 + 持股数 × 当日收盘价，
        持仓期间的浮亏同样体现在净值里，最大回撤才算得出来。
      </p>
      <p v-if="curve.confidence === 'estimated'" class="form-hint">
        ⓘ {{ curve.note }}
      </p>
      <p v-if="metricCaution" class="form-error">⚠ {{ metricCaution }}</p>
    </template>
    <p v-else-if="curve" class="empty pad">{{ curve.note || '暂无数据' }}</p>
  </section>

  <!-- 持仓周期归因 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>
        持仓归因
        <span v-if="trips" class="chip">{{ trips.summary.closed }} 已了结 / {{ trips.summary.open }} 持有中</span>
      </h2>
    </div>
    <template v-if="trips && trips.trips.length">
      <p v-if="trips.summary.hint" class="form-hint highlight-hint">→ {{ trips.summary.hint }}</p>
      <div class="table-wrap">
        <table class="dense">
          <thead>
            <tr>
              <th>标的</th>
              <th>区间</th>
              <th class="r">峰值股数</th>
              <th class="r">均价</th>
              <th class="r">收益</th>
              <th class="r">MAE</th>
              <th class="r">MFE</th>
              <th class="r">持有</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="trip in trips.trips" :key="trip.code + trip.opened_on">
              <td>
                <RouterLink :to="`/archive/${trip.code}`" class="stock-link">
                  {{ trip.name || trip.code }} <span class="code">{{ trip.code }}</span>
                </RouterLink>
              </td>
              <td class="mono dim">{{ trip.opened_on }} ~ {{ trip.closed_on || '至今' }}</td>
              <td class="r mono">{{ trip.peak_shares.toLocaleString('zh-CN') }}</td>
              <td class="r mono">{{ trip.avg_cost.toFixed(3) }}</td>
              <td class="r mono" :class="toneClass(trip.return_pct ?? 0)">
                {{ trip.return_pct === null ? '持有中' : pct(trip.return_pct) }}
              </td>
              <td class="r mono tone-down">{{ pct(trip.mae_pct) }}</td>
              <td class="r mono tone-up">{{ pct(trip.mfe_pct) }}</td>
              <td class="r mono">{{ trip.hold_days ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
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
      <p v-if="trips.summary.caution" class="form-error">⚠ {{ trips.summary.caution }}</p>
    </template>
    <p v-else class="empty pad">账本里还没有持仓记录。</p>
  </section>

  <!-- 候选池反向验证 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>候选池验证 <span v-if="candidates" class="chip">{{ candidates.summary.total }}</span></h2>
    </div>
    <p class="form-hint">
      只统计买过的票是幸存者偏差。这里对<strong>全部裁决</strong>一视同仁算 T+N 收益——
      当初否决的票后来涨了多少，比买错的输家更能说明规则有没有问题。
    </p>
    <template v-if="candidates && candidates.outcomes.length">
      <div v-if="candidates.summary.missed_winners.length" class="brief">
        <div class="brief-top"><strong class="brief-title">当初否决、事后大涨</strong></div>
        <ul class="rows">
          <li v-for="item in candidates.summary.missed_winners" :key="item.code + item.base_date">
            <div class="row-main">
              <strong>{{ item.name || item.code }}</strong>
              <span class="code">{{ item.code }}</span>
              <span class="tag">{{ item.decision }}</span>
              <span class="mono tone-up">T+20 {{ pct(item.return_t20) }}</span>
              <span class="dim mono">区间最高 {{ pct(item.max_favorable_pct) }}</span>
            </div>
          </li>
        </ul>
      </div>

      <div class="table-wrap">
        <table class="dense">
          <thead>
            <tr>
              <th>日期</th>
              <th>标的</th>
              <th>裁决</th>
              <th class="r">基准价</th>
              <th v-for="h in horizons" :key="h" class="r">T+{{ h }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in candidates.outcomes.slice(0, 40)" :key="item.candidate_id">
              <td class="mono dim">{{ item.base_date }}</td>
              <td>
                <RouterLink :to="`/archive/${item.code}`" class="stock-link">
                  {{ item.name || item.code }} <span class="code">{{ item.code }}</span>
                </RouterLink>
              </td>
              <td><span class="tag">{{ item.decision }}</span></td>
              <td class="r mono">{{ item.base_close?.toFixed(2) ?? '—' }}</td>
              <td
                v-for="h in horizons"
                :key="h"
                class="r mono"
                :class="toneClass(item.returns[`t${h}`] ?? 0)"
              >
                {{ pct(item.returns[`t${h}`]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="candidates.summary.score_buckets" class="meta-strip">
        <span class="meta-k">评分分箱 T+20（不单调说明打分没区分度）</span>
        <span v-for="b in candidates.summary.score_buckets" :key="b.range" class="meta-chip">
          {{ b.range }} <strong>{{ b.avg_t20 === null ? '—' : pct(b.avg_t20) }}</strong>
          <span class="dim">({{ b.count }})</span>
        </span>
      </div>
    </template>
    <p v-else class="empty pad">候选池还没有记录。</p>
  </section>

  <!-- 预案兑现 -->
  <section class="panel">
    <div class="panel-bar">
      <h2>预案兑现 <span v-if="plans.length" class="chip">{{ plans.length }}</span></h2>
    </div>
    <div v-if="plans.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>日期</th><th>标的</th><th>标题</th>
            <th class="r">止损</th><th class="r">止盈</th><th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="plan in plans" :key="plan.plan_id">
            <td class="mono dim">{{ plan.occurred_on }}</td>
            <td class="code">{{ plan.code }}</td>
            <td>{{ plan.title }}</td>
            <td class="r mono">{{ plan.stop_price ?? '—' }}</td>
            <td class="r mono">{{ plan.target_price ?? '—' }}</td>
            <td><span class="tag">{{ planStatus(plan.status_final) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty pad">还没有预案记录。写一份预案后，止损止盈有没有被触发就能自动核对。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  CapabilityUnavailableError,
  getCandidateOutcomes,
  getEquityCurve,
  getPlanOutcomes,
  getRoundTrips,
} from '@/api/quant'
import Sparkline from '@/components/Sparkline.vue'
import { money, toneClass } from '@/lib/format'
import type {
  CandidateOutcome,
  CandidateSummary,
  EquityCurve,
  PlanOutcome,
  RoundTrip,
  RoundTripSummary,
} from '@/types/quant'

const curve = ref<EquityCurve | null>(null)
const trips = ref<{ trips: RoundTrip[]; summary: RoundTripSummary } | null>(null)
const candidates = ref<{ outcomes: CandidateOutcome[]; summary: CandidateSummary } | null>(null)
const plans = ref<PlanOutcome[]>([])
const busy = ref(false)
const errorText = ref('')

const horizons = [5, 10, 20, 60]

const equityValues = computed(() => curve.value?.points.map((p) => p.total_equity) ?? [])
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
    const [c, t, cd, p] = await Promise.all([
      getEquityCurve(),
      getRoundTrips(),
      getCandidateOutcomes(),
      getPlanOutcomes(),
    ])
    curve.value = c
    trips.value = t
    candidates.value = cd
    plans.value = p
  } catch (caught: unknown) {
    errorText.value =
      caught instanceof CapabilityUnavailableError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : '加载失败'
  } finally {
    busy.value = false
  }
}

onMounted(reload)
</script>
