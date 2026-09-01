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

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { useChartTheme } from '@/shared/lib/useChartTheme'

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

/*
 * 角色档不是涨跌，调色板要的是「彼此分得开」而不是红绿语义，
 * 所以借 chartTokens 的定性色板（已按主题解析成字面量）。
 */
const { tokens } = useChartTheme()

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
    color: tokens.value.maPalette,
    grid: {
      left: 56,
      right: 16,
      top: 36,
      bottom: zoom ? 52 : 32,
    },
    legend: {
      top: 0,
      type: 'scroll',
      textStyle: { color: tokens.value.muted, fontSize: 11 },
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
        color: tokens.value.mist,
        fontSize: 11,
        hideOverlap: true,
        formatter: (v: string) => (v.length >= 10 ? v.slice(5) : v),
      },
      axisLine: { lineStyle: { color: tokens.value.rule } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 4,
      interval: 1,
      axisLabel: {
        color: tokens.value.mist,
        fontSize: 11,
        formatter: (v: number) => ROLE_AXIS_LABELS[v] ?? '',
      },
      splitLine: { lineStyle: { color: tokens.value.rule, type: 'dashed' } },
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

/* 换主题后 token 变了，canvas 是快照，必须重画 */
watch(tokens, () => render())
</script>

<template>
  <div
    class="role-timeline"
    :class="{ 'role-timeline--chart': hasPoints }"
    :style="height != null ? { height: `${height}px` } : undefined"
  >
    <EmptyState
      v-if="!hasPoints"
      description="这只票还没有留痕"
      reason="盯盘或日终总结跑过后出现观测点"
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
/*
 * 只留一份高度，且只在真出图时生效：ECharts 量的是父容器高度，所以画布需要具体值；
 * 但没有观测点时挂 16rem 就是一块死白。父层传 height 时内联样式优先级更高，仍然赢。
 */
.role-timeline {
  width: 100%;
}

.role-timeline--chart {
  height: 16rem;
}

.role-timeline__canvas {
  width: 100%;
  height: 100%;
}
</style>
