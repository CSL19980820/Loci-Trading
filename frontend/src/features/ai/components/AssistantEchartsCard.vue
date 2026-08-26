<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { artifactShellTitle, parseEchartsOption } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

echarts.use([LineChart, BarChart, PieChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ artifact: AiChartArtifact }>()

const root = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null

const option = computed(() => parseEchartsOption(props.artifact.data ?? {}))

function render(): void {
  if (!root.value || !option.value) return
  if (!chart) chart = echarts.init(root.value)
  chart.setOption(option.value, true)
}

onMounted(() => {
  render()
  if (root.value && typeof ResizeObserver !== 'undefined') {
    resizeObs = new ResizeObserver(() => chart?.resize())
    resizeObs.observe(root.value)
  }
})

watch(option, () => render(), { deep: true })

onBeforeUnmount(() => {
  resizeObs?.disconnect()
  resizeObs = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="assistant-echarts-card" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-echarts-card__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
    </div>
    <div v-if="option" ref="root" class="assistant-echarts-card__canvas" role="img" />
    <el-empty v-else :image-size="48" description="统计图 option 无效或未通过校验" />
  </section>
</template>

<style scoped>
.assistant-echarts-card {
  margin-top: .15rem; padding: .55rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2); width: 100%; min-width: 0;
}
.assistant-echarts-card__heading { margin-bottom: .35rem; }
.assistant-echarts-card h3 { margin: 0; font-size: var(--ai-fs-body); }
.assistant-echarts-card__canvas { width: 100%; height: 14rem; }
</style>
