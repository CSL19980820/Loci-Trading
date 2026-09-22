<script setup lang="ts">
import { Card, CardHeader, CardContent, CardTitle } from '@/shared/components/ui/card'
import { computed } from 'vue'

import { artifactShellTitle, parseSources } from '../assistantArtifacts'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Badge } from '@/shared/components/ui/badge'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const sources = computed(() => parseSources(props.artifact.data ?? {}))
</script>

<template>
  <Card
    class="assistant-source-strip assistant-card assistant-card--tight"
    :aria-label="artifactShellTitle(artifact)"
  >
    <CardHeader class="assistant-card__heading">
      <CardTitle>{{ artifactShellTitle(artifact) }}</CardTitle>
    </CardHeader>
    <CardContent class="assistant-card__content">
    <div v-if="sources.length" class="assistant-source-strip__list">
      <Badge
        v-for="(source, index) in sources"
        :key="`${source.label}-${index}`"
        variant="outline"
        class="assistant-source-strip__item"
        :title="[source.detail, source.code, source.date, source.hash].filter(Boolean).join(' · ')"
      >
        {{ source.label }}
        <span v-if="source.code" class="assistant-source-strip__meta">{{ source.code }}</span>
        <span v-if="source.date" class="assistant-source-strip__meta">{{ source.date }}</span>
      </Badge>
    </div>
    <EmptyState v-else description="无来源条目" reason="换个问法重问" />
    </CardContent>
  </Card>
</template>

<style scoped>
.assistant-source-strip__list { display: flex; flex-wrap: wrap; gap: .35rem; }
.assistant-source-strip__meta {
  margin-left: .25rem; color: var(--mist); font-family: var(--mono); font-size: var(--ai-fs-meta);
}
</style>
