<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>总览</h1>
      <span v-if="dashboard" class="muted mono">{{ dashboard.as_of }}</span>
    </div>
    <button class="primary-button" type="button" @click="tradeDialogOpen = true">记成交</button>
  </header>

  <template v-if="dashboard">
    <section class="stat-strip" aria-label="核心指标">
      <div class="stat" :class="toneClass(dashboard.account.realized_pnl)">
        <span class="stat-k">累计已实现</span>
        <span class="stat-v">{{ signedMoney(dashboard.account.realized_pnl) }}</span>
      </div>
      <div class="stat" :class="toneClass(dashboard.account.today_realized_pnl)">
        <span class="stat-k">当日</span>
        <span class="stat-v">{{ signedMoney(dashboard.account.today_realized_pnl) }}</span>
      </div>
      <!-- 持仓成本合计；pct 相对最近总资产快照 -->
      <div class="stat">
        <span class="stat-k">总持仓</span>
        <span class="stat-v accent">{{ money(dashboard.account.cost_exposure) }}</span>
        <span v-if="dashboard.account.cost_exposure_pct !== null" class="stat-x">
          占资产 {{ dashboard.account.cost_exposure_pct }}%
        </span>
      </div>
      <div class="stat">
        <span class="stat-k">总资产</span>
        <span class="stat-v">
          {{ dashboard.account.total_assets === null ? '—' : money(dashboard.account.total_assets) }}
        </span>
        <span v-if="dashboard.account.snapshot_date" class="stat-x">
          {{ dashboard.account.snapshot_date }}
        </span>
      </div>
      <div class="stat">
        <span class="stat-k">复盘</span>
        <span class="stat-v">{{ dashboard.evolution.review_count }}/{{ dashboard.evolution.gate }}</span>
      </div>
      <div class="stat">
        <span class="stat-k">胜率</span>
        <span class="stat-v">{{ dashboard.scorecard.win_rate === null ? '—' : `${dashboard.scorecard.win_rate}%` }}</span>
      </div>
    </section>

    <!-- 主内容：仓与预案先入眼，统计分布退后 -->
    <section class="grid-2 hold-plan">
      <article class="panel">
        <div class="panel-bar">
          <h2>
            持仓
            <span class="chip">{{ dashboard.positions.length }}</span>
            <span v-if="dashboard.positions.length" class="chip muted-chip mono">
              {{ money(dashboard.account.cost_exposure) }}
            </span>
          </h2>
          <RouterLink class="text-link" to="/journal">交割</RouterLink>
        </div>
        <div class="table-wrap">
          <table class="dense">
            <thead>
              <tr>
                <th>标的</th>
                <th class="r">股数</th>
                <th class="r">成本</th>
                <th class="r">金额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in dashboard.positions" :key="p.code">
                <td>
                  <RouterLink :to="`/archive/${p.code}`" class="stock-link">
                    {{ p.name }} <span class="code">{{ p.code }}</span>
                  </RouterLink>
                </td>
                <td class="r mono">{{ p.shares.toLocaleString('zh-CN') }}</td>
                <td class="r mono">{{ p.cost.toFixed(3) }}</td>
                <td class="r mono">{{ money(p.cost_value) }}</td>
              </tr>
              <tr v-if="!dashboard.positions.length">
                <td colspan="4" class="empty">无持仓</td>
              </tr>
            </tbody>
            <tfoot v-if="dashboard.positions.length">
              <tr class="table-total">
                <td>合计</td>
                <td class="r mono">{{ totalShares.toLocaleString('zh-CN') }}</td>
                <td class="r mono dim">—</td>
                <td class="r mono">{{ money(dashboard.account.cost_exposure) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </article>

      <article class="panel">
        <div class="panel-bar">
          <h2>预案 <span class="chip">{{ dashboard.plans.length }}</span></h2>
        </div>
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
        <p v-else class="empty pad">无</p>
      </article>
    </section>

    <section class="grid-2">
      <article class="panel">
        <div class="panel-bar">
          <h2>
            候选
            <span class="chip">{{ dashboard.candidates.length }}</span>
            <span
              v-if="dashboard.candidate_summary?.all_selected"
              class="chip muted-chip"
            >全选</span>
          </h2>
          <RouterLink class="text-link" to="/pool">差异</RouterLink>
        </div>
        <!-- 纪要只保留结论行 + 备注，股票明细交给下方列表，避免全选时双层重复 -->
        <div
          v-if="dashboard.candidate_summary && candidateBriefVisible"
          class="brief brief-compact"
        >
          <div class="brief-top">
            <strong class="brief-title">{{ dashboard.candidate_summary.headline }}</strong>
            <span
              v-if="dashboard.candidate_summary.filtered_count"
              class="chip muted-chip"
            >未选 {{ dashboard.candidate_summary.filtered_count }}</span>
          </div>
          <p v-if="dashboard.candidate_summary.note" class="brief-note">
            {{ dashboard.candidate_summary.note }}
          </p>
        </div>
        <ul v-if="dashboard.candidates.length" class="rows">
          <li v-for="c in dashboard.candidates.slice(0, 10)" :key="c.id" class="cand">
            <span class="score" :class="scoreTone(c.score)">{{ c.score ?? '—' }}</span>
            <div class="grow">
              <div class="row-main">
                <strong>{{ c.name }}</strong>
                <span class="code">{{ c.code }}</span>
                <span class="tag">{{ c.decision }}</span>
                <span v-if="c.timing" class="dim">{{ c.timing }}</span>
              </div>
              <p class="reason">{{ c.reason }}</p>
            </div>
          </li>
        </ul>
        <p v-else class="empty pad">无</p>
      </article>

      <article class="panel">
        <div class="panel-bar">
          <h2>战绩</h2>
          <RouterLink class="text-link" to="/reviews">复盘</RouterLink>
        </div>
        <dl class="kv">
          <div><dt>盈亏比</dt><dd>{{ dashboard.scorecard.profit_factor ?? '—' }}</dd></div>
          <div><dt>均盈亏</dt><dd :class="toneClass(dashboard.scorecard.average_realized)">{{ signedMoney(dashboard.scorecard.average_realized) }}</dd></div>
          <div><dt>胜/负</dt><dd>{{ dashboard.scorecard.wins }}/{{ dashboard.scorecard.losses }}</dd></div>
        </dl>
      </article>
    </section>

    <!-- 次要：曲线占满一行，决策只做紧凑计数，不与主面板抢视线 -->
    <section class="panel soft-panel mb">
      <div class="panel-bar quiet-bar">
        <h2>盈亏曲线</h2>
        <span class="chip muted-chip">{{ equityValues.length }}d</span>
      </div>
      <div class="chart-box compact-chart">
        <Sparkline
          v-if="equityValues.length"
          :values="equityValues"
          :height="72"
          :color="lastEquity >= 0 ? 'var(--up)' : 'var(--down)'"
          label="累计盈亏"
        />
        <p v-else class="empty">—</p>
      </div>
      <div v-if="decisionBars.length" class="meta-strip" aria-label="决策分布">
        <span class="meta-k">决策</span>
        <span
          v-for="item in decisionBars"
          :key="item.label"
          class="meta-chip"
        >
          {{ item.label }} <strong>{{ item.value }}</strong>
        </span>
      </div>
    </section>
  </template>

  <p v-else-if="!store.loading" class="empty pad">无数据</p>

  <TradeDialog v-model="tradeDialogOpen" />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import Sparkline from '@/components/Sparkline.vue'
import TradeDialog from '@/components/TradeDialog.vue'
import { money, signedMoney, toneClass } from '@/lib/format'
import { usePalaceStore } from '@/stores/palace'

const store = usePalaceStore()
const dashboard = computed(() => store.dashboard)
const tradeDialogOpen = ref(false)

const equityValues = computed(() => store.analytics?.equity_curve.map((item) => item.cumulative_pnl) ?? [])
const lastEquity = computed(() => equityValues.value[equityValues.value.length - 1] ?? 0)
const decisionBars = computed(
  () =>
    store.analytics?.decisions.map((item) => ({
      label: item.decision,
      value: item.count,
    })) ?? [],
)

const totalShares = computed(
  () => dashboard.value?.positions.reduce((sum, item) => sum + item.shares, 0) ?? 0,
)

/** 有标题/备注/未选计数时才展示轻量纪要，避免空壳条 */
const candidateBriefVisible = computed(() => {
  const s = dashboard.value?.candidate_summary
  if (!s) return false
  return Boolean(s.headline || s.note || s.filtered_count)
})

function scoreTone(score: number | null): string {
  if (score === null) return 'score-neutral'
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}
</script>