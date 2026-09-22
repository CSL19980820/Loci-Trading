<script setup lang="ts">
import { Card, CardHeader, CardContent, CardTitle } from '@/shared/components/ui/card'
import { computed } from 'vue'
import { artifactShellTitle, parseEquityPayload } from '../assistantArtifacts'
import EquityLineChart from '@/shared/components/charts/EquityLineChart.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const series = computed(() => parseEquityPayload(props.artifact.data ?? {}))
const ready = computed(() => series.value.dates.length > 1 && series.value.values.filter(value => value != null).length > 1)
</script>

<template>
  <Card class="assistant-equity-card assistant-card" :aria-label="artifactShellTitle(artifact)">
    <CardHeader class="assistant-card__heading">
      <CardTitle>{{ artifactShellTitle(artifact) }}</CardTitle>
    </CardHeader>
    <CardContent class="assistant-card__content">
    <EquityLineChart
      v-if="ready"
      :dates="series.dates"
      :values="series.values"
      :height="300"
      :format-mode="artifact.data.format_mode === 'money' ? 'money' : 'index'"
    />
    <EmptyState v-else description="净值序列不足" reason="多攒几天数据再看" />
    </CardContent>
  </Card>
</template>
