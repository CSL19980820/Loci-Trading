import { computed, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import { runBacktest, runHorizonBacktest } from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
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

export function useQuantBacktestPanel(opts: {
  strategies: Ref<StrategyInfo[]>
  lockedSlug?: Ref<string | undefined>
}) {
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
    selected,
    (s) => {
      if (!s) return
      const cfg = (s.backtest_config || {}) as Record<string, unknown>
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
    if (mode.value === 'horizon' && span > 186) {
      ElMessage.warning('Horizon 一次性回测最长约 6 个月（186 天）')
      return
    }

    busy.value = true
    try {
      if (mode.value === 'horizon') {
        const next = await runHorizonBacktest({
          strategy: strategySlug.value,
          start,
          end,
          horizons: [1, 3],
        })
        horizonResult.value = next
        const n1 = next.horizons.t1?.n ?? 0
        const n3 = next.horizons.t3?.n ?? 0
        if (!n1 && !n3) ElMessage.info('区间内没有可评估的信号事件')
        else ElMessage.success(`Horizon 完成 · T+1 ${n1} 笔 · T+3 ${n3} 笔`)
      } else {
        const next = await runBacktest({
          strategy: strategySlug.value,
          start,
          end,
          mode: 'trade',
          hold_days: holdDays.value,
          stop_loss_pct: stopLossEnabled.value ? stopLossPct.value : null,
          commission_bps: commissionBps.value,
          stamp_duty_bps: stampDutyBps.value,
          slippage_bps: slippageBps.value,
          include_trades: true,
        })
        tradeResult.value = next
        const n = next.metrics?.trades ?? 0
        if (!n) ElMessage.info('区间内没有可评估成交')
        else ElMessage.success(`成交回测完成 · ${n} 笔`)
      }
    } catch (caught: unknown) {
      errorText.value = toErrorMessage(caught, '回测失败')
      ElMessage.error(errorText.value)
    } finally {
      busy.value = false
    }
  }

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
    skippedText,
  }
}
