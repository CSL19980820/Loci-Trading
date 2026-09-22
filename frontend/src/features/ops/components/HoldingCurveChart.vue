<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw, ZoomIn, ZoomOut } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useChartTheme } from '@/shared/lib/useChartTheme'
import { withAlpha } from '@/shared/lib/chartTokens'
import { formatDateTime } from '@/shared/lib/dateTime'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import type { HoldingCurve } from '@/shared/types/holdingCurve'
import { curveTickLabel, type CurveMetric } from './holdingCurvePresentation'
import { buildCurveTimeline, curveSessionDay, drawdownAxisMin } from './holdingCurveTimeline'
import { curveRangeStatistics } from './holdingCurveStatistics'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent, CanvasRenderer])
const props = defineProps<{ data: HoldingCurve; mode: CurveMetric; threshold: number }>()
const host = ref<HTMLDivElement>()
const mobile = useMobileLayout()
const { tokens } = useChartTheme()
const selectedIndex = ref<number | null>(null)
const zoom = ref(100)
let chart: echarts.ECharts | undefined
let observer: ResizeObserver | undefined
let lastScope = ''
const metricLabel = computed(() => props.mode === 'drawdown' ? '回撤' : props.mode === 'return' ? '收益率' : '盈亏金额')
const timeline = computed(() => buildCurveTimeline(props.data.points, props.mode, props.data))
const chartPoints = computed(() => timeline.value.samples)
const statistics = computed(() => curveRangeStatistics(chartPoints.value))
const statisticUnit = computed(() => props.mode === 'pnl' ? '元' : '%')
const warningOutside = computed(() => props.mode === 'drawdown' && -props.threshold < drawdownAxisMin(chartPoints.value, props.threshold))
const inspected = computed(() => selectedIndex.value == null ? null : props.data.points[selectedIndex.value] ?? null)
const number = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : (Math.abs(value) < .0000001 ? 0 : value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
function inspectExtreme(which: 'minimum' | 'maximum' | 'latest'): void {
  const sample = statistics.value?.[which]
  if (!sample) return
  if (zoom.value < 100) zoomTo(100)
  inspect(chartPoints.value.findIndex(point => point.index === sample.index))
}
function description(index: number): string {
  const point = props.data.points[index]
  if (!point) return ''
  const values = [formatDateTime(point.at)]
  if (point.nav == null || point.quality === 'unavailable') values.push('估值不可用')
  else values.push(`回撤  ${number(point.drawdown_pct)}%`, `收益率  ${number((point.nav - 1) * 100)}%`, `盈亏  ${number(point.pnl_cents == null ? null : point.pnl_cents / 100)} 元`)
  if (point.kind === 'buy' || point.kind === 'sell') values.push(`${point.kind === 'buy' ? '买入' : '卖出'} ${point.trade_quantity} 股 · 费用 ${number((point.fees_cents ?? 0) / 100)} 元`)
  if (point.quantity != null && props.data.code) values.push(`持仓 ${point.quantity} 股`)
  if (point.quote_at) values.push(`行情 ${formatDateTime(point.quote_at)}`)
  if (timeline.value.samples.find(s => s.index === index)?.gapBefore) values.push('与上一有效点之间存在缺测；虚线仅连接端点')
  return values.join('\n')
}
function inspect(index: number): void {
  const item = chartPoints.value[index]
  if (!item) return
  selectedIndex.value = item.index
  // 手机使用固定读数栏，不向未创建的富文本浮层发送手动显示动作。
  if (!mobile.value) chart?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: timeline.value.sampleToData[index] })
}
function zoomTo(value: number): void {
  zoom.value = Math.max(10, Math.min(100, value))
  chart?.dispatchAction({ type: 'dataZoom', start: 100 - zoom.value, end: 100 })
}
function onKey(event: KeyboardEvent): void {
  const points = chartPoints.value
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key) || !points.length) return
  event.preventDefault()
  if (event.key === 'Escape') {
    selectedIndex.value = null
    if (!mobile.value) chart?.dispatchAction({ type: 'hideTip' })
    chart?.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' })
    return
  }
  const index = selectedIndex.value == null ? points.length - 1 : Math.max(0, points.findIndex(item => item.index === selectedIndex.value))
  if (zoom.value < 100) zoomTo(100)
  inspect(event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.max(0, Math.min(points.length - 1, index + (event.key === 'ArrowLeft' ? -1 : 1))))
}
function onChartClick(event: { offsetX?: number; offsetY?: number }): void {
  if (!chart || event.offsetX == null || event.offsetY == null || !chart.containPixel('grid', [event.offsetX, event.offsetY])) return
  const coords = chart.convertFromPixel({ seriesIndex: 0 }, [event.offsetX, event.offsetY]) as number[]
  const position = coords?.[0]
  if (position == null || !Number.isFinite(position)) return
  inspect(Math.max(0,Math.min(chartPoints.value.length-1,Math.round(position))))
}
function render(): void {
  if (!host.value?.clientWidth || !host.value.clientHeight) return
  if (!chart) {
    chart = echarts.init(host.value, undefined, { renderer: 'canvas' })
    chart.getZr().on('click', onChartClick)
    chart.on('updateAxisPointer', (event: unknown) => {
      const value = event as { axesInfo?: { seriesDataIndices?: { dataIndex: number }[] }[] }
      const index = value.axesInfo?.[0]?.seriesDataIndices?.[0]?.dataIndex
      const sample = index == null ? null : timeline.value.dataToSample[index]
      if (sample != null && chartPoints.value[sample]) selectedIndex.value = chartPoints.value[sample]!.index
    })
  }
  const scope = `${props.data.code}:${props.data.start}:${props.data.end}`
  if (scope !== lastScope) { selectedIndex.value = null; zoom.value = 100; lastScope = scope }
  const points = chartPoints.value
  if (!points.length) { chart.clear(); return }
  const t = tokens.value
  const chartWidth = host.value.clientWidth
  const compact = mobile.value
  const first = points[0]!.timestamp, last = points.at(-1)!.timestamp
  const spanDays = Math.max(0, (last - first) / 86400000)
  const sameDay = formatDateTime(points[0]!.point.at).slice(0, 10) === formatDateTime(points.at(-1)!.point.at).slice(0, 10)
  const stats = statistics.value!
  const axisMin = drawdownAxisMin(points,props.threshold)
  const interval = Math.max(1,Math.ceil((points.length-1)/(compact ? 4 : 7)))
  const color = props.mode === 'drawdown' ? t.up : t.info
  const dayLines = timeline.value.days.length <= 12 ? timeline.value.days : []
  const marks: Record<string, unknown>[] = []
  const minimum = points.findIndex(point => point.index === stats.minimum.index)
  const maximum = points.findIndex(point => point.index === stats.maximum.index)
  const final = points.length - 1
  const lastName = '最新'
  const flat = stats.minimum.value === stats.maximum.value
  const extrema = flat ? [{index:minimum,name:'最高 / 最低',low:true}] : [
    {index:minimum,name:'最低',low:true}, {index:maximum,name:'最高',low:false},
  ]
  for (const mark of extrema) {
    const value = points[mark.index]!.value
    const edge = mark.index / Math.max(1, points.length - 1)
    marks.push({ name:mark.name, coord:[mark.index,value], value,
      itemStyle:{color:t.sheet,borderColor:mark.low?t.up:t.info,borderWidth:2},
      label:{show:true,formatter:`${mark.name} ${number(value)}${statisticUnit.value}`,position:mark.low?'top':'bottom',
        align:edge<.25?'left':edge>.75?'right':'center',distance:8,color:t.ink,fontSize:compact?10:11,
        backgroundColor:withAlpha(t.sheet,.94),padding:[2,4],borderRadius:3},
    })
  }
  if (!extrema.some(mark => mark.index === final)) {
    const nearExtreme = extrema.some(mark => Math.abs(mark.index-final)/Math.max(1,points.length-1)*chartWidth < 120
      && Math.abs(points[mark.index]!.value-points[final]!.value) < Math.max(.00001, stats.spread*.16))
    marks.push({name:lastName,coord:[final,points[final]!.value],value:points[final]!.value,
      itemStyle:{color:t.sheet,borderColor:color,borderWidth:2},
      label:{show:!nearExtreme,formatter:`${lastName} ${number(points[final]!.value)}${statisticUnit.value}`,position:'left',distance:8,
        color:t.ink,fontSize:compact?10:11,backgroundColor:withAlpha(t.sheet,.94),padding:[2,4],borderRadius:3},
    })
  }
  chart.setOption({
    animation: false,
    grid: { left: compact ? 46 : 65, right: compact ? 20 : 30, top: compact ? 30 : 44, bottom: compact ? 30 : 38 },
    tooltip: { trigger: 'axis', triggerOn: 'mousemove|click', showContent: !compact, confine: true, renderMode: 'richText',
      formatter: (raw: unknown) => { const item = (Array.isArray(raw) ? raw[0] : raw) as { dataIndex?: number }; const index = item?.dataIndex; const sample = index == null ? null : timeline.value.dataToSample[index]; return sample == null ? '' : description(points[sample]?.index ?? -1) },
      textStyle: { color: t.ink, fontSize: 12, lineHeight: 21 }, backgroundColor: t.sheet, borderColor: t.rule,
    },
    xAxis: { type: 'value', min: points.length === 1 ? -.5 : 0, max: points.length === 1 ? .5 : points.length-1, interval,
      axisTick: { show:false }, axisLine: { show:true, lineStyle:{color:t.rule} }, splitLine:{show:false},
      axisPointer: { show:true, snap:true, lineStyle:{color:t.mist,type:'dashed'}, label:{show:false} },
      axisLabel: { color:t.mist,fontSize:compact?10:11,hideOverlap:true,showMinLabel:true,showMaxLabel:true,
        formatter: (position:number) => {
          const index=Math.round(position), item=points[index], prev=points[index-interval]
          if (!item || position!==index) return ''
          if (!sameDay && prev && curveSessionDay(prev.timestamp)===curveSessionDay(item.timestamp)) return ''
          return curveTickLabel(item.timestamp,sameDay,spanDays)
        },
      },
    },
    yAxis: { type: 'value', scale: props.mode !== 'drawdown', max: props.mode === 'drawdown' ? 0 : undefined, min: props.mode === 'drawdown' ? axisMin : undefined, splitNumber: 4,
      axisLabel: { color: t.mist, fontSize: 11, formatter: (value: number) => props.mode === 'pnl' ? Math.abs(value) >= 10000 ? `${+(value / 10000).toFixed(1)}万` : `${+value.toFixed(0)}` : `${+value.toFixed(2)}%` },
      splitLine: { lineStyle: { color: withAlpha(t.rule, .6), type: 'dashed' } },
    },
    dataZoom: [{ type: 'inside', start: 100 - zoom.value, end: 100, filterMode: 'none', zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: false, disabled: compact }],
    series: [{ name: metricLabel.value, type: 'line', data: timeline.value.mainData, connectNulls: false, smooth: false, showSymbol: points.length < 3, symbol: 'circle', symbolSize: 5,
      lineStyle: { width: compact ? 2 : 2.2, color }, itemStyle: { color },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: withAlpha(color, .02) }, { offset: 1, color: withAlpha(color, .13) }]) },
      markPoint: { symbol: 'circle', symbolSize: 6, tooltip: { show: false }, data: marks },
      markLine: { silent:true, symbol:'none', label:{show:false}, animation:false, data:[
        {name:'区间均值',yAxis:stats.average,lineStyle:{color:t.warn,width:1.3,type:'dashed'},
          label:{show:true,formatter:`均值 ${number(stats.average)}${statisticUnit.value}`,position:flat?'insideEndBottom':'insideStartTop',
            color:t.warn,fontSize:compact?10:11,backgroundColor:withAlpha(t.sheet,.94),padding:[2,4],borderRadius:3}},
        ...dayLines.map(index => ({xAxis:index-.5,lineStyle:{color:withAlpha(t.rule,.55),width:1,type:'dotted'},label:{show:false}})),
        ...timeline.value.bridges.map(bridge => [
          {coord:bridge.from,lineStyle:{color:t.mist,width:1.4,type:'dashed'},label:{show:false}},
          {coord:bridge.to},
        ]),
        ...(props.mode === 'drawdown' && !warningOutside.value ? [{yAxis:-props.threshold,lineStyle:{color:t.warn,width:1,type:'dashed'},label:{show:true,formatter:`预警 −${props.threshold}%`,position:'insideEndTop',fontSize:11,color:t.warn}}] : []),
      ] },
    }],
  }, { notMerge: true })
}
onMounted(() => { observer = new ResizeObserver(() => { chart?.resize(); render() }); if (host.value) observer.observe(host.value); render() })
onActivated(() => { chart?.resize(); render() })
watch(() => [props.data, props.mode, props.threshold, tokens.value, mobile.value], render, { flush: 'post' })
onBeforeUnmount(() => { observer?.disconnect(); chart?.getZr().off('click', onChartClick); chart?.dispose(); chart = undefined })
</script>

<template>
  <section class="holding-chart-shell" :class="{'is-mobile':mobile}" :aria-label="`${data.name}${metricLabel}曲线`">
    <div v-if="statistics" class="holding-range" aria-label="所选区间统计">
      <Button access="read" variant="ghost" type="button" class="holding-range__item" aria-label="查看最低值时点" @click="inspectExtreme('minimum')"><span>最低</span><strong data-stat="minimum">{{ number(statistics.minimum.value) }}<small>{{ statisticUnit }}</small></strong></Button>
      <Button access="read" variant="ghost" type="button" class="holding-range__item" aria-label="查看最高值时点" @click="inspectExtreme('maximum')"><span>最高</span><strong data-stat="maximum">{{ number(statistics.maximum.value) }}<small>{{ statisticUnit }}</small></strong></Button>
      <div class="holding-range__item"><span>平均</span><strong data-stat="average">{{ number(statistics.average) }}<small>{{ statisticUnit }}</small></strong></div>
      <div class="holding-range__item"><span>区间差</span><strong data-stat="spread">{{ number(statistics.spread) }}<small>{{ mode === 'pnl' ? '元' : '个百分点' }}</small></strong></div>
      <Button access="read" variant="ghost" type="button" class="holding-range__item holding-range__latest" :title="formatDateTime(statistics.latest.point.at)" aria-label="查看最新值时点" @click="inspectExtreme('latest')"><span>最新</span><strong data-stat="latest">{{ number(statistics.latest.value) }}<small>{{ statisticUnit }}</small></strong></Button>
    </div>
    <div class="holding-chart-plot">
      <div v-if="!mobile" class="holding-chart-tools" aria-label="图表缩放">
        <Button access="read" variant="ghost" size="icon-sm" aria-label="放大曲线" :disabled="zoom <= 10" @click="zoomTo(zoom / 2)"><ZoomIn /></Button>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="缩小曲线" :disabled="zoom >= 100" @click="zoomTo(zoom * 2)"><ZoomOut /></Button>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="重置曲线缩放" :disabled="zoom >= 100" @click="zoomTo(100)"><RotateCcw /></Button>
      </div>
    <div ref="host" class="holding-curve-chart" role="img" tabindex="0" :aria-label="`${data.name}${metricLabel}曲线。左右方向键查看时点，Home、End 跳至首末点。`" @keydown="onKey" />
    </div>
    <div v-if="mobile" class="holding-chart-readout" aria-live="polite">
      <template v-if="inspected"><time>{{ formatDateTime(inspected.at).slice(5,16) }}</time><span v-if="inspected.nav == null || inspected.quality === 'unavailable'">估值不可用</span><template v-else><span>回撤 <b>{{ number(inspected.drawdown_pct) }}%</b></span><span>盈亏 <b>{{ number(inspected.pnl_cents == null ? null : inspected.pnl_cents / 100) }}元</b></span></template></template>
      <template v-else><span>轻点曲线查看该时点</span></template>
    </div>
    <span v-else class="sr-only" aria-live="polite">{{ selectedIndex == null ? '' : description(selectedIndex) }}</span>
  </section>
</template>

<style scoped>
.holding-chart-shell { display:flex; flex-direction:column; flex:1 1 0%; min-height:0; width:100%; min-width:0; }
.holding-range { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); flex:none; gap:0; padding:18px 8px 16px; border-bottom:1px solid var(--border-subtle); }
.holding-range__item { display:flex; flex-direction:column; align-items:flex-start; gap:6px; min-width:0; padding:0 18px; border:0; border-right:1px solid var(--border-subtle); background:transparent; color:var(--text-primary); text-align:left; }
.holding-range__item:last-child { border-right:0; }
button.holding-range__item { cursor:pointer; }
button.holding-range__item:hover strong { color:var(--seal-ink); }
.holding-range__item:focus-visible { outline:2px solid var(--focus-ring); outline-offset:3px; border-radius:4px; }
.holding-range__item>span { color:var(--text-tertiary); font-size:12px; }
.holding-range strong { font-size:clamp(17px,1.55vw,23px); font-weight:600; line-height:1.35; font-variant-numeric:tabular-nums; letter-spacing:-.035em; overflow-wrap:anywhere; }
.holding-range small { margin-left:5px; font-size:11px; font-weight:400; letter-spacing:0; color:var(--text-tertiary); white-space:nowrap; }
.holding-range__latest strong { color:var(--seal-ink); }
.holding-chart-plot { display:flex; flex:1 1 0%; position:relative; min-height:220px; min-width:0; }
.holding-chart-tools { position:absolute; z-index:1; top:5px; right:12px; display:flex; gap:2px; }
.holding-chart-tools svg { width:14px; height:14px; }
.holding-curve-chart { width:100%; flex:1 1 0%; min-height:220px; min-width:0; touch-action:pan-y; outline:none; }
.holding-curve-chart:focus-visible { outline:2px solid var(--focus-ring); outline-offset:-2px; }
.holding-chart-readout { display:flex; flex-wrap:wrap; align-items:center; gap:4px 10px; min-height:34px; padding:4px 12px 8px; color:var(--text-tertiary); font-size:11px; line-height:1.5; font-variant-numeric:tabular-nums; }
.holding-chart-readout b { color:var(--text-primary); font-weight:550; }
@media(max-width:767px) {
 .holding-range { padding:12px 0; row-gap:14px; grid-template-columns:repeat(3,minmax(0,1fr)); }
 .holding-range__item { padding:0 10px; gap:4px; }
 .holding-range__item:nth-child(3) { border-right:0; }
 .holding-range__item>span { font-size:11px; }
 .holding-range strong { font-size:17px; }
 .holding-range small { font-size:10px; margin-left:3px; }
 .holding-chart-shell { min-height:390px; }
 .holding-chart-plot,.holding-curve-chart { min-height:235px; }
}
</style>
