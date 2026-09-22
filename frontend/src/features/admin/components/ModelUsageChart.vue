<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useChartTheme } from '@/shared/lib/useChartTheme'
import { withAlpha } from '@/shared/lib/chartTokens'
import type { ModelUsageItem } from '@/shared/api/admin'
import { formatTokens } from '../lib/adminFormat'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])
const props = defineProps<{ rows: ModelUsageItem[]; start: string; end: string; mode: 'line' | 'area'; metric: 'tokens' | 'calls'; incomplete?: boolean }>()
const host = ref<HTMLDivElement>()
const { tokens } = useChartTheme()
let chart: echarts.ECharts | undefined
let resize: ResizeObserver | undefined
const days = computed(() => {
  const output: string[] = []
  const from = new Date(`${props.start}T00:00:00Z`)
  const to = new Date(`${props.end}T00:00:00Z`)
  for (let cursor = from.getTime(); Number.isFinite(cursor) && cursor <= to.getTime() && output.length < 370; cursor += 86400000) output.push(new Date(cursor).toISOString().slice(0, 10))
  return output
})
const totals = computed(() => {
  const map = new Map<string, { input: number; output: number; calls: number }>()
  for (const row of props.rows) {
    const old = map.get(row.day) ?? { input: 0, output: 0, calls: 0 }
    old.input += row.input_tokens; old.output += row.output_tokens; old.calls += row.calls
    map.set(row.day, old)
  }
  return map
})
function render(): void {
  if (!host.value || !host.value.clientWidth || !host.value.clientHeight) return
  chart ??= echarts.init(host.value, undefined, { renderer: 'canvas' })
  const t = tokens.value
  const series = props.metric === 'calls' ? [{ key: 'calls' as const, name: '调用次数', color: t.info }] : [
    { key: 'input' as const, name: '输入 Tokens', color: t.info },
    { key: 'output' as const, name: '输出 Tokens', color: t.seal },
  ]
  chart.setOption({
    animationDuration: 180,
    legend: { top: 8, left: 12, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { color: t.muted, fontSize: 12 } },
    grid: { top: 52, left: 16, right: 20, bottom: days.value.length > 45 ? 48 : 20, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, renderMode: 'richText', valueFormatter: (value: unknown) => typeof value === 'number' ? value.toLocaleString('zh-CN') : '未取得数据' },
    xAxis: { type: 'category', data: days.value, boundaryGap: false, axisTick: { show: false }, axisLine: { lineStyle: { color: t.rule } }, axisLabel: { color: t.mist, hideOverlap: true, fontSize: 11, formatter: (value: string) => value.slice(5) } },
    yAxis: { type: 'value', min: 0, axisLabel: { color: t.mist, fontSize: 11, formatter: (value: number) => props.metric === 'tokens' ? formatTokens(value) : value.toLocaleString('zh-CN') }, splitLine: { lineStyle: { color: withAlpha(t.rule, .6), type: 'dashed' } } },
    dataZoom: days.value.length > 45 ? [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 2, borderColor: 'transparent' }] : [],
    series: series.map(item => ({
      type: 'line', name: item.name, data: days.value.map(day => totals.value.get(day)?.[item.key] ?? (props.incomplete ? null : 0)),
      smooth: .18, connectNulls: false, showSymbol: days.value.length < 20, symbolSize: 5,
      lineStyle: { width: 2, color: item.color }, itemStyle: { color: item.color },
      areaStyle: props.mode === 'area' ? { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: withAlpha(item.color, .28) }, { offset: 1, color: withAlpha(item.color, .02) }]) } : undefined,
      emphasis: { focus: 'series' },
    })),
  }, { notMerge: true })
}
onMounted(() => {
  resize = new ResizeObserver(() => { render(); chart?.resize() })
  if (host.value) resize.observe(host.value)
  render()
})
watch(() => [props.rows, props.start, props.end, props.mode, props.metric, props.incomplete, tokens.value], render, { deep: true, flush: 'post' })
onBeforeUnmount(() => { resize?.disconnect(); chart?.dispose(); chart = undefined })
</script>
<template><div ref="host" class="model-usage-chart" role="img" :aria-label="`${start}至${end}每日${metric === 'tokens' ? '输入和输出Tokens' : '调用次数'}${mode === 'area' ? '面积' : '曲线'}图`" /></template>
<style scoped>
.model-usage-chart { width:100%; flex:1 1 0%; min-width:0; min-height:180px; height:100%; }
</style>
