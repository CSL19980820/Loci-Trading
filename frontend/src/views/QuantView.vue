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
              <button class="quiet-button" type="button" :disabled="busy" @click="screen(item.slug)">选股</button>
              <button class="quiet-button" type="button" :disabled="busy" @click="backtest(item.slug)">回测</button>
              <button
                class="quiet-button"
                type="button"
                :class="{ 'text-link': configTarget === item.slug }"
                @click="toggleConfig(item.slug)"
              >
                {{ configTarget === item.slug ? '收起' : '配置' }}
              </button>
            </td>
          </tr>
          <template v-for="item in strategies" :key="`cfg-${item.slug}`">
            <tr v-if="configTarget === item.slug" class="config-row">
              <td colspan="5">
                <div class="strategy-config">
                  <h3>{{ item.name }} — 定时选股配置</h3>
                  <form class="config-form" @submit.prevent="saveConfig(item.slug)">
                    <div class="config-grid">
                      <label>
                        Cron 表达式
                        <input v-model.trim="configForm.cron" placeholder="45 15 * * 1-5（留空=仅手动）" />
                      </label>
                      <label>
                        每次取前 N 名
                        <input v-model.number="configForm.top_n" type="number" min="0" max="200" placeholder="0=不限" />
                      </label>
                      <label>
                        验证交易日数
                        <input v-model.number="configForm.trading_days" type="number" min="1" max="500" />
                      </label>
                      <label>
                        默认持有天数
                        <input v-model.number="configForm.hold_days" type="number" min="1" max="250" />
                      </label>
                      <label>
                        止损 %（负数）
                        <input v-model.number="configForm.stop_loss_pct" type="number" step="0.5" placeholder="-6" />
                      </label>
                    </div>
                    <div class="config-checks">
                      <label class="checkbox-label">
                        <input v-model="configForm.auto_review" type="checkbox" />
                        自动复盘（选完写入候选池，记录选股来源）
                      </label>
                      <label class="checkbox-label">
                        <input v-model="configForm.enabled" type="checkbox" />
                        启用定时任务
                      </label>
                    </div>
                    <div class="dialog-actions">
                      <button
                        v-if="strategyJobs[item.slug]?.bound"
                        class="quiet-button"
                        type="button"
                        :disabled="busy"
                        @click="removeConfig(item.slug)"
                      >
                        解除绑定
                      </button>
                      <button class="quiet-button" type="button" @click="configTarget = ''">取消</button>
                      <button class="primary-button" type="submit" :disabled="busy">保存</button>
                    </div>
                  </form>
                  <p v-if="strategyJobs[item.slug]?.bound" class="form-hint">
                    已绑定：cron <code>{{ strategyJobs[item.slug].cron || '手动' }}</code>，
                    自动复盘 {{ strategyJobs[item.slug].config?.record_candidates ? '开' : '关' }}，
                    top_n {{ strategyJobs[item.slug].config?.top_n || '不限' }}
                  </p>
                  <p class="form-hint">
                    「自动复盘」开启后每次运行选股会把入选标的写入候选池（pool_id = 战法@日期），
                    T+N 验证才能有数据。top_n=0 表示不限制。
                  </p>
                </div>
              </td>
            </tr>
          </template>
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

  <!-- 横向对比与退出扫描：分钟级任务，后台跑 + 轮询 -->
  <section class="panel mb">
    <div class="panel-bar">
      <h2>分析</h2>
      <span v-if="analysisBusy" class="muted mono">{{ analysisLabel }} 运行中…</span>
    </div>
    <div class="analysis-actions">
      <button class="quiet-button" type="button" :disabled="analysisBusy" @click="runCompare">
        横向对比全部战法
      </button>
      <select v-model="optimizeTarget" :disabled="analysisBusy">
        <option value="">选一个战法扫描退出规则</option>
        <option v-for="item in strategies" :key="item.slug" :value="item.slug">
          {{ item.name }}
        </option>
      </select>
      <button
        class="quiet-button"
        type="button"
        :disabled="analysisBusy || !optimizeTarget"
        @click="runOptimize"
      >
        扫描退出规则
      </button>
      <label class="inline-field">
        起始
        <input v-model="analysisStart" type="date" :disabled="analysisBusy" />
      </label>
    </div>
    <p class="form-hint">
      对比按<strong>超额</strong>排序而不是绝对收益——大盘涨的时候什么都赚。
      「回吐」= MFE 均值 − 净收益均值，即持有期内的浮盈最终没拿住多少；
      多数战法回吐都大，说明问题在退出纪律而不在选股。
    </p>
    <p v-if="analysisBusy" class="form-hint">
      全市场跑一轮通常要几十秒到几分钟。可以离开本页，结果会留在运维页的执行历史里。
    </p>

    <div v-if="compareResult" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>战法</th><th class="r">笔数</th><th class="r">胜率</th>
            <th class="r">净收益</th><th class="r">MFE</th><th class="r">MAE</th>
            <th class="r">超额</th><th class="r">回吐</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in compareResult.rows" :key="row.label">
            <td><strong>{{ row.label }}</strong></td>
            <td class="r mono">{{ row.trades.toLocaleString('zh-CN') }}</td>
            <td class="r mono">{{ row.win_rate.toFixed(1) }}%</td>
            <td class="r mono" :class="toneClass(row.avg_net_return)">{{ signed(row.avg_net_return) }}</td>
            <td class="r mono tone-up">{{ signed(row.avg_mfe ?? undefined) }}</td>
            <td class="r mono tone-down">{{ signed(row.avg_mae ?? undefined) }}</td>
            <td class="r mono" :class="toneClass(row.avg_alpha ?? 0)">
              <strong>{{ signed(row.avg_alpha ?? undefined) }}</strong>
            </td>
            <td class="r mono">
              {{ row.give_back.toFixed(2) }}%<span v-if="row.give_back > 4" class="tone-down"> ⚠</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="compareResult?.hint" class="form-hint highlight-hint">→ {{ compareResult.hint }}</p>

    <template v-if="optimizeResult">
      <div class="table-wrap">
        <table class="dense">
          <thead>
            <tr>
              <th class="r">持有</th><th class="r">止盈</th><th class="r">止损</th>
              <th class="r">笔数</th><th class="r">胜率</th><th class="r">净收益</th>
              <th class="r">超额</th><th>退出分布</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in optimizeResult.rows.slice(0, 12)" :key="index">
              <td class="r mono">{{ row.hold_days }}d</td>
              <td class="r mono">{{ row.take_profit_pct ? signed(row.take_profit_pct) : '—' }}</td>
              <td class="r mono">{{ row.stop_loss_pct ? signed(row.stop_loss_pct) : '—' }}</td>
              <td class="r mono">{{ row.trades }}</td>
              <td class="r mono">{{ row.win_rate.toFixed(1) }}%</td>
              <td class="r mono" :class="toneClass(row.avg_net_return)">{{ signed(row.avg_net_return) }}</td>
              <td class="r mono" :class="toneClass(row.avg_alpha ?? 0)">
                <strong>{{ signed(row.avg_alpha ?? undefined) }}</strong>
              </td>
              <td class="dim mono">{{ exitDist(row.exit_reasons) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="optimizeResult.best" class="form-hint highlight-hint">
        → 最优：持有 {{ optimizeResult.best.hold_days }} 日{{
          optimizeResult.best.take_profit_pct
            ? `，止盈 ${signed(optimizeResult.best.take_profit_pct)}`
            : '，不设止盈'
        }}{{
          optimizeResult.best.stop_loss_pct
            ? `，止损 ${signed(optimizeResult.best.stop_loss_pct)}`
            : '，不设止损'
        }}<span v-if="optimizeResult.improvement !== null">
          （比只按持有期了结高 {{ signed(optimizeResult.improvement) }}）</span>
      </p>
      <p class="form-error">⚠ {{ optimizeResult.warning }}</p>
    </template>
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
import { computed, onMounted, reactive, ref } from 'vue'

import {
  CapabilityUnavailableError,
  awaitJobResult,
  getMarketCoverage,
  getStrategies,
  getStrategyJob,
  runBacktest,
  runScreen,
  startAnalysis,
  unbindStrategyJob,
  upsertStrategyJob,
} from '@/api/quant'
import { toneClass } from '@/lib/format'
import type {
  BacktestResult,
  CompareResult,
  MarketCoverage,
  OptimizeResult,
  ScreenResult,
  StrategyInfo,
  StrategyJob,
} from '@/types/quant'

const strategies = ref<StrategyInfo[]>([])
const coverage = ref<MarketCoverage | null>(null)
const screenResult = ref<ScreenResult | null>(null)
const backtestResult = ref<BacktestResult | null>(null)
const busy = ref(false)
const unavailable = ref('')

const compareResult = ref<CompareResult | null>(null)
const optimizeResult = ref<OptimizeResult | null>(null)
const analysisBusy = ref(false)
const analysisLabel = ref('')
const optimizeTarget = ref('')
const analysisStart = ref('2025-01-01')

// ---- 策略配置 -------------------------------------------------------
const configTarget = ref('')   // 当前展开配置面板的 slug
const strategyJobs = ref<Record<string, StrategyJob>>({})  // slug → job
const configForm = reactive({
  cron: '',
  auto_review: false,
  trading_days: 60,
  top_n: 3,    // 默认取前3名
  hold_days: 3,
  stop_loss_pct: -6,
  enabled: true,
})

async function toggleConfig(slug: string): Promise<void> {
  if (configTarget.value === slug) {
    configTarget.value = ''
    return
  }
  configTarget.value = slug
  // 加载现有配置
  try {
    const job = await getStrategyJob(slug)
    strategyJobs.value[slug] = job
    if (job.bound) {
      const cfg = job.config ?? {}
      configForm.cron = job.cron ?? ''
      configForm.auto_review = Boolean(cfg.record_candidates)
      configForm.trading_days = Number(cfg.trading_days ?? 60)
      configForm.top_n = Number(cfg.top_n ?? 0)
      configForm.hold_days = Number(cfg.hold_days ?? 3)
      configForm.stop_loss_pct = cfg.stop_loss_pct !== undefined ? Number(cfg.stop_loss_pct) : -6
      configForm.enabled = job.enabled
    } else {
      Object.assign(configForm, { cron: '', auto_review: false, trading_days: 60, top_n: 0, hold_days: 3, stop_loss_pct: -6, enabled: true })
    }
  } catch {
    Object.assign(configForm, { cron: '', auto_review: false, trading_days: 60, top_n: 0, hold_days: 3, stop_loss_pct: -6, enabled: true })
  }
}

async function saveConfig(slug: string): Promise<void> {
  busy.value = true
  unavailable.value = ''
  try {
    const job = await upsertStrategyJob(slug, {
      cron: configForm.cron,
      auto_review: configForm.auto_review,
      trading_days: configForm.trading_days,
      top_n: configForm.top_n,
      hold_days: configForm.hold_days,
      stop_loss_pct: configForm.stop_loss_pct,
      enabled: configForm.enabled,
    })
    strategyJobs.value[slug] = job
    unavailable.value = ''
    configTarget.value = ''
  } catch (e: unknown) {
    unavailable.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function removeConfig(slug: string): Promise<void> {
  busy.value = true
  try {
    await unbindStrategyJob(slug)
    const job = await getStrategyJob(slug)
    strategyJobs.value[slug] = job
    configTarget.value = ''
  } catch (e: unknown) {
    unavailable.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    busy.value = false
  }
}

// ---- 通用 -----------------------------------------------------------

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

function exitDist(reasons: Record<string, number>): string {
  const labels: Record<string, string> = {
    hold_expired: '到期', stop_loss: '止损', take_profit: '止盈', data_end: '无数据',
  }
  return Object.entries(reasons)
    .map(([key, count]) => `${labels[key] ?? key}${count}`)
    .join(' ')
}

async function runAnalysis(
  kind: 'compare' | 'optimize',
  payload: Record<string, unknown>,
): Promise<unknown> {
  analysisBusy.value = true
  analysisLabel.value = kind === 'compare' ? '横向对比' : '退出扫描'
  unavailable.value = ''
  compareResult.value = null
  optimizeResult.value = null
  try {
    const started = await startAnalysis(kind, payload)
    const run = await awaitJobResult(started.job_id)
    if (run.status === 'failed') {
      unavailable.value = run.error_text.split('\n')[0] || '分析失败'
      return null
    }
    return run.result
  } catch (caught: unknown) {
    unavailable.value =
      caught instanceof CapabilityUnavailableError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : '分析失败'
    return null
  } finally {
    analysisBusy.value = false
    analysisLabel.value = ''
  }
}

async function runCompare(): Promise<void> {
  const result = await runAnalysis('compare', { start: analysisStart.value, holds: [1, 3] })
  if (result) compareResult.value = result as CompareResult
}

async function runOptimize(): Promise<void> {
  if (!optimizeTarget.value) return
  const result = await runAnalysis('optimize', {
    strategy: optimizeTarget.value,
    start: analysisStart.value,
    holds: [1, 2, 3, 5],
    targets: [0, 3, 5, 8],
    stops: [0, -5, -8],
  })
  if (result) optimizeResult.value = result as OptimizeResult
}

onMounted(reload)
</script>

<style scoped>
.config-row > td {
  padding: 0;
  border-top: none;
}
.strategy-config {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  margin: 4px 0 8px;
}
.strategy-config h3 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--muted);
}
.config-form { display: flex; flex-direction: column; gap: 10px; }
.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.config-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.config-grid input { padding: 4px 8px; border: 1px solid var(--line-2); border-radius: 6px; }
.config-checks { display: flex; gap: 16px; flex-wrap: wrap; }
.checkbox-label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
</style>
