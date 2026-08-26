<script setup lang="ts">
/**
 * 角色演进图：离散角色档位 × 交易日阶梯线。
 * 数字只表示角色档，不是收益。
 */
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  ROLE_AXIS_LABELS,
  roleLabelCn,
  type RoleTimelineModel,
} from './paperRoleTimeline'

echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const props = defineProps<{
  model: RoleTimelineModel
  height?: number
}>()

const PALETTE = ['#0f766e', '#b45309', '#1d4ed8', '#be123c', '#57534e', '#047857']

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null

const hasPoints = computed(() =>
  props.model.series.some((s) => s.ranks.some((r) => r != null)),
)

function buildOption(): echarts.EChartsCoreOption {
  const { dates, series } = props.model
  const zoom = dates.length > 24

  return {
    animationDuration: 240,
    color: PALETTE,
    grid: {
      left: 56,
      right: 16,
      top: 36,
      bottom: zoom ? 52 : 32,
    },
    legend: {
      top: 0,
      type: 'scroll',
      textStyle: { color: '#5c5660', fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : []
        if (!rows.length) return ''
        const axis = String((rows[0] as { axisValue?: string }).axisValue ?? '')
        const lines = [`<div>${axis}</div>`]
        for (const raw of rows) {
          const item = raw as {
            seriesName?: string
            dataIndex?: number
            marker?: string
            seriesIndex?: number
          }
          const idx = item.seriesIndex ?? 0
          const di = item.dataIndex ?? 0
          const role = series[idx]?.roles[di]
          if (role == null) continue
          lines.push(
            `${item.marker || ''}${item.seriesName || ''}：${roleLabelCn(role)}`,
          )
        }
        return lines.join('<br/>')
      },
    },
    dataZoom: zoom
      ? [
          { type: 'inside', start: Math.max(0, 100 - (2400 / dates.length)), end: 100 },
          { type: 'slider', height: 18, bottom: 4 },
        ]
      : undefined,
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: '#8a8690',
        fontSize: 11,
        hideOverlap: true,
        formatter: (v: string) => (v.length >= 10 ? v.slice(5) : v),
      },
      axisLine: { lineStyle: { color: '#ddd8e0' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 4,
      interval: 1,
      axisLabel: {
        color: '#8a8690',
        fontSize: 11,
        formatter: (v: number) => ROLE_AXIS_LABELS[v] ?? '',
      },
      splitLine: { lineStyle: { color: '#eeeaf0', type: 'dashed' } },
    },
    series: series.map((s) => ({
      type: 'line' as const,
      name: `${s.name}(${s.code})`,
      data: s.ranks,
      step: 'end' as const,
      connectNulls: false,
      showSymbol: true,
      symbolSize: 7,
      lineStyle: { width: 2 },
      emphasis: { focus: 'series' as const },
    })),
  }
}

function render(): void {
  if (!chartEl.value) return
  // jsdom / 折叠容器宽高为 0 时 init 会留下坏 painter，直接跳过
  if (chartEl.value.clientWidth < 8 || chartEl.value.clientHeight < 8) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  }
  if (!hasPoints.value) {
    chart.clear()
    return
  }
  try {
    chart.setOption(buildOption(), { notMerge: true })
  } catch {
    // 测试环境或卸载竞态：忽略绘制失败
  }
}

onMounted(() => {
  render()
  if (chartEl.value) {
    resizeObs = new ResizeObserver(() => chart?.resize())
    resizeObs.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  resizeObs?.disconnect()
  resizeObs = null
  chart?.dispose()
  chart = null
})

watch(
  () => [props.model.dates, props.model.series] as const,
  () => render(),
  { deep: true },
)
</script>

<template>
  <div
    class="role-timeline"
    :style="height != null ? { height: `${height}px` } : undefined"
  >
    <el-empty
      v-if="!hasPoints"
      description="这只票还没有留痕，盯盘或日终总结跑过后会出现观测点"
      :image-size="56"
    />
    <div
      v-else
      ref="chartEl"
      class="role-timeline__canvas"
      role="img"
      aria-label="角色演进图"
    />
  </div>
</template>

<style scoped>
.role-timeline {
  width: 100%;
  min-height: 14rem;
  height: 16rem;
}
.role-timeline__canvas {
  width: 100%;
  height: 100%;
  min-height: 14rem;
}
</style>
