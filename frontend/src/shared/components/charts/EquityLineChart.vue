<script setup lang="ts">
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  MarkLineComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChartTheme } from '@/shared/lib/useChartTheme'
import { money } from '@/shared/lib/format'

echarts.use([LineChart, GridComponent, MarkLineComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  dates: string[]
  values: number[]
  color?: string
  height?: number
  /** money=金额；index=净值指数（如 1.0 起） */
  formatMode?: 'money' | 'index'
  /** 叠在图上的角标文案，如「最大回撤 -3.2%」 */
  overlayText?: string
  overlayTone?: 'up' | 'down' | ''
}>()

const chartEl = ref<HTMLElement | null>(null)
const { tokens } = useChartTheme()
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null

function fmtValue(v: number): string {
  if (!Number.isFinite(v)) return '—'
  if (props.formatMode === 'index') {
    return v.toFixed(3)
  }
  const abs = Math.abs(v)
  if (abs >= 1e6) return `${(v / 1e4).toFixed(1)}万`
  return money(v)
}

function resolveChartColor(input: string | undefined, fallback: string): string {
  const raw = (input || '').trim() || fallback
  if (!raw.startsWith('var(')) return raw
  const name = raw.slice(4, -1).trim()
  const resolved = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return resolved || fallback
}

function buildOption(): echarts.EChartsCoreOption {
  const values = props.values
  const dates = props.dates
  // 兜底走 A 股涨色，而不是欧美绿涨口径
  const t = tokens.value
  const color = resolveChartColor(props.color, t.up)
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
  const showAllLabels = values.length > 0 && values.length <= 40

  return {
    animationDuration: 280,
    grid: { left: 8, right: 16, top: 28, bottom: values.length > 40 ? 48 : 28, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => (typeof v === 'number' ? fmtValue(v) : String(v ?? '—')),
    },
    dataZoom: values.length > 40
      ? [{ type: 'inside', start: 0, end: 100 }, { type: 'slider', height: 18, bottom: 4 }]
      : undefined,
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: t.mist,
        fontSize: 11,
        fontFamily: t.mono,
        hideOverlap: true,
        formatter: (v: string) => (v.length >= 10 ? v.slice(5) : v),
      },
      axisLine: { lineStyle: { color: t.rule } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: t.mist,
        fontSize: 11,
        fontFamily: t.mono,
        formatter: (v: number) => fmtValue(v),
      },
      splitLine: { lineStyle: { color: t.rule, type: 'dashed' } },
    },
    series: [
      {
        type: 'line',
        name: props.formatMode === 'index' ? '诊断净值' : '总资产',
        data: values,
        smooth: 0.15,
        showSymbol: true,
        symbolSize: values.length <= 20 ? 8 : 5,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        // 面积必须跟着线走：此前写死为绿色，账本盈利时是「红线罩着一片绿」
        areaStyle: { color: `color-mix(in oklab, ${color} 12%, transparent)` },
        label: {
          show: showAllLabels,
          position: 'top',
          fontSize: 10,
          color: t.muted,
          formatter: (p: { value?: number | string }) => fmtValue(Number(p.value)),
        },
        labelLayout: { hideOverlap: true },
        markLine: {
          silent: true,
          symbol: 'none',
          label: {
            formatter: () => `均线 ${fmtValue(avg)}`,
            position: 'insideEndTop',
            color: t.mist,
            fontSize: 11,
          },
          lineStyle: { type: 'dashed', color: t.mist, width: 1 },
          data: [{ yAxis: avg }],
        },
      },
    ],
  }
}

function render(): void {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  }
  if (!props.values.length) {
    chart.clear()
    return
  }
  chart.setOption(buildOption(), { notMerge: true })
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
  () => [props.dates, props.values, props.color, props.formatMode, tokens.value] as const,
  () => render(),
  { deep: true },
)
</script>

<template>
  <div
    class="equity-line-chart"
    :class="{ 'equity-line-chart--fill': height == null }"
    :style="height != null ? { height: `${height}px` } : undefined"
  >
    <div
      v-if="overlayText"
      class="equity-line-chart__overlay"
      :class="{
        'is-up': overlayTone === 'up',
        'is-down': overlayTone === 'down',
      }"
    >
      {{ overlayText }}
    </div>
    <div
      ref="chartEl"
      class="equity-line-chart__canvas"
      role="img"
      aria-label="盈亏走势"
    />
  </div>
</template>

<style scoped>
.equity-line-chart {
  position: relative;
  width: 100%;
  min-height: clamp(9rem, 24dvh, 12rem);
}

.equity-line-chart--fill {
  flex: 1 1 auto;
  height: 100%;
  min-height: clamp(9rem, 24dvh, 12rem);
}

.equity-line-chart__canvas {
  width: 100%;
  height: 100%;
  min-height: inherit;
}

/* 图内读数浮层，组件内部层叠，不进全局 --z-* 序列 */
.equity-line-chart__overlay {
  position: absolute;
  top: 0.35rem;
  right: 0.75rem;
  z-index: 2;
  pointer-events: none;
  font: 600 0.82rem/1.2 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
  background: color-mix(in oklab, var(--sheet) 82%, transparent);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
}

.equity-line-chart__overlay.is-up {
  color: var(--up);
}

.equity-line-chart__overlay.is-down {
  color: var(--down);
}
</style>
