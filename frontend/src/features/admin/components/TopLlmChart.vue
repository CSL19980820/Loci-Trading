<script setup lang="ts">
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChartTheme } from '@/shared/lib/useChartTheme'
import type { TopLlmUsageItem } from '@/shared/types/admin'
import { formatTokens } from '../lib/adminFormat'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  items: TopLlmUsageItem[]
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null
const { tokens } = useChartTheme()

const sortedItems = computed(() => {
  return [...props.items].sort((a, b) => a.value - b.value)
})

function buildOption(): echarts.EChartsCoreOption {
  const data = sortedItems.value
  const userNames = data.map((d) => d.user_id)
  const values = data.map((d) => d.value)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        if (!item) return ''
        return `<strong>${item.name}</strong><br/>${formatTokens(Number(item.value))} tokens（词元）`
      },
    },
    grid: {
      top: 10,
      bottom: 24,
      left: 80,
      right: 40,
    },
    xAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: tokens.value.rule } },
      axisLabel: {
        color: tokens.value.mist,
        formatter: (val: number) => formatTokens(val),
        fontFamily: tokens.value.mono,
        fontSize: 11,
      },
      splitLine: { lineStyle: { color: tokens.value.rule, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: userNames,
      axisLine: { lineStyle: { color: tokens.value.rule } },
      axisLabel: {
        color: tokens.value.ink,
        fontSize: 12,
      },
    },
    series: [
      {
        name: 'LLM 用量（tokens）',
        type: 'bar',
        data: values,
        // 面板吃满高度后，只有两三个用户时 ECharts 会把条画成 200px 厚的色块；
        // 条形图读的是长度，厚度过了 24px 只是噪声
        barMaxWidth: 24,
        itemStyle: {
          color: tokens.value.seal,
          borderRadius: [0, 4, 4, 0],
        },
        label: {
          show: true,
          position: 'right',
          color: tokens.value.mist,
          fontSize: 11,
          formatter: (p: any) => formatTokens(p.value as number),
        },
      },
    ],
  }
}

function renderChart(): void {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
    if (typeof ResizeObserver !== 'undefined') {
      resizeObs = new ResizeObserver(() => chart?.resize())
      resizeObs.observe(chartEl.value)
    }
  }
  if (!props.items.length) {
    chart.clear()
    return
  }
  chart.setOption(buildOption(), { notMerge: true })
}

watch([() => props.items, tokens], () => {
  renderChart()
}, { deep: true })

onMounted(() => {
  renderChart()
})

onBeforeUnmount(() => {
  resizeObs?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="top-llm-chart">
    <div v-if="items.length > 0" ref="chartEl" class="chart-canvas" role="img" aria-label="当月大模型用量排行图" />
    <EmptyState v-else description="本月暂无大模型用量" reason="有调用后自动统计" />
  </div>
</template>

<style scoped>
.top-llm-chart {
  width: 100%;
  flex: 1 1 auto;
  min-height: calc(var(--row-h) * 8);
  display: flex;
  align-items: stretch;
  justify-content: stretch;
}

.chart-canvas {
  flex: 1 1 auto;
  min-width: 0;
  width: 100%;
  height: 100%;
  min-height: 0;
}

.top-llm-chart :deep(.empty-state) {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
