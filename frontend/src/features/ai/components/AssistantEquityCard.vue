<script setup lang="ts">
import { computed } from 'vue'
import { artifactShellTitle, parseEquityPayload } from '../assistantArtifacts'
import EquityLineChart from '@/shared/components/charts/EquityLineChart.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const series = computed(() => parseEquityPayload(props.artifact.data ?? {}))
const ready = computed(() => series.value.dates.length > 1 && series.value.values.length > 1)
</script>

<template>
  <section class="assistant-equity-card assistant-card" :aria-label="artifactShellTitle(artifact)">
    <div class="assistant-card__heading">
      <h3>{{ artifactShellTitle(artifact) }}</h3>
    </div>
    <EquityLineChart
      v-if="ready"
      :dates="series.dates"
      :values="series.values"
      :height="200"
    />
    <EmptyState v-else description="净值序列不足" reason="多攒几天数据再看" />
  </section>
</template>
