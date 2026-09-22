<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { computed, ref, useId } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { Info } from '@lucide/vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import type { AgentEquity } from '@/shared/types/stock_agents'
import { agentMoney, agentTime } from '../agentFormat'
const props = defineProps<{ points: AgentEquity[]; loading?: boolean; error?: string }>()
const mode = ref('pnl')
const selected = ref<number | null>(null)
const mobile = useMediaQuery('(max-width: 640px)')
const gradientId = `equity-fill-${useId()}`
const chartWidth = computed(() => mobile.value ? 420 : 900)
const left = 70
const right = computed(() => chartWidth.value - 22)
const plotWidth = computed(() => right.value - left)
const values = computed(() => props.points.map(p => (mode.value === 'pnl' ? p.pnl_cents : p.equity_cents) / 100))
const bounds = computed(() => {
  const low = Math.min(...values.value, mode.value === 'pnl' ? 0 : Infinity)
  const high = Math.max(...values.value, mode.value === 'pnl' ? 0 : -Infinity)
  if (!Number.isFinite(low) || !Number.isFinite(high)) return { low: 0, high: 1 }
  const pad = Math.max((high - low) * .18, Math.max(Math.abs(high) * .001, 1))
  return { low: low - pad, high: high + pad }
})
const y = (value: number) => 200 - (value - bounds.value.low) / (bounds.value.high - bounds.value.low) * 180
const x = (index: number) => props.points.length <= 1 ? (left + right.value) / 2 : left + index / (props.points.length - 1) * plotWidth.value
const coordinates = computed(() => values.value.map((v, i) => `${x(i)},${y(v)}`).join(' '))
const areaPath = computed(() => {
  if (props.points.length < 2) return ''
  const base = mode.value === 'pnl' ? y(0) : 203
  return `M${x(0)},${base} L${coordinates.value.split(' ').join(' L')} L${x(props.points.length - 1)},${base} Z`
})
const current = computed(() => selected.value == null ? props.points.at(-1) : props.points[selected.value])
const last = computed(() => props.points.at(-1))
const ticks = computed(() => Array.from({ length: 4 }, (_, i) => bounds.value.low + (bounds.value.high - bounds.value.low) * i / 3))
const currentValue = computed(() => (mode.value === 'pnl' ? current.value?.pnl_cents : current.value?.equity_cents) ?? 0)
const tone = computed(() => mode.value === 'pnl' ? (currentValue.value > 0 ? 'is-up' : currentValue.value < 0 ? 'is-down' : '') : '')
const scope = computed(() => mode.value === 'pnl' ? '已扣除累计投入，追加资金不会抬高盈利。' : '包含追加资金；资产增长不等于投资盈利。')
function inspect(event: PointerEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (!props.points.length || !rect.width) return
  selected.value = Math.max(0, Math.min(props.points.length - 1, Math.round(((event.clientX - rect.left) / rect.width * chartWidth.value - left) / plotWidth.value * (props.points.length - 1))))
}
function onKey(event: KeyboardEvent) {
  if (!props.points.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key)) return
  event.preventDefault()
  if (event.key === 'Escape') { selected.value = null; return }
  if (event.key === 'Home') { selected.value = 0; return }
  if (event.key === 'End') { selected.value = props.points.length - 1; return }
  selected.value = Math.max(0, Math.min(props.points.length - 1, (selected.value ?? props.points.length - 1) + (event.key === 'ArrowLeft' ? -1 : 1)))
}
function changeMode(value: unknown) {
  if (value !== 'pnl' && value !== 'equity') return
  mode.value = value
  selected.value = null
}
</script>
<template>
  <Card class="equity-card">
    <CardHeader class="border-b">
      <CardTitle class="flex items-center gap-1.5">
        账户曲线
        <Tooltip><TooltipTrigger as-child><Button access="read" variant="ghost" type="button" class="equity-card__info" aria-label="查看曲线计算口径"><Info class="size-3.5" /></Button></TooltipTrigger><TooltipContent>{{ scope }}</TooltipContent></Tooltip>
      </CardTitle>
      <CardAction><ToggleGroup :model-value="mode" type="single" size="sm" variant="outline" aria-label="曲线指标" @update:model-value="changeMode"><ToggleGroupItem value="pnl">盈利</ToggleGroupItem><ToggleGroupItem value="equity">资产</ToggleGroupItem></ToggleGroup></CardAction>
    </CardHeader>
    <CardContent class="equity-card__body">
      <PageBusy v-if="loading && !points.length" busy label="加载账户曲线…" class="equity-card__state" />
      <Alert v-else-if="error" variant="destructive" class="equity-card__state"><AlertTitle class="line-clamp-none">{{ error }}</AlertTitle></Alert>
      <template v-else-if="points.length">
        <div class="equity-card__readout" aria-live="polite">
          <strong :class="tone">{{ mode === 'pnl' && currentValue > 0 ? '+' : '' }}{{ agentMoney(currentValue) }}<small>元</small></strong>
          <span class="equity-card__when">{{ current?.day }}<em v-if="current?.stale">含陈旧报价</em></span>
        </div>
        <svg :viewBox="`0 0 ${chartWidth} 235`" role="img" tabindex="0"
          :aria-label="`${mode === 'pnl' ? '累计盈利' : '资产'}曲线，共${points.length}个日度快照，最新${agentMoney(mode === 'pnl' ? last?.pnl_cents : last?.equity_cents)}元。方向键查看历史。`"
          @pointerdown="inspect" @pointermove="inspect" @pointerleave="selected = null" @keydown="onKey">
          <defs><linearGradient :id="gradientId" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--seal)" stop-opacity="0.18" /><stop offset="1" stop-color="var(--seal)" stop-opacity="0" /></linearGradient></defs>
          <g v-for="tick in ticks" :key="tick" class="chart-grid"><line :x1="left" :x2="right" :y1="y(tick)" :y2="y(tick)" /><text :x="left - 8" :y="y(tick) + 4" text-anchor="end">{{ tick.toLocaleString('zh-CN', { maximumFractionDigits: Math.abs(tick) < 10 ? 2 : 0 }) }}</text></g>
          <line v-if="mode === 'pnl'" class="zero-line" :x1="left" :x2="right" :y1="y(0)" :y2="y(0)" />
          <path v-if="areaPath" :fill="`url(#${gradientId})`" :d="areaPath" />
          <polyline v-if="points.length > 1" class="equity-line" :points="coordinates" />
          <circle v-if="last" class="equity-dot" :cx="x(points.length - 1)" :cy="y(values.at(-1) ?? 0)" r="3" />
          <g v-if="selected !== null && current"><line class="cursor-line" :x1="x(selected)" :x2="x(selected)" y1="16" y2="203" /><circle class="equity-dot" :cx="x(selected)" :cy="y(values[selected] ?? 0)" r="4" /></g>
          <text class="axis-date" :x="left" y="227">{{ points[0]?.day }}</text><text class="axis-date" :x="right" y="227" text-anchor="end">{{ last?.day }}</text>
        </svg>
        <footer class="equity-card__foot"><span>{{ points.length }} 个日度快照</span><span>最新估值 {{ agentTime(last?.at) }}</span></footer>
      </template>
      <EmptyState v-else description="暂无账户快照" />
    </CardContent>
  </Card>
</template>
<style scoped>
.equity-card { min-width: 0; }
.equity-card__body { display: flex; flex-direction: column; gap: 8px; min-height: 180px; }
.equity-card__state { margin: 16px 0; }
.equity-card__info { display: inline-grid; place-items: center; padding: 3px; border-radius: 4px; color: var(--text-tertiary); }
.equity-card__info:focus-visible, svg:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.equity-card__readout { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; }
.equity-card__readout strong { color: var(--text-primary); font-family: var(--mono); font-size: 20px; font-weight: 600; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.equity-card__readout strong.is-up { color: var(--up); }
.equity-card__readout strong.is-down { color: var(--down); }
.equity-card__readout small { margin-left: 4px; color: var(--text-tertiary); font-family: var(--font); font-size: 12px; font-weight: 400; }
.equity-card__when { color: var(--text-tertiary); font-family: var(--mono); font-size: 11px; font-variant-numeric: tabular-nums; }
.equity-card__when em { margin-left: 8px; color: var(--warn-ink); font-style: normal; }
svg { display: block; width: 100%; height: auto; max-height: 240px; overflow: visible; touch-action: pan-y; }
.chart-grid line { stroke: var(--border-subtle); stroke-width: 1; stroke-dasharray: 3 5; }
.chart-grid text, .axis-date { fill: var(--text-tertiary); font-family: var(--mono); font-size: 13px; }
.equity-line { fill: none; stroke: var(--seal); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.equity-dot { fill: var(--seal); stroke: var(--surface); stroke-width: 1.5; }
.zero-line { stroke: var(--border-strong); stroke-width: 1; stroke-dasharray: 2 3; }
.cursor-line { stroke: var(--text-tertiary); stroke-dasharray: 3 4; }
.equity-card__foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; padding-top: 6px; border-top: 1px solid var(--border-subtle); color: var(--text-tertiary); font-size: 11px; }
</style>
