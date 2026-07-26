<template>
  <header class="toolbar">
    <div class="toolbar-title">
      <h1>量化</h1>
      <span v-if="coverage" class="muted mono">
        {{ coverage.codes }} 只 · {{ coverage.first_date }} ~ {{ coverage.last_date }}
      </span>
    </div>
    <button class="quiet-button" type="button" :disabled="busy" @click="reload">刷新</button>
  </header>

  <p v-if="unavailable" class="error-banner" role="alert">
    <span>{{ unavailable }}</span>
  </p>

  <section v-if="coverage" class="stat-strip" aria-label="行情仓">
    <div class="stat">
      <span class="stat-k">证券</span>
      <span class="stat-v">{{ coverage.codes.toLocaleString('zh-CN') }}</span>
    </div>
    <div class="stat">
      <span class="stat-k">日线行数</span>
      <span class="stat-v">{{ coverage.rows.toLocaleString('zh-CN') }}</span>
    </div>
    <div class="stat">
      <span class="stat-k">最新交易日</span>
      <span class="stat-v mono">{{ coverage.last_date || '—' }}</span>
    </div>
    <div class="stat" :class="coverage.failed_codes ? 'tone-down' : ''">
      <span class="stat-k">同步失败</span>
      <span class="stat-v">{{ coverage.failed_codes }}</span>
    </div>
    <div class="stat">
      <span class="stat-k">库体积</span>
      <span class="stat-v">{{ (coverage.db_bytes / 1e6).toFixed(0) }} MB</span>
    </div>
  </section>

  <section class="panel mb">
    <div class="panel-bar">
      <h2>战法 <span class="chip">{{ strategies.length }}</span></h2>
    </div>
    <div class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>战法</th>
            <th>入场</th>
            <th class="r">最少K线</th>
            <th>说明</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in strategies" :key="item.slug">
            <td>
              <strong>{{ item.name }}</strong>
              <span class="code">{{ item.slug }}</span>
            </td>
            <td>
              <span class="tag">{{ item.entry_timing === 'open' ? '当日开盘' : '次日开盘' }}</span>
            </td>
            <td class="r mono">{{ item.min_bars }}</td>
            <td class="reason">{{ item.description }}</td>
            <td class="r">
              <button class="quiet-button" type="button" :disabled="busy" @click="screen(item.slug)">
                选股
              </button>
              <button class="quiet-button" type="button" :disabled="busy" @click="backtest(item.slug)">
                回测
              </button>
            </td>
          </tr>
          <tr v-if="!strategies.length">
            <td colspan="5" class="empty">无已注册战法</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="form-hint">
      入场时点是战法自身的属性，不是回测参数：用到当日收盘/最高/最低的战法只能次日开盘入场，
      否则就是拿收盘后才知道的信息去做当日成交。
    </p>
  </section>

  <section v-if="screenResult" class="panel mb">
    <div class="panel-bar">
      <h2>
        选股结果
        <span class="chip">{{ screenResult.picks.length }}</span>
        <span class="chip muted-chip mono">{{ screenResult.trade_date }}</span>
      </h2>
      <span class="muted mono">
        候选池 {{ screenResult.universe_size }} 只 · {{ (screenResult.elapsed_seconds * 1000).toFixed(0) }} ms
      </span>
    </div>
    <div v-if="screenResult.picks.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>代码</th>
            <th class="r">开</th>
            <th class="r">收</th>
            <th v-for="key in factorKeys" :key="key" class="r">{{ key }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pick in screenResult.picks" :key="pick.code">
            <td>
              <RouterLink :to="`/archive/${pick.code}`" class="stock-link">{{ pick.code }}</RouterLink>
            </td>
            <td class="r mono">{{ fmt(pick.open) }}</td>
            <td class="r mono">{{ fmt(pick.close) }}</td>
            <td v-for="key in factorKeys" :key="key" class="r mono">{{ fmt(pick.factors[key]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="empty pad">当日无标的满足条件</p>
  </section>

  <section v-if="backtestResult" class="panel mb">
    <div class="panel-bar">
      <h2>回测 <span class="chip mono">{{ backtestResult.strategy }}</span></h2>
    </div>
    <p v-if="!backtestResult.metrics.trades" class="empty pad">区间内没有可评估的交易</p>
    <template v-else>
      <section class="stat-strip">
        <div class="stat">
          <span class="stat-k">笔数</span>
          <span class="stat-v">{{ backtestResult.metrics.trades }}</span>
        </div>
        <div class="stat">
          <span class="stat-k">胜率</span>
          <span class="stat-v">{{ backtestResult.metrics.win_rate?.toFixed(1) }}%</span>
        </div>
        <div class="stat" :class="toneClass(backtestResult.metrics.avg_net_return ?? 0)">
          <span class="stat-k">净收益均值</span>
          <span class="stat-v">{{ signed(backtestResult.metrics.avg_net_return) }}</span>
        </div>
        <div class="stat">
          <span class="stat-k">盈亏比</span>
          <span class="stat-v">{{ backtestResult.metrics.profit_factor ?? '—' }}</span>
        </div>
        <div class="stat tone-up">
          <span class="stat-k">MFE 均值</span>
          <span class="stat-v">{{ signed(backtestResult.metrics.avg_mfe) }}</span>
        </div>
        <div class="stat tone-down">
          <span class="stat-k">MAE 均值</span>
          <span class="stat-v">{{ signed(backtestResult.metrics.avg_mae) }}</span>
        </div>
      </section>
      <!-- 浮盈拿不住是短持有期战法最常见的病：MFE 远高于净收益就是信号。 -->
      <p v-if="profitGiveBack" class="form-hint">
        持有期内最大浮盈均值 {{ signed(backtestResult.metrics.avg_mfe) }}，而最终净收益只有
        {{ signed(backtestResult.metrics.avg_net_return) }}——利润在回吐，值得试试更早的止盈。
      </p>
      <p v-if="backtestResult.metrics.caution" class="form-error">
        ⚠ {{ backtestResult.metrics.caution }}
      </p>
      <dl class="kv">
        <div><dt>退出原因</dt><dd>{{ exitReasons }}</dd></div>
        <div><dt>平均持有</dt><dd>{{ backtestResult.metrics.avg_hold_days }} 日</dd></div>
        <div v-if="backtestResult.metrics.avg_alpha !== undefined">
          <dt>相对基准超额</dt><dd>{{ signed(backtestResult.metrics.avg_alpha) }}</dd>
        </div>
      </dl>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  CapabilityUnavailableError,
  getMarketCoverage,
  getStrategies,
  runBacktest,
  runScreen,
} from '@/api/quant'
import { toneClass } from '@/lib/format'
import type { BacktestResult, MarketCoverage, ScreenResult, StrategyInfo } from '@/types/quant'

const strategies = ref<StrategyInfo[]>([])
const coverage = ref<MarketCoverage | null>(null)
const screenResult = ref<ScreenResult | null>(null)
const backtestResult = ref<BacktestResult | null>(null)
const busy = ref(false)
const unavailable = ref('')

/** 因子列取所有入选标的的并集，保证列头稳定，不会因为某只票缺一项就错位。 */
const factorKeys = computed(() => {
  const keys = new Set<string>()
  for (const pick of screenResult.value?.picks ?? []) {
    for (const [key, value] of Object.entries(pick.factors)) {
      if (typeof value === 'number') keys.add(key)
    }
  }
  return [...keys]
})

const exitReasons = computed(() => {
  const reasons = backtestResult.value?.metrics.exit_reasons ?? {}
  const labels: Record<string, string> = {
    hold_expired: '到期',
    stop_loss: '止损',
    take_profit: '止盈',
    data_end: '数据到头',
  }
  return Object.entries(reasons)
    .map(([key, count]) => `${labels[key] ?? key} ${count}`)
    .join(' · ') || '—'
})

const profitGiveBack = computed(() => {
  const metrics = backtestResult.value?.metrics
  if (!metrics?.trades || metrics.avg_mfe === undefined || metrics.avg_net_return === undefined) {
    return false
  }
  return metrics.avg_mfe - metrics.avg_net_return > 2
})

function fmt(value: number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '✓' : '—'
  return Number(value).toFixed(2)
}

function signed(value: number | undefined): string {
  if (value === undefined) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

async function guard<T>(task: () => Promise<T>): Promise<T | null> {
  busy.value = true
  unavailable.value = ''
  try {
    return await task()
  } catch (caught: unknown) {
    if (caught instanceof CapabilityUnavailableError) {
      unavailable.value = caught.message
    } else {
      unavailable.value = caught instanceof Error ? caught.message : '请求失败'
    }
    return null
  } finally {
    busy.value = false
  }
}

async function reload(): Promise<void> {
  await guard(async () => {
    const [list, cov] = await Promise.all([getStrategies(), getMarketCoverage()])
    strategies.value = list
    coverage.value = cov
  })
}

async function screen(slug: string): Promise<void> {
  backtestResult.value = null
  const result = await guard(() => runScreen({ strategy: slug }))
  if (result) screenResult.value = result
}

async function backtest(slug: string): Promise<void> {
  screenResult.value = null
  const result = await guard(() =>
    runBacktest({ strategy: slug, hold_days: 3, stop_loss_pct: -6, benchmark: '000300' }),
  )
  if (result) backtestResult.value = result
}

onMounted(reload)
</script>
