<script setup lang="ts">
import { computed } from 'vue'

import { artifactShellTitle, parseEquityPayload } from '../assistantArtifacts'
import EquityLineChart from '@/shared/components/charts/EquityLineChart.vue'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

const props = defineProps<{ artifact: AiChartArtifact }>()

const series = computed(() => parseEquityPayload(props.artifact.data ?? {}))
const ready = computed(() => series.value.dates.length > 1 && series.value.values.length > 1)
</script>

<template>
  <section class="assistant-equity-card" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-equity-card__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
    </div>
    <EquityLineChart
      v-if="ready"
      :dates="series.dates"
      :values="series.values"
      :height="200"
    />
    <el-empty v-else :image-size="48" description="净值序列不足，画不出曲线" />
  </section>
</template>

<style scoped>
.assistant-equity-card {
  margin-top: .15rem; padding: .55rem; border: 1px solid var(--rule);
  border-radius: var(--radius); background: var(--panel-2); width: 100%; min-width: 0;
}
.assistant-equity-card__heading { margin-bottom: .35rem; }
.assistant-equity-card h3 { margin: 0; font-size: var(--ai-fs-body); }
</style>
