import { computed, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import { runBacktest, runHorizonBacktest } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import { useBacktestPanelStore } from '@/shared/stores/backtestPanel'
import type { StrategyBacktestTemplate } from '@/shared/types/backtest-config'
import type {
  BacktestResult,
  HorizonBacktestResult,
  StrategyInfo,
} from '@/shared/types/quant'

import {
  loadBacktestPrefs,
  saveBacktestPrefs,
  skippedText,
} from './quantBacktestSummary'

export type BacktestMode = 'horizon' | 'trade'

function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function rangeEndingToday(daysBack: number): [string, string] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - daysBack)
  return [iso(start), iso(end)]
}

/** 回测面板对外的契约（模板与测试都按这个名字走，别再 ReturnType 反推）。 */
export interface QuantBacktestPanel {
  strategySlug: Ref<string>
  range: Ref<[string, string] | null>
  mode: Ref<BacktestMode>
  busy: Ref<boolean>
  /** 本次回测真实已耗时（秒）；没有服务端百分比，就别编一个 */
  elapsedSec: Ref<number>
  expectedHint: ComputedRef<string>
  horizonResult: Ref<HorizonBacktestResult | null>
  tradeResult: Ref<BacktestResult | null>
  errorText: Ref<string>
  activePreset: Ref<30 | 90 | 180 | null>
  showCost: Ref<boolean>
  holdDays: Ref<number>
  stopLossEnabled: Ref<boolean>
  stopLossPct: Ref<number>
  commissionBps: Ref<number>
  stampDutyBps: Ref<number>
  slippageBps: Ref<number>
  selected: ComputedRef<StrategyInfo | null>
  entryLabel: ComputedRef<string>
  entryDetail: ComputedRef<string>
  subtitle: ComputedRef<string>
  rangeShortcuts: { text: string; value: () => [Date, Date] }[]
  tripCostPct: ComputedRef<number>
  resultMeta: ComputedRef<string>
  rangeLabel: ComputedRef<string>
  activeHasResult: ComputedRef<boolean>
  applyPreset: (daysBack: 30 | 90 | 180) => void
  onRangeChange: () => void
  disabledDate: (date: Date) => boolean
  run: () => Promise<void>
  /** 停止等待本次回测：abort 请求并作废回写 */
  stop: () => void
  skippedText: (skipped: Record<string, number> | undefined) => string
}

export function useQuantBacktestPanel(opts: {
  strategies: Ref<StrategyInfo[]>
  lockedSlug?: Ref<string | undefined>
}): QuantBacktestPanel {
  const prefs = loadBacktestPrefs()

  const strategySlug = ref('')
  const range = ref<[string, string] | null>(prefs.range ?? rangeEndingToday(90))
  const mode = ref<BacktestMode>(prefs.mode === 'trade' ? 'trade' : 'horizon')
  const busy = ref(false)
  const horizonResult = ref<HorizonBacktestResult | null>(null)
  const tradeResult = ref<BacktestResult | null>(null)
  const errorText = ref('')
  const activePreset = ref<30 | 90 | 180 | null>(prefs.activePreset ?? 90)
  const showCost = ref(false)

  const cache = useBacktestPanelStore()
  /** 工坊面板与策稿页锁定战法的面板各存各的结果 */
  const cacheScope = computed(() => opts.lockedSlug?.value || '__workshop__')

  /**
   * 回测是一次几十秒的同步 POST，没有服务端进度可读——所以这里给的是**真实
   * 已耗时**，不是编出来的百分比。停止按钮靠 controller 断掉等待。
   */
  const elapsedSec = ref(0)
  let controller: AbortController | null = null
  let runToken = 0
  let ticker: number | undefined

  const holdDays = ref(prefs.holdDays ?? 3)
  const stopLossEnabled = ref(prefs.stopLossEnabled !== false)
  const stopLossPct = ref(prefs.stopLossPct ?? -6)
  const commissionBps = ref(prefs.commissionBps ?? 3)
  const stampDutyBps = ref(prefs.stampDutyBps ?? 10)
  const slippageBps = ref(prefs.slippageBps ?? 5)

  watch(
    () => opts.lockedSlug?.value,
    (slug) => {
      if (slug) strategySlug.value = slug
    },
    { immediate: true },
  )

  const selected = computed(
    () =>
      opts.strategies.value.find(
        (s) => s.slug === (opts.lockedSlug?.value || strategySlug.value),
      ) ?? null,
  )

  watch(
    () => selected.value?.slug,
    () => {
      const s = selected.value
      if (!s) return
      const cfg = (s.backtest_config || {}) as StrategyBacktestTemplate
      const fromCfg = Number(cfg.hold_days)
      const fromParams = Number(s.params?.hold_days)
      if (Number.isFinite(fromCfg) && fromCfg > 0) holdDays.value = fromCfg
      else if (Number.isFinite(fromParams) && fromParams > 0) holdDays.value = fromParams
      if (typeof cfg.stop_loss_pct === 'number') {
        stopLossPct.value = cfg.stop_loss_pct
        stopLossEnabled.value = true
      } else if (cfg.stop_loss_pct === null) {
        stopLossEnabled.value = false
      }
      if (typeof cfg.commission_bps === 'number') commissionBps.value = cfg.commission_bps
      if (typeof cfg.stamp_duty_bps === 'number') stampDutyBps.value = cfg.stamp_duty_bps
      if (typeof cfg.slippage_bps === 'number') slippageBps.value = cfg.slippage_bps
      if (cfg.start && cfg.end) {
        range.value = [cfg.start, cfg.end]
        activePreset.value = null
      }
      if (cfg.signal_dataset) mode.value = 'trade'
    },
    { immediate: true },
  )

  watch(
    () => opts.strategies.value,
    (list) => {
      if (!strategySlug.value && list.length) strategySlug.value = list[0].slug
      if (strategySlug.value && !list.some((s) => s.slug === strategySlug.value)) {
        strategySlug.value = list[0]?.slug ?? ''
      }
    },
    { immediate: true },
  )

  watch(
    [
      mode,
      range,
      activePreset,
      holdDays,
      stopLossEnabled,
      stopLossPct,
      commissionBps,
      stampDutyBps,
      slippageBps,
    ],
    () => {
      saveBacktestPrefs({
        mode: mode.value,
        range: range.value,
        activePreset: activePreset.value,
        holdDays: holdDays.value,
        stopLossEnabled: stopLossEnabled.value,
        stopLossPct: stopLossPct.value,
        commissionBps: commissionBps.value,
        stampDutyBps: stampDutyBps.value,
        slippageBps: slippageBps.value,
      })
    },
    { deep: true },
  )

  const entryTiming = computed(
    () => selected.value?.entry_timing || horizonResult.value?.entry_timing || '',
  )

  const entryLabel = computed(() => {
    const timing = entryTiming.value
    if (timing === 'close') return '尾盘买'
    if (timing === 'next_dip') return '次日低吸'
    if (timing === 'next_open') return '次日开'
    if (timing === 'open') return '开盘买'
    return timing || '—'
  })

  const entryDetail = computed(() => {
    if (mode.value === 'trade') {
      if (selected.value?.backtest_config?.signal_dataset) {
        return `持有期 ${holdDays.value} 表示买入后 ${holdDays.value} 个交易日（含买入日 ${holdDays.value + 1} 日）· 费用为实验假设`
      }
      return '按入场价模拟买卖（止损/持有期）· 成本计入净收益'
    }
    const timing = entryTiming.value
    if (timing === 'close') return '选股日收盘入场 · T+N 看其后第 N 日最高'
    if (timing === 'next_dip') return '选股日后挂 2% 低吸单 · 成交后看其后第 N 日最高'
    if (timing === 'next_open') return '选股日后一交易日开盘入场 · T+1 约看第 2 日最高'
    if (timing === 'open') return '选股日开盘入场 · T+N 看其后第 N 日最高'
    return '入场时点以战法声明为准'
  })

  const subtitle = computed(() =>
    mode.value === 'horizon'
      ? '标记日最高 ÷ 选股日收盘 · 最长 6 个月'
      : '成交回测 · 顺序复利诊断曲线（非真实多仓）',
  )

  const rangeShortcuts = [
    {
      text: '近一月',
      value: () => {
        const end = new Date()
        const start = new Date()
        start.setDate(start.getDate() - 30)
        return [start, end] as [Date, Date]
      },
    },
    {
      text: '近三月',
      value: () => {
        const end = new Date()
        const start = new Date()
        start.setDate(start.getDate() - 90)
        return [start, end] as [Date, Date]
      },
    },
    {
      text: '近六月',
      value: () => {
        const end = new Date()
        const start = new Date()
        start.setDate(start.getDate() - 180)
        return [start, end] as [Date, Date]
      },
    },
  ]

  function applyPreset(daysBack: 30 | 90 | 180): void {
    activePreset.value = daysBack
    range.value = rangeEndingToday(daysBack)
  }

  function onRangeChange(): void {
    activePreset.value = null
  }

  const disabledDate = (date: Date): boolean => {
    const today = new Date()
    today.setHours(23, 59, 59, 999)
    return date.getTime() > today.getTime()
  }

  const tripCostPct = computed(
    () => (commissionBps.value * 2 + stampDutyBps.value + slippageBps.value * 2) / 100,
  )

  /** `战法|开始|结束`——换一组输入，暂存的结果就不该再贴回来。 */
  const resultKey = computed(
    () => `${strategySlug.value}|${range.value?.[0] ?? ''}|${range.value?.[1] ?? ''}`,
  )

  /** 开跑前就说清楚要等多久；藏在空态里等于没说。 */
  const expectedHint = computed(() =>
    mode.value === 'horizon'
      ? '全市场逐日回放，一次通常要几十秒；区间越长越久'
      : '逐笔模拟买卖，全市场一次通常要几十秒到一两分钟',
  )

  function stopTicker(): void {
    if (ticker != null) {
      window.clearInterval(ticker)
      ticker = undefined
    }
  }

  /**
   * 停止等待这次回测。
   *
   * token 先自增再 abort：即便请求已经在返回路上，回来的那一份也会被下面的
   * 守卫丢掉，不会在用户停手之后再把结果/报错糊回界面。
   */
  function stop(): void {
    if (!busy.value) return
    runToken += 1
    controller?.abort('用户停止回测')
    controller = null
    stopTicker()
    busy.value = false
    errorText.value = ''
    ElMessage.info('已停止等待 · 这一次的结果不会再回写')
  }

  async function run(): Promise<void> {
    errorText.value = ''
    if (!strategySlug.value) {
      ElMessage.warning('请先选择战法')
      return
    }
    if (!range.value?.[0] || !range.value?.[1]) {
      ElMessage.warning('请选择回测区间')
      return
    }
    const [start, end] = range.value
    const span = (Date.parse(end) - Date.parse(start)) / 86_400_000
    if (span < 0) {
      ElMessage.warning('结束日不能早于开始日')
      return
    }
    if (mode.value === 'horizon' && selected.value?.backtest_config?.signal_dataset) {
      ElMessage.warning('该战法的历史14:50数据用于成交回测，请选择成交模式')
      return
    }
    if (mode.value === 'horizon' && span > 186) {
      ElMessage.warning('Horizon 一次性回测最长约 6 个月（186 天）')
      return
    }

    const token = ++runToken
    const ctrl = new AbortController()
    controller = ctrl
    busy.value = true
    elapsedSec.value = 0
    const startedAt = Date.now()
    stopTicker()
    ticker = window.setInterval(() => {
      elapsedSec.value = Math.floor((Date.now() - startedAt) / 1000)
    }, 1000)
    try {
      if (mode.value === 'horizon') {
        const next = await runHorizonBacktest(
          {
            strategy: strategySlug.value,
            start,
            end,
            horizons: [1, 3],
          },
          { signal: ctrl.signal },
        )
        if (token !== runToken) return
        horizonResult.value = next
        rememberResults()
        const n1 = next.horizons.t1?.n ?? 0
        const n3 = next.horizons.t3?.n ?? 0
        if (!n1 && !n3) ElMessage.info('区间内没有可评估的信号事件')
        else ElMessage.success(`Horizon 完成 · T+1 ${n1} 笔 · T+3 ${n3} 笔`)
      } else {
        const cfg = (selected.value?.backtest_config || {}) as StrategyBacktestTemplate
        const next = await runBacktest(
          {
            strategy: strategySlug.value,
            start,
            end,
            mode: 'trade',
            hold_days: holdDays.value,
            stop_loss_pct: stopLossEnabled.value ? stopLossPct.value : null,
            commission_bps: commissionBps.value,
            stamp_duty_bps: stampDutyBps.value,
            slippage_bps: slippageBps.value,
            ...(cfg.take_profit_pct !== undefined ? { take_profit_pct: cfg.take_profit_pct } : {}),
            ...(cfg.benchmark !== undefined ? { benchmark: cfg.benchmark } : {}),
            ...(cfg.strict_limit_prices !== undefined ? { strict_limit_prices: cfg.strict_limit_prices } : {}),
            ...(cfg.economic_returns !== undefined ? { economic_returns: cfg.economic_returns } : {}),
            ...(cfg.signal_dataset !== undefined ? { signal_dataset: cfg.signal_dataset } : {}),
            // 估值末日始终跟随本次用户选择，不能固化为模板创建时的日期。
            ...(cfg.valuation_end !== undefined ? { valuation_end: end } : {}),
            include_trades: true,
          },
          { signal: ctrl.signal },
        )
        if (token !== runToken) return
        tradeResult.value = next
        rememberResults()
        const n = next.metrics?.trades ?? 0
        if (!n) ElMessage.info('区间内没有可评估成交')
        else ElMessage.success(`成交回测完成 · ${n} 笔`)
      }
    } catch (caught: unknown) {
      // 用户停手 / 组件卸载：这次结果连同报错一起作废，不许再回写界面
      if (token !== runToken) return
      errorText.value = toErrorMessage(caught, '回测失败')
      ElMessage.error(errorText.value)
    } finally {
      if (controller === ctrl) controller = null
      if (token === runToken) {
        stopTicker()
        busy.value = false
      }
    }
  }

  function rememberResults(): void {
    cache.remember(cacheScope.value, {
      key: resultKey.value,
      horizon: horizonResult.value,
      trade: tradeResult.value,
    })
  }

  // 装载时把上一次的结果接回来（切 Tab 会卸载本组件），输入不同则不接
  const remembered = cache.recall(cacheScope.value, resultKey.value)
  if (remembered) {
    horizonResult.value = remembered.horizon
    tradeResult.value = remembered.trade
  }

  // 组件卸载（切 Tab / 离页）也作废在途请求，别让它回来写一个已经没人看的面板
  onUnmounted(() => {
    runToken += 1
    controller?.abort('面板已卸载')
    controller = null
    stopTicker()
  })

  const resultMeta = computed(() => {
    const start = range.value?.[0] || ''
    const end = range.value?.[1] || ''
    return `${strategySlug.value} · ${start} — ${end} · ${entryLabel.value}`
  })

  const rangeLabel = computed(() => {
    const start = range.value?.[0] || ''
    const end = range.value?.[1] || ''
    return `${start} — ${end}`
  })

  const activeHasResult = computed(() =>
    mode.value === 'horizon' ? !!horizonResult.value : !!tradeResult.value,
  )

  return {
    strategySlug,
    range,
    mode,
    busy,
    elapsedSec,
    expectedHint,
    horizonResult,
    tradeResult,
    errorText,
    activePreset,
    showCost,
    holdDays,
    stopLossEnabled,
    stopLossPct,
    commissionBps,
    stampDutyBps,
    slippageBps,
    selected,
    entryLabel,
    entryDetail,
    subtitle,
    rangeShortcuts,
    tripCostPct,
    resultMeta,
    rangeLabel,
    activeHasResult,
    applyPreset,
    onRangeChange,
    disabledDate,
    run,
    stop,
    skippedText,
  }
}
