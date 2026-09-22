<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart, CandlestickChart, HeatmapChart, RadarChart, FunnelChart, GaugeChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, TitleComponent, DataZoomComponent, VisualMapComponent, RadarComponent, DatasetComponent, CalendarComponent, PolarComponent, SingleAxisComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RefreshCw, TriangleAlert } from '@lucide/vue'
import { Card, CardHeader, CardTitle, CardContent } from '@/shared/components/ui/card'
import { Alert, AlertTitle, AlertDescription } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { useChartTheme } from '@/shared/lib/useChartTheme'
import { artifactShellTitle, parseEchartsOption } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

echarts.use([LineChart, BarChart, PieChart, ScatterChart, CandlestickChart, HeatmapChart, RadarChart, FunnelChart, GaugeChart, GridComponent, LegendComponent, TooltipComponent, TitleComponent, DataZoomComponent, VisualMapComponent, RadarComponent, DatasetComponent, CalendarComponent, PolarComponent, SingleAxisComponent, CanvasRenderer])
const props = defineProps<{ artifact: AiChartArtifact }>()
const root = ref<HTMLElement | null>(null)
const failure = ref(false)
const { tokens } = useChartTheme()
const option = computed(() => parseEchartsOption(props.artifact.data ?? {}))
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null
let observed: HTMLElement | null = null
function dispose(): void {
  observer?.disconnect()
  observer = null
  chart?.dispose()
  chart = null
  observed = null
}
function render(): void {
  const el = root.value
  if (!el || !option.value || el.clientWidth < 8 || el.clientHeight < 8) return
  try {
    if (!chart) chart = echarts.init(el)
    const t = tokens.value
    const raw = option.value
    const tooltip = raw.tooltip && typeof raw.tooltip === 'object' && !Array.isArray(raw.tooltip) ? raw.tooltip as Record<string,unknown> : {}
    chart.setOption({
      color: t.maPalette,
      backgroundColor: 'transparent',
      textStyle: { color:t.muted, fontSize:12 },
      ...raw,
      // Model-provided labels are data, never HTML in a tooltip.
      tooltip: { ...tooltip, renderMode:'richText', confine:true },
    }, { notMerge:true })
    chart.resize()
    failure.value = false
  } catch {
    failure.value = true
  }
}
watch([root, option, tokens], () => {
  if (root.value !== observed) {
    dispose()
    observed = root.value
    if (observed && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => { if (!failure.value) render() })
      observer.observe(observed)
    }
  }
  render()
}, { flush:'post', deep:true })
async function retry(): Promise<void> { failure.value = false; await nextTick(); render() }
onBeforeUnmount(dispose)
</script>
<template>
  <Card class="assistant-echarts-card" :aria-label="artifactShellTitle(artifact)">
    <CardHeader><CardTitle class="text-sm">{{ artifactShellTitle(artifact) }}</CardTitle></CardHeader>
    <CardContent>
      <Alert v-if="failure"><TriangleAlert /><AlertTitle>统计图未能绘制</AlertTitle><AlertDescription>图表数据或配置不完整，正文不受影响。<Button access="read" variant="outline" size="sm" class="mt-2" @click="retry"><RefreshCw />重试绘制</Button></AlertDescription></Alert>
      <div v-show="option && !failure" ref="root" class="assistant-echarts-card__canvas" role="img" :aria-label="artifactShellTitle(artifact)" />
      <EmptyState v-if="!option" description="未返回可绘制的统计图" reason="请重新生成这张图表" />
    </CardContent>
  </Card>
</template>
<style scoped>
.assistant-echarts-card { min-width:0; gap:12px; box-shadow:none; }
.assistant-echarts-card__canvas { width:100%; height:clamp(300px,40dvh,440px); }
</style>
