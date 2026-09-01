<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { computed, ref, watch } from 'vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import KlineReadout from './KlineReadout.vue'
import MinuteSessionDialog from './MinuteSessionDialog.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
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
  if (!Number.isFinite(n)) return '—'
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
  <section class="tdx-desk">
    <header class="tdx-head">
      <el-button
        v-if="!embedded"
        class="tdx-back"
        size="small"
        @click="emit('close')"
      >
        返回
      </el-button>
      <div v-if="!embedded" class="tdx-id">
        <strong class="tdx-name">{{ detailName || detailCode }}</strong>
        <span class="mono tdx-code">{{ detailCode }}</span>
        <template v-if="quote">
          <span class="mono tdx-last" :class="chgClass(detailPct)">{{ lastClose }}</span>
          <span class="mono tdx-pct" :class="chgClass(detailPct)">{{ fmtPct(detailPct) }}</span>
        </template>
      </div>
      <div class="tdx-controls">
        <el-radio-group
          :model-value="period"
          size="small"
          class="tdx-btn-group"
          @update:model-value="emit('update:period', $event as KPeriod)"
        >
          <el-tooltip content="日 K 上双击某根 K 线可打开该日分时" placement="bottom" :show-after="300">
            <el-radio-button value="day">日K</el-radio-button>
          </el-tooltip>
          <el-radio-button value="week">周K</el-radio-button>
          <el-radio-button value="month">月K</el-radio-button>
        </el-radio-group>
        <el-radio-group
          :model-value="adjust"
          size="small"
          class="tdx-btn-group"
          @update:model-value="
            emit('update:adjust', $event as 'qfq' | 'hfq' | 'none');
            emit('adjustChange')
          "
        >
          <el-radio-button value="qfq">前复权</el-radio-button>
          <el-radio-button value="hfq">后复权</el-radio-button>
          <el-radio-button value="none">不复权</el-radio-button>
        </el-radio-group>
        <el-popover v-model:visible="maPopover" placement="bottom-end" :width="280" trigger="click">
          <template #reference>
            <el-button size="small" class="tdx-ma-btn">均线设置</el-button>
          </template>
          <p class="tdx-ma-pop__title">主图均线周期</p>
          <p class="tdx-ma-pop__hint">可改成 5 / 13 / 21 等；留空并应用 = 不画该线。全部清空则不显示均线。</p>
          <div class="tdx-ma-pop__list">
            <div v-for="(_, idx) in maDraft" :key="idx" class="tdx-ma-pop__row">
              <span class="tdx-ma-pop__label">MA{{ idx + 1 }}</span>
              <el-input
                v-model="maDraft[idx]"
                size="small"
                placeholder="周期"
                inputmode="numeric"
              />
              <el-button size="small" text type="danger" @click="removeMaSlot(idx)">删</el-button>
            </div>
          </div>
          <div class="tdx-ma-pop__actions">
            <el-button size="small" text @click="addMaSlot">加一行</el-button>
            <el-button size="small" text @click="resetMaDefault">恢复默认</el-button>
            <el-button size="small" text @click="clearAllMa">全清</el-button>
            <el-button size="small" type="primary" @click="applyMaDraft">应用</el-button>
          </div>
        </el-popover>
        <span v-if="quote" class="tdx-meta mono">{{ totalHint() }} · {{ adjustLabel }}</span>
      </div>
    </header>

    <div v-if="activeMas.length" class="tdx-ma-rail">
      <template v-if="locked">
        <span
          v-for="(m, idx) in locked.ma"
          :key="m.period"
          class="tdx-ma-rail__item mono"
          :style="{ color: MA_LINE_COLORS[idx % MA_LINE_COLORS.length] }"
        >
          MA{{ m.period }}:{{ fmtPx(m.value) }}
        </span>
      </template>
      <span v-else class="tdx-ma-rail__empty">移动十字光标查看均线</span>
    </div>

    <div class="tdx-chart-wrap" :style="gridTopVars">
      <PageBusy overlay :busy="busy" label="加载行情…" />
      <KlineChart
        v-if="quote"
        class="tdx-chart"
        :bars="quote.bars"
        :period="period"
        :indicator="indicator"
        :ma-periods="activeMas"
        :visible-bars="60"
        :stock-code="detailCode"
        :stock-name="detailName"
        :has-more-history="hasMoreHistory"
        :focus-date="focusDate || ''"
        :strategy-signals="strategySignals"
        @hover="onHover"
        @need-history="emit('needHistory')"
        @bar-dblclick="onBarDblclick"
      />
      <EmptyState v-else-if="!busy" description="该证券暂无本机日线。" />

      <KlineReadout
        v-if="showFloat && locked"
        :locked="locked"
        :detail-code="detailCode"
        :detail-name="detailName"
        @close="floatClosed = true"
      />

      <div v-if="locked && quote" class="tdx-pane tdx-pane--vol" aria-live="polite">
        <span class="tdx-pane__tag">量</span>
        <span class="mono tdx-pane__item">VOL:{{ fmtVol(locked.volume) }}</span>
        <span
          v-for="vm in locked.volumeMa"
          :key="vm.period"
          class="mono tdx-pane__item"
          :class="vm.period === 5 ? 'is-vma5' : 'is-vma60'"
        >
          MA{{ vm.period }}:{{ fmtVol(vm.value) }}
        </span>
      </div>

      <div v-if="quote" class="tdx-pane tdx-pane--ind" aria-live="polite">
        <el-radio-group
          class="tdx-ind-switch"
          size="small"
          :model-value="indicator"
          @update:model-value="emit('update:indicator', $event as IndicatorKind)"
        >
          <el-radio-button value="macd">MACD</el-radio-button>
          <el-radio-button value="kdj">KDJ</el-radio-button>
        </el-radio-group>
        <template v-if="locked && indicator === 'macd' && locked.macd">
          <span class="mono tdx-pane__item is-dif">DIF:{{ fmtInd(locked.macd.dif) }}</span>
          <span class="mono tdx-pane__item is-dea">DEA:{{ fmtInd(locked.macd.dea) }}</span>
          <span class="mono tdx-pane__item is-macd">MACD:{{ fmtInd(locked.macd.hist) }}</span>
        </template>
        <template v-else-if="locked && indicator === 'kdj' && locked.kdj">
          <span class="mono tdx-pane__item is-k">K:{{ fmtKd(locked.kdj.k) }}</span>
          <span class="mono tdx-pane__item is-d">D:{{ fmtKd(locked.kdj.d) }}</span>
          <span class="mono tdx-pane__item is-j">J:{{ fmtKd(locked.kdj.j) }}</span>
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
