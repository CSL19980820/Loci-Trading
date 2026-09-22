<script setup lang="ts">
import { useLocalStorage, useMediaQuery } from '@vueuse/core'
import { ArrowLeft, ChevronDown, Settings } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import KlineReadout from './KlineReadout.vue'
import MinuteSessionDialog from './MinuteSessionDialog.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import KlineChart, {
  type KlineBarDblclickPayload,
} from '@/shared/components/charts/KlineChart.vue'
import type { StrategySignalMark } from '@/shared/lib/klineStrategyMarks'
import {
  DEFAULT_MA_PERIODS,
  KLINE_GRID_TOPS,
  MA_LINE_COLORS,
  normalizeMaPeriods,
  type IndicatorKind,
  type KlineHoverPayload,
} from '@/shared/lib/klineConfig'
import { compactNumber } from '@/shared/lib/format'
import type { KPeriod } from '@/shared/lib/indicators'
import type { QuoteSeries } from '@/shared/types/quant'

import { chgClass, fmtPct } from '../composables/dataQueryFormat'

/**
 * K 线工作台卡：顶栏是两组药片分段（周期 / 复权）+ 均线设置 + 元信息；
 * 均线读数一行；主图 + 量 / 指标读数浮层。`embedded` 时身份与返回由外壳（档案页头）承担。
 */
const props = defineProps<{
  detailCode: string
  detailName: string
  quote: QuoteSeries | null
  busy: boolean
  period: KPeriod
  indicator: IndicatorKind
  adjust: 'qfq' | 'hfq' | 'none'
  adjustLabel: string
  lastClose: string
  detailPct: number | null
  /** 工作台内嵌时隐藏返回与身份（由外壳承担） */
  embedded?: boolean
  /** 锚定日 K 到该交易日 */
  focusDate?: string
  /** 策略选股信号标记 */
  strategySignals?: StrategySignalMark[]
}>()
const emit = defineEmits<{
  'update:period': [KPeriod]
  'update:indicator': [IndicatorKind]
  'update:adjust': ['qfq' | 'hfq' | 'none']
  close: []
  adjustChange: []
  needHistory: []
}>()

/** 主图均线周期（可改成 5/13/21…；空 = 不画） */
const maPeriods = useLocalStorage<number[]>('loci.market.maPeriods', [...DEFAULT_MA_PERIODS])
/** 设置弹层里编辑中的草稿（字符串，便于清空） */
const maDraft = ref<string[]>([])
const maPopover = ref(false)
const floatClosed = ref(false)
const mobile = useMediaQuery('(max-width:767px)')
const mobileReadoutOpen = ref(false)

const locked = ref<KlineHoverPayload | null>(null)
const minuteOpen = ref(false)
const minuteDate = ref('')
const minutePrevClose = ref<number | null>(null)

const activeMas = computed(() => normalizeMaPeriods(maPeriods.value))

/** 读数浮层与 ECharts grid 同源，改一处不会错位 */
const gridTopVars = computed(() => ({
  '--kline-vol-top': `${KLINE_GRID_TOPS.vol}%`,
  '--kline-ind-top': `${KLINE_GRID_TOPS.ind}%`,
}))

function totalHint(): string {
  const q = props.quote
  if (!q) return ''
  if (q.total_rows && q.total_rows > q.rows) return `${q.rows}/${q.total_rows}根`
  return `${q.rows}根`
}

function fmtPx(v: unknown): string {
  const n = Number(v)
  if (v == null || v === '' || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmtVol(v: unknown): string {
  return compactNumber(v)
}

function fmtInd(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(3)
}

function fmtKd(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

const showFloat = computed(() => Boolean(locked.value) && !floatClosed.value)

const hasMoreHistory = computed(() => {
  const q = props.quote
  if (!q) return false
  return Boolean(q.total_rows && q.total_rows > q.rows)
})

function syncMaDraft(): void {
  const cur = activeMas.value
  maDraft.value = (cur.length ? cur : [...DEFAULT_MA_PERIODS]).map(String)
  while (maDraft.value.length < 7) maDraft.value.push('')
}

function addMaSlot(): void {
  if (maDraft.value.length >= 8) return
  maDraft.value.push('')
}

function removeMaSlot(idx: number): void {
  maDraft.value.splice(idx, 1)
}

function applyMaDraft(): void {
  maPeriods.value = normalizeMaPeriods(maDraft.value)
  maPopover.value = false
}

function resetMaDefault(): void {
  maDraft.value = DEFAULT_MA_PERIODS.map(String)
}

function clearAllMa(): void {
  maDraft.value = ['', '', '', '', '', '', '']
}

function onHover(payload: KlineHoverPayload | null): void {
  if (!payload) return
  locked.value = payload
  floatClosed.value = false
}

function onBarDblclick(payload: KlineBarDblclickPayload): void {
  if (props.period !== 'day') return
  minuteDate.value = payload.tradeDate
  minutePrevClose.value = payload.prevClose
  minuteOpen.value = true
}

watch(maPopover, (open) => {
  if (open) syncMaDraft()
})

watch(
  () => props.quote,
  (q) => {
    if (!q?.bars?.length) locked.value = null
  },
)
</script>

<template>
  <section class="tdx-desk" :class="{ 'tdx-desk--embedded': embedded }">
    <header class="tdx-head">
      <Button access="read" v-if="!embedded" variant="ghost" size="icon-sm" class="tdx-back" aria-label="返回" @click="emit('close')">
        <ArrowLeft aria-hidden="true" />
      </Button>
      <div v-if="!embedded" class="tdx-id">
        <strong class="tdx-name">{{ detailName || detailCode }}</strong>
        <span class="tdx-code">{{ detailCode }}</span>
        <template v-if="quote">
          <span class="tdx-last" :class="chgClass(detailPct)">{{ lastClose }}</span>
          <span class="tdx-pct" :class="chgClass(detailPct)">{{ fmtPct(detailPct) }}</span>
        </template>
      </div>
      <div class="tdx-controls">
        <ToggleGroup
          type="single"
          :model-value="period"
          aria-label="K 线周期"
          class="tdx-seg"
          @update:model-value="emit('update:period', $event as KPeriod)"
        >
          <Tooltip>
            <TooltipTrigger as-child>
              <span class="tdx-seg__tip"><ToggleGroupItem value="day" class="tdx-seg__item">日K</ToggleGroupItem></span>
            </TooltipTrigger>
            <TooltipContent side="bottom">日 K 上双击某根 K 线可打开该日分时</TooltipContent>
          </Tooltip>
          <ToggleGroupItem value="week" class="tdx-seg__item">周K</ToggleGroupItem>
          <ToggleGroupItem value="month" class="tdx-seg__item">月K</ToggleGroupItem>
        </ToggleGroup>
        <Select v-if="mobile" :model-value="adjust" @update:model-value="value => { emit('update:adjust', value as 'qfq' | 'hfq' | 'none'); emit('adjustChange') }">
          <SelectTrigger class="tdx-mobile-adjust" aria-label="复权方式"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="qfq">前复权</SelectItem><SelectItem value="hfq">后复权</SelectItem><SelectItem value="none">不复权</SelectItem></SelectContent>
        </Select>
        <ToggleGroup v-else
          type="single"
          :model-value="adjust"
          aria-label="复权方式"
          class="tdx-seg"
          @update:model-value="
            emit('update:adjust', $event as 'qfq' | 'hfq' | 'none');
            emit('adjustChange')
          "
        >
          <ToggleGroupItem value="qfq" class="tdx-seg__item">前复权</ToggleGroupItem>
          <ToggleGroupItem value="hfq" class="tdx-seg__item">后复权</ToggleGroupItem>
          <ToggleGroupItem value="none" class="tdx-seg__item">不复权</ToggleGroupItem>
        </ToggleGroup>
        <Popover v-model:open="maPopover">
          <PopoverTrigger as-child>
            <Button access="read" variant="outline" size="sm" class="tdx-ma-btn" :aria-expanded="maPopover">
              <Settings aria-hidden="true" />
              <span>均线</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent side="bottom" align="end" class="w-[min(300px,calc(100vw-32px))] p-3">
            <p class="tdx-ma-pop__title">主图均线周期</p>
            <p class="tdx-ma-pop__hint">输入周期，留空可隐藏该条均线。</p>
            <div class="tdx-ma-pop__list">
              <div v-for="(_, idx) in maDraft" :key="idx" class="tdx-ma-pop__row">
                <span class="tdx-ma-pop__label">MA{{ idx + 1 }}</span>
                <Input
                  v-model="maDraft[idx]"
                  :aria-label="`第 ${idx + 1} 条均线周期`"
                  class="h-[var(--ctl-h-sm)]"
                  placeholder="周期"
                  inputmode="numeric"
                />
                <Button access="read" variant="ghost" size="sm" :aria-label="`删除第 ${idx + 1} 条均线`" @click="removeMaSlot(idx)">
                  删除
                </Button>
              </div>
            </div>
            <div class="tdx-ma-pop__actions">
              <Button access="read" variant="ghost" size="sm" :disabled="maDraft.length >= 8" @click="addMaSlot">加一行</Button>
              <Button access="read" variant="ghost" size="sm" @click="resetMaDefault">恢复默认</Button>
              <Button access="read" variant="ghost" size="sm" @click="clearAllMa">全清</Button>
              <Button access="read" size="sm" @click="applyMaDraft">应用</Button>
            </div>
          </PopoverContent>
        </Popover>
        <span v-if="quote && !mobile" class="tdx-meta">{{ totalHint() }} · {{ adjustLabel }}</span>
      </div>
    </header>

    <div v-if="activeMas.length" class="tdx-ma-rail">
      <template v-if="locked">
        <span
          v-for="(m, idx) in locked.ma"
          :key="m.period"
          class="tdx-ma-rail__item"
          :style="{ color: MA_LINE_COLORS[idx % MA_LINE_COLORS.length] }"
        >
          MA{{ m.period }} {{ fmtPx(m.value) }}
        </span>
      </template>
      <span v-else class="tdx-ma-rail__empty">移动十字光标查看均线读数</span>
    </div>

    <div v-if="mobile && locked" class="tdx-mobile-lock">
      <Button access="read" variant="ghost" type="button" class="tdx-mobile-lock-toggle" aria-label="展开K线读数" :aria-expanded="mobileReadoutOpen" @click="mobileReadoutOpen = !mobileReadoutOpen"><time>{{ locked.bar.trade_date.slice(0, 10) }}</time><span>收 <b>{{ fmtPx(locked.bar.close) }}</b></span><span class="tdx-readout-label">读数<ChevronDown :size="13" :class="{ 'is-open': mobileReadoutOpen }" /></span></Button>
      <KlineReadout v-if="mobileReadoutOpen" class="tdx-mobile-readout" :locked="locked" :detail-code="detailCode" :detail-name="detailName" @close="mobileReadoutOpen = false" />
    </div>
    <div class="tdx-chart-wrap" :style="gridTopVars">
      <PageBusy overlay :busy="busy" label="加载行情…" />
      <KlineChart
        v-if="quote?.bars?.length"
        class="tdx-chart"
        :bars="quote.bars"
        :period="period"
        :indicator="indicator"
        :ma-periods="activeMas"
        :visible-bars="mobile ? 40 : 60"
        :stock-code="detailCode"
        :stock-name="detailName"
        :has-more-history="hasMoreHistory"
        :focus-date="focusDate || ''"
        :strategy-signals="strategySignals"
        @hover="onHover"
        @need-history="emit('needHistory')"
        @bar-dblclick="onBarDblclick"
      />
      <EmptyState
        v-else-if="!busy"
        :description="quote ? '暂无 K 线' : '暂无日线'"
        reason="同步行情后再查看"
      />

      <KlineReadout
        v-if="!mobile && showFloat && locked"
        :locked="locked"
        :detail-code="detailCode"
        :detail-name="detailName"
        @close="floatClosed = true"
      />

      <div v-if="locked && quote" class="tdx-pane tdx-pane--vol" role="group" aria-label="成交量读数">
        <span class="tdx-pane__tag">量</span>
        <span class="tdx-pane__item">VOL {{ fmtVol(locked.volume) }}</span>
        <span
          v-for="vm in locked.volumeMa"
          :key="vm.period"
          class="tdx-pane__item"
          :class="vm.period === 5 ? 'is-vma5' : 'is-vma60'"
        >
          MA{{ vm.period }} {{ fmtVol(vm.value) }}
        </span>
      </div>

      <div v-if="quote" class="tdx-pane tdx-pane--ind" role="group" aria-label="指标读数">
        <ToggleGroup
          type="single"
          class="tdx-seg tdx-seg--mini tdx-ind-switch"
          aria-label="副图指标"
          :model-value="indicator"
          @update:model-value="emit('update:indicator', $event as IndicatorKind)"
        >
          <ToggleGroupItem value="macd" class="tdx-seg__item">MACD</ToggleGroupItem>
          <ToggleGroupItem value="kdj" class="tdx-seg__item">KDJ</ToggleGroupItem>
        </ToggleGroup>
        <template v-if="locked && indicator === 'macd' && locked.macd">
          <span class="tdx-pane__item is-dif">DIF {{ fmtInd(locked.macd.dif) }}</span>
          <span class="tdx-pane__item is-dea">DEA {{ fmtInd(locked.macd.dea) }}</span>
          <span class="tdx-pane__item is-macd">MACD {{ fmtInd(locked.macd.hist) }}</span>
        </template>
        <template v-else-if="locked && indicator === 'kdj' && locked.kdj">
          <span class="tdx-pane__item is-k">K {{ fmtKd(locked.kdj.k) }}</span>
          <span class="tdx-pane__item is-d">D {{ fmtKd(locked.kdj.d) }}</span>
          <span class="tdx-pane__item is-j">J {{ fmtKd(locked.kdj.j) }}</span>
        </template>
      </div>
    </div>
  </section>

  <MinuteSessionDialog
    v-model="minuteOpen"
    :code="detailCode"
    :name="detailName"
    :trade-date="minuteDate"
    :prev-close="minutePrevClose"
    :adjust="adjust"
  />
</template>

<style scoped src="./DataQueryDetailPanel.css"></style>
<style scoped src="./DataQueryDetailPanel.mobile.css"></style>
